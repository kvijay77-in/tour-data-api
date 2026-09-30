"""
Unit tests for Lambda functions using moto for AWS mocking

Tests the Lambda functions with the hybrid table strategy:
- Shared tables (TourMaster, RiderProfile) resolved via env var
- Tour-specific tables resolved via STACK_NAME + tourId
"""

import os
import json
import importlib
import pytest
import boto3
from moto import mock_aws

# Set up path for imports
import sys
sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/tours')

from tests.fixtures.mock_data import MOCK_TOURS, MOCK_TOUR_ID
from models import TourStatus


def _make_auth_event(method='GET', body=None, path_params=None, groups=None):
    """Build a minimal authenticated API Gateway v2 event."""
    claims = {
        'sub': 'user-001',
        'email': 'user@example.com',
        'cognito:username': 'testuser',
    }
    if groups is not None:
        claims['cognito:groups'] = ','.join(groups)

    return {
        'version': '2.0',
        'requestContext': {
            'http': {'method': method},
            'authorizer': {'jwt': {'claims': claims}},
        },
        'pathParameters': path_params or {},
        'headers': {},
        'body': json.dumps(body) if body is not None else None,
    }


def _load_tours_handler(module_name):
    """Load a tours Lambda handler after moto/env setup."""
    module = importlib.import_module(module_name)
    return importlib.reload(module)


