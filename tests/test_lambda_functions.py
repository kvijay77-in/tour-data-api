"""
Unit tests for Lambda functions using moto for AWS mocking

Tests the Lambda functions with the hybrid table strategy:
- Shared tables (TourMaster, RiderProfile) resolved via env var
- Tour-specific tables resolved via STACK_NAME + tourId
"""

import os
import json
import pytest
import boto3
from moto import mock_aws

# Set up path for imports
import sys
sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/tours')

from tests.fixtures.mock_data import MOCK_TOURS, MOCK_TOUR_ID
from models import TourStatus


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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
