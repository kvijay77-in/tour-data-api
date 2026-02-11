"""
Unit tests for Lambda functions using moto for AWS mocking

This module demonstrates proper testing of Lambda functions without
modifying production code. Uses moto to mock AWS DynamoDB services.
"""

import os
import json
import pytest
import boto3
from moto import mock_aws
from decimal import Decimal

# Set up path for imports
import sys
sys.path.insert(0, 'src/layers/common/python')
sys.path.insert(0, 'src/functions/tours')

from tests.fixtures.mock_data import MOCK_TOURS, MOCK_RIDERS
from models import TourStatus, RideStatus


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
        
        # Create Tour table
        tour_table = dynamodb.create_table(
            TableName='test-tour-table',
            KeySchema=[
                {'AttributeName': 'PK', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'PK', 'AttributeType': 'S'},
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
        
        # Set environment variables for Lambda
        os.environ['TOUR_TABLE'] = 'test-tour-table'
        os.environ['RIDER_PROFILE_TABLE'] = 'test-rider-table'
        os.environ['TOUR_RIDER_TABLE'] = 'test-tour-rider-table'
        os.environ['RIDE_TABLE'] = 'test-ride-table'
        os.environ['CHECKIN_TABLE'] = 'test-checkin-table'
        os.environ['USER_TABLE'] = 'test-user-table'
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
    assert body['data']['tourId'] == 'TOUR#001'
    assert body['data']['status'] == TourStatus.ACTIVE.value


def test_get_active_tour_not_found(dynamodb_mock):
    """Test getting active tour - no active tour"""
    from get_active import lambda_handler
    
    # Clear the mock tour (make it inactive)
    table = dynamodb_mock.Table('test-tour-table')
    table.delete_item(Key={'PK': 'TOUR#001'})
    
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


def test_dynamodb_utils_with_mocking(dynamodb_mock):
    """Test DynamoDB utilities with moto mocking"""
    # Import dynamodb_utils - it will use our mocked boto3 resource
    import dynamodb_utils
    
    # Clear cache to use new mock
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    
    # Test get_item
    item = dynamodb_utils.get_item('TOUR_TABLE', {'PK': 'TOUR#001'})
    assert item is not None
    assert item['tourId'] == 'TOUR#001'
    
    # Test put_item
    new_tour = {
        'PK': 'TOUR#002',
        'tourId': 'TOUR#002',
        'tourName': 'New Test Tour',
        'status': TourStatus.PLANNING.value
    }
    dynamodb_utils.put_item('TOUR_TABLE', new_tour)
    
    # Verify it was added
    retrieved = dynamodb_utils.get_item('TOUR_TABLE', {'PK': 'TOUR#002'})
    assert retrieved['tourName'] == 'New Test Tour'
    
    # Test scan_items
    items = dynamodb_utils.scan_items(
        'TOUR_TABLE',
        filter_expression='#status = :status',
        expression_values={':status': TourStatus.ACTIVE.value},
        expression_names={'#status': 'status'}
    )
    assert len(items) == 1
    assert items[0]['tourId'] == 'TOUR#001'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