@pytest.fixture
def aws_credentials():
    """Mock AWS credentials for moto"""
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture
def dynamodb_mock(aws_credentials):
    """Create mock DynamoDB tables with test data"""
    with mock_aws():
        # Create DynamoDB resource
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        
        # Create shared TourMaster table with StatusIndex GSI
        tour_table = dynamodb.create_table(
            TableName='test-tour-master-table',
            KeySchema=[
                {'AttributeName': 'tourId', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'tourId', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'StatusIndex',
                    'KeySchema': [
                        {'AttributeName': 'status', 'KeyType': 'HASH'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 1,
                        'WriteCapacityUnits': 1
                    }
                }
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        
        # Populate with mock data
        for tour in MOCK_TOURS:
            tour_table.put_item(Item=tour)
        
        # Set environment variables for Lambda (hybrid table strategy)
        os.environ['TOUR_MASTER_TABLE'] = 'test-tour-master-table'
        os.environ['RIDER_PROFILE_TABLE'] = 'test-rider-table'
        os.environ['STACK_NAME'] = 'test-stack'
        os.environ['ENVIRONMENT'] = 'test'
        os.environ['SUBSCRIPTION_ID'] = 'test-sub-001'
        os.environ['PHOTOS_BUCKET'] = 'test-photos-bucket'
        os.environ['LOG_LEVEL'] = 'INFO'
        
        yield dynamodb


def test_get_active_tour_success(dynamodb_mock):
    """Test getting active tour - success case"""
    # Import after environment setup
    from get_active import lambda_handler
    
    # Create test event
    event = {
        'version': '2.0',
        'routeKey': 'GET /v1/tours/active',
        'rawPath': '/v1/tours/active',
        'headers': {},
        'requestContext': {
            'http': {'method': 'GET'}
        }
    }
    
    # Execute Lambda handler
    response = lambda_handler(event, None)
    
    # Assertions
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['success'] is True
    assert body['data']['tourId'] == MOCK_TOUR_ID
    assert body['data']['status'] == TourStatus.ACTIVE.value


def test_get_active_tour_not_found(dynamodb_mock):
    """Test getting active tour - no active tour"""
    from get_active import lambda_handler
    
    # Clear the mock tour
    table = dynamodb_mock.Table('test-tour-master-table')
    table.delete_item(Key={'tourId': MOCK_TOUR_ID})
    
    # Create test event
    event = {
        'version': '2.0',
        'routeKey': 'GET /v1/tours/active',
        'rawPath': '/v1/tours/active'
    }
    
    # Execute Lambda handler
    response = lambda_handler(event, None)
    
    # Assertions
    assert response['statusCode'] == 404
    body = json.loads(response['body'])
    assert body['success'] is False
    assert body['error']['code'] == 'NO_ACTIVE_TOUR'


def test_dynamodb_utils_shared_tables(dynamodb_mock):
    """Test DynamoDB utilities with shared table pattern"""
    import dynamodb_utils
    
    # Clear cache to use new mock
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    
    # Test get_item on shared table
    item = dynamodb_utils.get_item('TOUR_MASTER_TABLE', {'tourId': MOCK_TOUR_ID})
    assert item is not None
    assert item['tourId'] == MOCK_TOUR_ID
    
    # Test put_item on shared table
    new_tour = {
        'tourId': 'NewTour-2026',
        'name': 'New Test Tour',
        'status': TourStatus.PLANNING.value
    }
    dynamodb_utils.put_item('TOUR_MASTER_TABLE', new_tour)
    
    # Verify it was added
    retrieved = dynamodb_utils.get_item('TOUR_MASTER_TABLE', {'tourId': 'NewTour-2026'})
    assert retrieved['name'] == 'New Test Tour'
    
    # Test scan_items on shared table
    items = dynamodb_utils.scan_items(
        'TOUR_MASTER_TABLE',
        filter_expression='#status = :status',
        expression_values={':status': TourStatus.ACTIVE.value},
        expression_names={'#status': 'status'}
    )
    assert len(items) == 1
    assert items[0]['tourId'] == MOCK_TOUR_ID


def test_create_tour_defaults_to_master_record_only(dynamodb_mock):
    """POST /v1/tours saves TourMaster only when provisioning is omitted."""
    create_tour = _load_tours_handler('create_tour')
    event = _make_auth_event(
        method='POST',
        groups=['ADMINISTRATOR'],
        body={
            'tourId': 'NewTour-2026',
            'name': 'New Test Tour',
            'startDate': '2026-06-01',
            'endDate': '2026-06-10',
            'rideCount': 12,
        },
    )

    response = create_tour.lambda_handler(event, None)

    assert response['statusCode'] == 201
    body = json.loads(response['body'])
    assert body['success'] is True
    assert body['data']['status'] == TourStatus.PLANNING.value
    assert body['data']['rideCount'] == 12
    assert body['data']['selfQuitRidingAllowed'] is False
    assert 'provisioning' not in body['data']
    assert 'provisionedAt' not in body['data']

    table = dynamodb_mock.Table('test-tour-master-table')
    saved = table.get_item(Key={'tourId': 'NewTour-2026'})['Item']
    assert saved['status'] == TourStatus.PLANNING.value
    assert 'provisioning' not in saved

    dynamodb_client = boto3.client('dynamodb', region_name='us-east-1')
    table_names = dynamodb_client.list_tables()['TableNames']
    assert f"test-stack-TourRider-NewTour-2026" not in table_names


def test_get_tour_returns_false_default_for_legacy_setting(dynamodb_mock):
    get_tour = _load_tours_handler('get_tour')

    response = get_tour.lambda_handler(
        _make_auth_event(path_params={'tourId': MOCK_TOUR_ID}),
        None,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['data']['selfQuitRidingAllowed'] is False


def test_create_tour_rejects_non_boolean_quit_setting(dynamodb_mock):
    create_tour = _load_tours_handler('create_tour')
    event = _make_auth_event(
        method='POST',
        groups=['ADMINISTRATOR'],
        body={
            'tourId': 'InvalidTour-2026',
            'name': 'Invalid Test Tour',
            'startDate': '2026-06-01',
            'endDate': '2026-06-10',
            'rideCount': 12,
            'selfQuitRidingAllowed': 'true',
        },
    )

    response = create_tour.lambda_handler(event, None)

    assert response['statusCode'] == 400
    assert 'selfQuitRidingAllowed must be a boolean' in json.loads(response['body'])['error']['message']


def test_create_tour_provisions_tables_when_requested(dynamodb_mock):
    """POST /v1/tours provisions tour tables only when provisioning is true."""
    create_tour = _load_tours_handler('create_tour')
    event = _make_auth_event(
        method='POST',
        groups=['ADMINISTRATOR'],
        body={
            'tourId': 'ProvisionedTour-2026',
            'name': 'Provisioned Test Tour',
            'startDate': '2026-06-01',
            'endDate': '2026-06-10',
            'rideCount': 12,
            'provisioning': True,
        },
    )

    response = create_tour.lambda_handler(event, None)

    assert response['statusCode'] == 201
    body = json.loads(response['body'])
    assert body['success'] is True
    assert body['data']['status'] == TourStatus.PLANNING.value
    assert 'provisioning' not in body['data']
    assert 'provisionedAt' in body['data']

    table = dynamodb_mock.Table('test-tour-master-table')
    saved = table.get_item(Key={'tourId': 'ProvisionedTour-2026'})['Item']
    assert saved['status'] == TourStatus.PLANNING.value
    assert 'provisioning' not in saved

    dynamodb_client = boto3.client('dynamodb', region_name='us-east-1')
    expected_names = [
        f"test-stack-TourRider-ProvisionedTour-2026",
        f"test-stack-Ride-ProvisionedTour-2026",
        f"test-stack-CheckIn-ProvisionedTour-2026",
        f"test-stack-User-ProvisionedTour-2026",
        f"test-stack-Notification-ProvisionedTour-2026",
        f"test-stack-Artifacts-ProvisionedTour-2026",
    ]
    table_names = dynamodb_client.list_tables()['TableNames']
    for table_name in expected_names:
        assert table_name in table_names


def test_update_tour_updates_master_and_provisions_tables(dynamodb_mock):
    """PUT /v1/tours provisions a tour that does not have provisionedAt."""
    update_tour = _load_tours_handler('update_tour')
    table = dynamodb_mock.Table('test-tour-master-table')
    unprovisioned_tour = {**MOCK_TOURS[0]}
    unprovisioned_tour.pop('provisionedAt')
    table.put_item(Item=unprovisioned_tour)
    event = _make_auth_event(
        method='PUT',
        groups=['ADMINISTRATOR'],
        body={
            'tourId': MOCK_TOUR_ID,
            'name': 'Updated Test Tour',
            'startDate': '2026-02-12',
            'endDate': '2026-02-18',
            'status': 'planning',
            'provisioning': True,
            'selfQuitRidingAllowed': True,
        },
    )

    response = update_tour.lambda_handler(event, None)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['success'] is True
    assert body['data']['tour']['name'] == 'Updated Test Tour'
    assert body['data']['tour']['status'] == TourStatus.PLANNING.value
    assert body['data']['tour']['selfQuitRidingAllowed'] is True
    assert 'provisionedAt' in body['data']['tour']
    assert len(body['data']['provisionedTables']) == 11

    saved = table.get_item(Key={'tourId': MOCK_TOUR_ID})['Item']
    assert saved['name'] == 'Updated Test Tour'
    assert saved['startDate'] == '2026-02-12'
    assert saved['selfQuitRidingAllowed'] is True
    assert 'provisionedAt' in saved


def test_update_tour_default_provisioning_false_skips_provisioning(dynamodb_mock):
    """PUT /v1/tours without provisioning/provisionOnly only updates TourMaster."""
    update_tour = _load_tours_handler('update_tour')
    event = _make_auth_event(
        method='PUT',
        groups=['ADMINISTRATOR'],
        body={
            'tourId': MOCK_TOUR_ID,
            'name': 'Updated Test Tour',
        },
    )

    response = update_tour.lambda_handler(event, None)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['success'] is True
    assert body['data']['provisioning'] is False
    assert body['data']['provisionedTables'] == []

    table = dynamodb_mock.Table('test-tour-master-table')
    saved = table.get_item(Key={'tourId': MOCK_TOUR_ID})['Item']
    assert saved['name'] == 'Updated Test Tour'


def test_update_tour_rejects_repeated_provisioning(dynamodb_mock):
    """PUT /v1/tours rejects provisioning after provisionedAt is set."""
    update_tour = _load_tours_handler('update_tour')
    event = _make_auth_event(
        method='PUT',
        groups=['ADMINISTRATOR'],
        body={
            'tourId': MOCK_TOUR_ID,
            'provisioning': True,
        },
    )

    response = update_tour.lambda_handler(event, None)

    assert response['statusCode'] == 400
    body = json.loads(response['body'])
    assert 'already provisioned' in body['error']['message']


def test_update_tour_rejects_legacy_provision_only(dynamodb_mock):
    """PUT /v1/tours rejects the replaced provisionOnly request field."""
    update_tour = _load_tours_handler('update_tour')
    event = _make_auth_event(
        method='PUT',
        groups=['ADMINISTRATOR'],
        body={
            'tourId': MOCK_TOUR_ID,
            'provisionOnly': True,
        },
    )

    response = update_tour.lambda_handler(event, None)

    assert response['statusCode'] == 400


def test_provision_tour_reruns_without_changing_provisioned_at(dynamodb_mock):
    """Dedicated provisioning endpoint preserves the original TourMaster item."""
    provision_tour = _load_tours_handler('provision_tour')
    original_timestamp = MOCK_TOURS[0]['provisionedAt']
    event = _make_auth_event(
        method='PUT',
        groups=['ADMINISTRATOR'],
        path_params={'tourId': MOCK_TOUR_ID},
    )

    response = provision_tour.lambda_handler(event, None)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['success'] is True
    assert body['data']['tour']['name'] == MOCK_TOURS[0]['name']
    assert body['data']['tour']['provisionedAt'] == original_timestamp
    assert len(body['data']['provisionedTables']) == 11

    table = dynamodb_mock.Table('test-tour-master-table')
    saved = table.get_item(Key={'tourId': MOCK_TOUR_ID})['Item']
    assert saved == MOCK_TOURS[0]

    dynamodb_client = boto3.client('dynamodb', region_name='us-east-1')
    dynamodb_client.describe_table(TableName=f'test-stack-Artifacts-{MOCK_TOUR_ID}')


def test_provision_tour_rejects_unprovisioned_tour(dynamodb_mock):
    """Dedicated provisioning endpoint is only for re-provisioning."""
    provision_tour = _load_tours_handler('provision_tour')
    table = dynamodb_mock.Table('test-tour-master-table')
    unprovisioned_tour = {**MOCK_TOURS[0]}
    unprovisioned_tour.pop('provisionedAt')
    table.put_item(Item=unprovisioned_tour)
    event = _make_auth_event(
        method='PUT',
        groups=['ADMINISTRATOR'],
        path_params={'tourId': MOCK_TOUR_ID},
    )

    response = provision_tour.lambda_handler(event, None)

    assert response['statusCode'] == 400
    body = json.loads(response['body'])
    assert 'have not been provisioned' in body['error']['message']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
