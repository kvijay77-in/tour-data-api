"""
Unit tests for new rider-app API Lambda functions

Tests the new Lambda functions added for tour-rider-app integration:
- Create Rider Profile (POST /v1/riders/profile)
- List Rider Tour Participations (GET /v1/profile/{profileId}/tours)
- Get Rider Tour Participation (GET /v1/profile/{profileId}/tours/{tourId})
- Register Tour Rider (POST /v1/tours/{tourId}/riders)
- Get Rider Statistics (GET /v1/tours/{tourId}/riders/{riderId}/statistics)
- Upload Profile Picture (POST /v1/riders/profile/{profileId}/picture)
- List Notifications (GET /v1/tours/{tourId}/notifications)
- Create Notification (POST /v1/tours/{tourId}/notifications)
- Update Notification (PUT /v1/tours/{tourId}/notifications/{notificationId})
"""

import os
import json
import pytest
import boto3
from moto import mock_aws
from unittest.mock import patch, MagicMock
from decimal import Decimal

# Set up path for imports
import sys
sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/riders')
sys.path.insert(0, 'src/functions/notifications')

from tests.fixtures.mock_data import (
    MOCK_TOUR_ID, MOCK_TOURS, MOCK_RIDER_PROFILES,
    MOCK_TOUR_RIDERS, MOCK_RIDES, MOCK_CHECKINS
)
from models import TourStatus, TourRiderStatus, NotificationType


def _convert_floats(obj):
    """Recursively convert float values to Decimal for DynamoDB compatibility"""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: _convert_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_floats(i) for i in obj]
    return obj


@pytest.fixture
def aws_credentials():
    """Mock AWS credentials for moto"""
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture
def dynamodb_full_mock(aws_credentials):
    """Create mock DynamoDB tables with full test data for rider-app tests"""
    with mock_aws():
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
        for tour in MOCK_TOURS:
            tour_table.put_item(Item=tour)

        # Create shared RiderProfile table with EmailIndex and PersonalCodeIndex GSIs
        rider_table = dynamodb.create_table(
            TableName='test-rider-table',
            KeySchema=[
                {'AttributeName': 'profileId', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'profileId', 'AttributeType': 'S'},
                {'AttributeName': 'email', 'AttributeType': 'S'},
                {'AttributeName': 'personalCode', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'EmailIndex',
                    'KeySchema': [
                        {'AttributeName': 'email', 'KeyType': 'HASH'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 1,
                        'WriteCapacityUnits': 1
                    }
                },
                {
                    'IndexName': 'PersonalCodeIndex',
                    'KeySchema': [
                        {'AttributeName': 'personalCode', 'KeyType': 'HASH'}
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
        for profile in MOCK_RIDER_PROFILES:
            rider_table.put_item(Item=profile)

        # Create shared RiderCognitoUser table
        dynamodb.create_table(
            TableName='test-rider-cognito-user-table',
            KeySchema=[
                {'AttributeName': 'cognitoUserName', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'cognitoUserName', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )

        # Create shared RiderTours table
        rider_tours_table = dynamodb.create_table(
            TableName='test-rider-tours-table',
            KeySchema=[
                {'AttributeName': 'profileId', 'KeyType': 'HASH'},
                {'AttributeName': 'tourId', 'KeyType': 'RANGE'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'profileId', 'AttributeType': 'S'},
                {'AttributeName': 'tourId', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        rider_tours_table.put_item(
            Item={
                'profileId': 'P001',
                'tourId': MOCK_TOUR_ID,
                'appliedOn': '2025-12-30T13:51:05Z',
                'confirmedOn': '2026-03-22T13:51:05Z',
                'tourFeePaidOn': '2026-04-08T13:51:05Z',
                'registredOn': '',
                'riderId': '',
                'status': 'CONFIRMED',
                'updatedAt': '2026-04-08T13:51:05Z'
            }
        )

        # Create tour-specific TourRider table with ProfileIdIndex GSI
        tour_rider_table = dynamodb.create_table(
            TableName=f'test-stack-TourRider-{MOCK_TOUR_ID}',
            KeySchema=[
                {'AttributeName': 'riderId', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'riderId', 'AttributeType': 'S'},
                {'AttributeName': 'profileId', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'ProfileIdIndex',
                    'KeySchema': [
                        {'AttributeName': 'profileId', 'KeyType': 'HASH'}
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
        for rider in MOCK_TOUR_RIDERS:
            tour_rider_table.put_item(Item=rider)

        # Create tour-specific Ride table
        ride_table = dynamodb.create_table(
            TableName=f'test-stack-Ride-{MOCK_TOUR_ID}',
            KeySchema=[
                {'AttributeName': 'rideId', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'rideId', 'AttributeType': 'S'},
                {'AttributeName': 'date', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'DateIndex',
                    'KeySchema': [
                        {'AttributeName': 'date', 'KeyType': 'HASH'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 1,
                        'WriteCapacityUnits': 1
                    }
                },
                {
                    'IndexName': 'StatusIndex',
                    'KeySchema': [
                        {'AttributeName': 'status', 'KeyType': 'HASH'},
                        {'AttributeName': 'date', 'KeyType': 'RANGE'}
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
        for ride in MOCK_RIDES:
            ride_table.put_item(Item=_convert_floats(ride))

        # Create tour-specific CheckIn table
        checkin_table = dynamodb.create_table(
            TableName=f'test-stack-CheckIn-{MOCK_TOUR_ID}',
            KeySchema=[
                {'AttributeName': 'rideId', 'KeyType': 'HASH'},
                {'AttributeName': 'checkInId', 'KeyType': 'RANGE'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'rideId', 'AttributeType': 'S'},
                {'AttributeName': 'checkInId', 'AttributeType': 'S'},
                {'AttributeName': 'riderId', 'AttributeType': 'S'},
                {'AttributeName': 'timestamp', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'RiderIdIndex',
                    'KeySchema': [
                        {'AttributeName': 'riderId', 'KeyType': 'HASH'},
                        {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
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
        for checkin in MOCK_CHECKINS:
            checkin_table.put_item(Item=checkin)

        # Create tour-specific Notification table
        dynamodb.create_table(
            TableName=f'test-stack-Notification-{MOCK_TOUR_ID}',
            KeySchema=[
                {'AttributeName': 'notificationId', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'notificationId', 'AttributeType': 'S'},
                {'AttributeName': 'type', 'AttributeType': 'S'},
                {'AttributeName': 'createdAt', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'TypeCreatedAtIndex',
                    'KeySchema': [
                        {'AttributeName': 'type', 'KeyType': 'HASH'},
                        {'AttributeName': 'createdAt', 'KeyType': 'RANGE'}
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

        # Set environment variables
        os.environ['TOUR_MASTER_TABLE'] = 'test-tour-master-table'
        os.environ['RIDER_PROFILE_TABLE'] = 'test-rider-table'
        os.environ['RIDER_TOURS_TABLE'] = 'test-rider-tours-table'
        os.environ['RIDER_COGNITO_USER_TABLE'] = 'test-rider-cognito-user-table'
        os.environ['STACK_NAME'] = 'test-stack'
        os.environ['ENVIRONMENT'] = 'test'
        os.environ['SUBSCRIPTION_ID'] = 'test-sub-001'
        os.environ['PHOTOS_BUCKET'] = 'test-photos-bucket'
        os.environ['LOG_LEVEL'] = 'INFO'

        yield dynamodb


def _make_event(method='GET', path='/', path_params=None, body=None,
                query_params=None, groups=None):
    """Helper to create API Gateway HTTP API event"""
    event = {
        'version': '2.0',
        'routeKey': f'{method} {path}',
        'rawPath': path,
        'headers': {},
        'requestContext': {
            'http': {'method': method},
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': 'test-user-123',
                        'email': 'test@example.com',
                        'cognito:groups': ','.join(groups) if groups else ''
                    }
                }
            }
        }
    }
    if path_params:
        event['pathParameters'] = path_params
    if body:
        event['body'] = json.dumps(body)
    if query_params:
        event['queryStringParameters'] = query_params
    return event


# ============================================================================
# CREATE RIDER PROFILE TESTS
# ============================================================================

class TestCreateRiderProfile:
    """Tests for POST /v1/riders/profile"""

    def test_create_profile_success(self, dynamodb_full_mock):
        """Successfully create a new rider profile"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_rider_profile import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile',
            body={
                'name': 'New Rider',
                'email': 'newrider@example.com',
                'phone': '+9876543210',
                'emergencyContact': {
                    'name': 'Emergency Contact',
                    'phone': '+1234567890',
                    'relation': 'Friend'
                },
                'dateOfBirth': '1991-05-21',
                'gender': 'Female',
                'address': {
                    'line1': '1 New Street',
                    'city': 'Chennai',
                    'country': 'India',
                    'postalCode': '600100'
                }
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['name'] == 'New Rider'
        assert body['data']['email'] == 'newrider@example.com'
        assert 'profileId' in body['data']

    def test_create_profile_uses_profile_id_from_path(self, dynamodb_full_mock):
        """Use path profileId when provided instead of auto-generating UUID"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_rider_profile import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile/CUSTOM-PROFILE-001',
            path_params={'profileId': 'CUSTOM-PROFILE-001'},
            body={
                'name': 'Path Profile Rider',
                'email': 'pathprofile@example.com',
                'phone': '+9876500000',
                'emergencyContact': {
                    'name': 'Emergency Contact',
                    'phone': '+1234500000',
                    'relation': 'Friend'
                },
                'dateOfBirth': '1992-04-01',
                'gender': 'Male',
                'address': {
                    'line1': '12 North Avenue',
                    'city': 'Bengaluru',
                    'country': 'India',
                    'postalCode': '560001'
                }
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['profileId'] == 'CUSTOM-PROFILE-001'

    def test_create_profile_rejects_existing_path_profile_id(self, dynamodb_full_mock):
        """Reject create when provided path profileId already exists"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_rider_profile import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile/P001',
            path_params={'profileId': 'P001'},
            body={
                'name': 'Duplicate ProfileId Rider',
                'email': 'duplicate-profile-id@example.com',
                'phone': '+9876500001',
                'emergencyContact': {
                    'name': 'Emergency Contact',
                    'phone': '+1234500001',
                    'relation': 'Friend'
                },
                'dateOfBirth': '1992-04-02',
                'gender': 'Male',
                'address': {
                    'line1': '13 North Avenue',
                    'city': 'Bengaluru',
                    'country': 'India',
                    'postalCode': '560002'
                }
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 409
        body = json.loads(response['body'])
        assert body['error']['code'] == 'PROFILE_ALREADY_EXISTS'

    def test_create_profile_missing_fields(self, dynamodb_full_mock):
        """Fail with missing required fields"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_rider_profile import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile',
            body={'name': 'Incomplete'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 422

    def test_create_profile_normalizes_personal_code(self, dynamodb_full_mock):
        """Normalize personalCode to uppercase when creating profile"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_rider_profile import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile',
            body={
                'name': 'Code Rider',
                'email': 'coderider@example.com',
                'personalCode': ' d999 ',
                'phone': '+919999999999',
                'emergencyContact': {
                    'name': 'Emergency Contact',
                    'phone': '+911111111111',
                    'relation': 'Sibling'
                },
                'dateOfBirth': '1990-03-10',
                'gender': 'Other',
                'address': {
                    'line1': '44 Garden Street',
                    'city': 'Hyderabad',
                    'country': 'India',
                    'postalCode': '500001'
                }
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['data']['personalCode'] == 'D999'

    def test_create_profile_duplicate_personal_code(self, dynamodb_full_mock):
        """Reject duplicate personalCode using case-insensitive check"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_rider_profile import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile',
            body={
                'name': 'Duplicate Code Rider',
                'email': 'duplicatecode@example.com',
                'personalCode': 'd220',
                'phone': '+919888888888',
                'emergencyContact': {
                    'name': 'Emergency Contact',
                    'phone': '+911212121212',
                    'relation': 'Parent'
                },
                'dateOfBirth': '1989-12-11',
                'gender': 'Female',
                'address': {
                    'line1': '55 East Road',
                    'city': 'Pune',
                    'country': 'India',
                    'postalCode': '411001'
                }
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 409
        body = json.loads(response['body'])
        assert body['error']['code'] == 'PERSONAL_CODE_ALREADY_EXISTS'

    def test_create_profile_with_extended_attributes(self, dynamodb_full_mock):
        """Create profile with address/dateOfBirth/gender/emergencyContact fields"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_rider_profile import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile',
            body={
                'name': 'Extended Rider',
                'email': 'extended@example.com',
                'phone': '+919191919191',
                'emergencyContact': {
                    'name': 'Primary Contact',
                    'phone': '+918181818181',
                    'relation': 'Sibling'
                },
                'dateOfBirth': '1991-05-21',
                'gender': 'Female',
                'address': {
                    'line1': '221B Baker Street',
                    'line2': 'Floor 2',
                    'city': 'Chennai',
                    'state': 'Tamil Nadu',
                    'country': 'India',
                    'postalCode': '600002'
                }
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['data']['emergencyContact']['relation'] == 'Sibling'
        assert body['data']['dateOfBirth'] == '1991-05-21'
        assert body['data']['gender'] == 'Female'
        assert body['data']['address']['city'] == 'Chennai'

    def test_create_profile_rejects_invalid_gender(self, dynamodb_full_mock):
        """Reject unsupported gender values"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_rider_profile import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile',
            body={
                'name': 'Invalid Gender Rider',
                'email': 'invalidgender@example.com',
                'phone': '+919191919192',
                'emergencyContact': {
                    'name': 'Primary Contact',
                    'phone': '+918181818182',
                    'relation': 'Sibling'
                },
                'dateOfBirth': '1995-06-12',
                'gender': 'Unknown',
                'address': {
                    'line1': '98 Market Road',
                    'city': 'Madurai',
                    'country': 'India',
                    'postalCode': '625001'
                }
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 422

    def test_create_profile_rejects_invalid_address_shape(self, dynamodb_full_mock):
        """Reject address map that misses required keys"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_rider_profile import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile',
            body={
                'name': 'Invalid Address Rider',
                'email': 'invalidaddress@example.com',
                'phone': '+919191919193',
                'emergencyContact': {
                    'name': 'Primary Contact',
                    'phone': '+918181818183',
                    'relation': 'Cousin'
                },
                'dateOfBirth': '1994-08-20',
                'gender': 'Male',
                'address': {
                    'line1': '123 Main Street',
                    'city': 'Chennai'
                }
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 422

# ============================================================================
# GET/UPDATE RIDER PROFILE TESTS
# ============================================================================

class TestGetAndUpdateRiderProfile:
    """Tests for GET/PUT /v1/riders/profile/{profileId}"""

    def test_get_profile_returns_extended_attributes(self, dynamodb_full_mock):
        """Get profile returns all stored optional profile fields"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_profile import lambda_handler

        event = _make_event(
            method='GET',
            path='/v1/riders/profile/P001',
            path_params={'profileId': 'P001'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['data']['dateOfBirth'] == '1990-01-15'
        assert body['data']['gender'] == 'Male'
        assert body['data']['emergencyContact']['relation'] == 'Spouse'
        assert body['data']['address']['postalCode'] == '600001'

    def test_update_profile_with_extended_attributes(self, dynamodb_full_mock):
        """Update supports dateOfBirth/gender/address/emergencyContact"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from update_rider_profile import lambda_handler

        event = _make_event(
            method='PUT',
            path='/v1/riders/profile/P002',
            path_params={'profileId': 'P002'},
            body={
                'name': 'Jane Smith Updated',
                'email': 'jane.smith@example.com',
                'phone': '+1234567891',
                'dateOfBirth': '1993-09-10',
                'gender': 'Other',
                'emergencyContact': {
                    'name': 'Updated Contact',
                    'phone': '+917700112233',
                    'relation': 'Parent'
                },
                'address': {
                    'line1': '77 Lake View',
                    'line2': 'Near Park',
                    'city': 'Coimbatore',
                    'state': 'Tamil Nadu',
                    'country': 'India',
                    'postalCode': '641001'
                }
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['data']['dateOfBirth'] == '1993-09-10'
        assert body['data']['gender'] == 'Other'
        assert body['data']['emergencyContact']['relation'] == 'Parent'
        assert body['data']['address']['city'] == 'Coimbatore'

    def test_update_profile_rejects_invalid_date_of_birth(self, dynamodb_full_mock):
        """Update rejects invalid dateOfBirth format"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from update_rider_profile import lambda_handler

        event = _make_event(
            method='PUT',
            path='/v1/riders/profile/P001',
            path_params={'profileId': 'P001'},
            body={'dateOfBirth': '10-09-1993'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400


# ============================================================================
# LIST RIDER TOUR PARTICIPATIONS TESTS
# ============================================================================

class TestListRiderTourParticipations:
    """Tests for GET /v1/profile/{profileId}/tours"""

    def test_list_rider_tour_participations_success(self, dynamodb_full_mock):
        """Return all RiderTours rows for the given profileId"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Seed one additional tour for same profile and one for another profile.
        table = dynamodb_full_mock.Table('test-rider-tours-table')
        table.put_item(
            Item={
                'profileId': 'P001',
                'tourId': 'TOT-2027',
                'appliedOn': '2026-12-30T13:51:05Z',
                'confirmedOn': '2027-03-22T13:51:05Z',
                'tourFeePaidOn': '2027-04-08T13:51:05Z',
                'registredOn': '',
                'riderId': '',
                'status': 'CONFIRMED',
                'updatedAt': '2027-04-08T13:51:05Z'
            }
        )
        table.put_item(
            Item={
                'profileId': 'P002',
                'tourId': 'TOT-2028',
                'appliedOn': '2027-12-30T13:51:05Z',
                'confirmedOn': '',
                'tourFeePaidOn': '',
                'registredOn': '',
                'riderId': '',
                'status': 'APPLIED',
                'updatedAt': '2027-12-30T13:51:05Z'
            }
        )

        from get_rider_tours import lambda_handler

        event = _make_event(
            method='GET',
            path='/v1/profile/P001/tours',
            path_params={'profileId': 'P001'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['profileId'] == 'P001'
        assert body['data']['count'] == 2

        returned_tours = {item['tourId'] for item in body['data']['tours']}
        assert returned_tours == {MOCK_TOUR_ID, 'TOT-2027'}

    def test_list_rider_tour_participations_empty(self, dynamodb_full_mock):
        """Return 200 with empty list when profile has no RiderTours rows"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_tours import lambda_handler

        event = _make_event(
            method='GET',
            path='/v1/profile/P999/tours',
            path_params={'profileId': 'P999'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['profileId'] == 'P999'
        assert body['data']['count'] == 0
        assert body['data']['tours'] == []

    def test_list_rider_tour_participations_missing_profile_id(self, dynamodb_full_mock):
        """Return 400 when profileId is missing"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_tours import lambda_handler

        event = _make_event(
            method='GET',
            path='/v1/profile//tours',
            path_params={'profileId': ''}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400


# ============================================================================
# GET RIDER TOUR PARTICIPATION TESTS
# ============================================================================

class TestGetRiderTourParticipation:
    """Tests for GET /v1/profile/{profileId}/tours/{tourId}"""

    def test_get_rider_tour_success(self, dynamodb_full_mock):
        """Return rider tour participation for an existing profileId/tourId pair"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_tour import lambda_handler

        event = _make_event(
            method='GET',
            path=f'/v1/profile/P001/tours/{MOCK_TOUR_ID}',
            path_params={'profileId': 'P001', 'tourId': MOCK_TOUR_ID}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['profileId'] == 'P001'
        assert body['data']['tourId'] == MOCK_TOUR_ID
        assert body['data']['status'] == 'CONFIRMED'

    def test_get_rider_tour_not_found(self, dynamodb_full_mock):
        """Return 404 for a missing profileId/tourId pair"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_tour import lambda_handler

        event = _make_event(
            method='GET',
            path='/v1/profile/P001/tours/TOT-2099',
            path_params={'profileId': 'P001', 'tourId': 'TOT-2099'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404

    def test_get_rider_tour_invalid_tour_id(self, dynamodb_full_mock):
        """Return 400 for invalid tourId format"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_tour import lambda_handler

        event = _make_event(
            method='GET',
            path='/v1/profile/P001/tours/??',
            path_params={'profileId': 'P001', 'tourId': '??'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400

    def test_update_profile_requires_all_mandatory_fields(self, dynamodb_full_mock):
        """Update fails when mandatory profile fields are omitted"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from update_rider_profile import lambda_handler

        event = _make_event(
            method='PUT',
            path='/v1/riders/profile/P001',
            path_params={'profileId': 'P001'},
            body={
                'name': 'Partial Update',
                'email': 'john.doe@example.com'
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400


# ============================================================================
# LINK RIDER COGNITO USER TESTS
# ============================================================================

class TestLinkRiderCognitoUser:
    """Tests for GET/POST/DELETE /v1/riders/link/{cognitoUserName}"""

    def test_create_link_success(self, dynamodb_full_mock):
        """Successfully create a Cognito username link"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from link_rider_cognito_user import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/link/rider.user',
            path_params={'cognitoUserName': 'rider.user'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['cognitoUserName'] == 'rider.user'
        assert 'profileId' in body['data']

    def test_create_link_conflict(self, dynamodb_full_mock):
        """Fail when cognitoUserName already exists"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from link_rider_cognito_user import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/link/rider.user',
            path_params={'cognitoUserName': 'rider.user'}
        )

        first = lambda_handler(event, None)
        assert first['statusCode'] == 201

        second = lambda_handler(event, None)
        assert second['statusCode'] == 409
        body = json.loads(second['body'])
        assert body['error']['code'] == 'COGNITO_USER_ALREADY_LINKED'

    def test_get_link_success(self, dynamodb_full_mock):
        """Return the linked profileId for an existing Cognito username"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from link_rider_cognito_user import lambda_handler

        create_event = _make_event(
            method='POST',
            path='/v1/riders/link/rider.lookup',
            path_params={'cognitoUserName': 'rider.lookup'}
        )
        created = lambda_handler(create_event, None)
        assert created['statusCode'] == 201
        created_body = json.loads(created['body'])
        profile_id = created_body['data']['profileId']

        get_event = _make_event(
            method='GET',
            path='/v1/riders/link/rider.lookup',
            path_params={'cognitoUserName': 'rider.lookup'}
        )
        response = lambda_handler(get_event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['profileId'] == profile_id

    def test_get_link_not_found(self, dynamodb_full_mock):
        """Return 404 when the Cognito username is not linked"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from link_rider_cognito_user import lambda_handler

        event = _make_event(
            method='GET',
            path='/v1/riders/link/missing.user',
            path_params={'cognitoUserName': 'missing.user'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404

    def test_delete_link_success(self, dynamodb_full_mock):
        """Successfully delete an existing Cognito username link"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from link_rider_cognito_user import lambda_handler

        create_event = _make_event(
            method='POST',
            path='/v1/riders/link/rider.delete',
            path_params={'cognitoUserName': 'rider.delete'}
        )
        created = lambda_handler(create_event, None)
        assert created['statusCode'] == 201

        delete_event = _make_event(
            method='DELETE',
            path='/v1/riders/link/rider.delete',
            path_params={'cognitoUserName': 'rider.delete'}
        )
        deleted = lambda_handler(delete_event, None)
        assert deleted['statusCode'] == 200
        body = json.loads(deleted['body'])
        assert body['success'] is True
        assert body['data']['deleted'] is True

    def test_delete_link_not_found(self, dynamodb_full_mock):
        """Fail deleting when link is not present"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from link_rider_cognito_user import lambda_handler

        event = _make_event(
            method='DELETE',
            path='/v1/riders/link/nonexistent.user',
            path_params={'cognitoUserName': 'nonexistent.user'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404

    def test_link_missing_path_parameter(self, dynamodb_full_mock):
        """Fail when cognitoUserName path parameter is missing"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from link_rider_cognito_user import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/link/'
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400

    def test_create_profile_duplicate_email(self, dynamodb_full_mock):
        """Fail when email already exists"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_rider_profile import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile',
            body={
                'name': 'Duplicate Rider',
                'email': 'john.doe@example.com',  # Already exists in mock data
                'phone': '+9876543210',
                'emergencyContact': {
                    'name': 'Contact',
                    'phone': '+1234567890',
                    'relation': 'Friend'
                },
                'dateOfBirth': '1990-01-15',
                'gender': 'Male',
                'address': {
                    'line1': '10 Beach Road',
                    'city': 'Chennai',
                    'country': 'India',
                    'postalCode': '600001'
                }
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 409
        body = json.loads(response['body'])
        assert body['error']['code'] == 'EMAIL_ALREADY_EXISTS'

    def test_create_profile_invalid_email(self, dynamodb_full_mock):
        """Fail with invalid email format"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_rider_profile import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile',
            body={
                'name': 'Bad Email',
                'email': 'not-an-email',
                'phone': '+9876543210',
                'emergencyContact': {
                    'name': 'Contact',
                    'phone': '+1234567890',
                    'relation': 'Friend'
                },
                'dateOfBirth': '1991-10-10',
                'gender': 'Female',
                'address': {
                    'line1': '100 Elm Street',
                    'city': 'Madurai',
                    'country': 'India',
                    'postalCode': '625010'
                }
            }
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 422


# ============================================================================
# REGISTER TOUR RIDER TESTS
# ============================================================================

class TestRegisterTourRider:
    """Tests for POST /v1/tours/{tourId}/riders"""

    def test_register_success(self, dynamodb_full_mock):
        """Successfully register a rider for a tour"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from register_tour_rider import lambda_handler

        # Use a profile that's not already registered (create one)
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        rider_table = dynamodb.Table('test-rider-table')
        rider_table.put_item(Item={
            'profileId': 'P003',
            'name': 'New Rider',
            'email': 'newrider@example.com',
            'phone': '+111',
            'emergencyContact': {
                'name': 'Contact',
                'phone': '+222',
                'relation': 'Sibling'
            }
        })

        event = _make_event(
            method='POST',
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders',
            path_params={'tourId': MOCK_TOUR_ID},
            body={'profileId': 'P003'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['status'] == TourRiderStatus.PENDING.value
        assert body['data']['profileId'] == 'P003'

    def test_register_missing_profile_id(self, dynamodb_full_mock):
        """Fail with missing profileId"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from register_tour_rider import lambda_handler

        event = _make_event(
            method='POST',
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders',
            path_params={'tourId': MOCK_TOUR_ID},
            body={}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400

    def test_register_tour_not_found(self, dynamodb_full_mock):
        """Fail when tour does not exist"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from register_tour_rider import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/tours/NonExistentTour/riders',
            path_params={'tourId': 'NonExistentTour'},
            body={'profileId': 'P001'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404

    def test_register_already_registered(self, dynamodb_full_mock):
        """Fail when rider is already registered"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from register_tour_rider import lambda_handler

        # P001 is already registered in mock data
        event = _make_event(
            method='POST',
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders',
            path_params={'tourId': MOCK_TOUR_ID},
            body={'profileId': 'P001'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 409
        body = json.loads(response['body'])
        assert body['error']['code'] == 'ALREADY_REGISTERED'

    def test_register_profile_not_found(self, dynamodb_full_mock):
        """Fail when rider profile does not exist"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from register_tour_rider import lambda_handler

        event = _make_event(
            method='POST',
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders',
            path_params={'tourId': MOCK_TOUR_ID},
            body={'profileId': 'NONEXISTENT'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404


# ============================================================================
# GET TOUR RIDER NAMES TESTS
# ============================================================================

class TestGetTourRiderNames:
    """Tests for GET /v1/tours/{tourId}/riders/names"""

    def test_get_names_success(self, dynamodb_full_mock):
        """Successfully list riderId and name only"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_tour_rider_names import lambda_handler

        event = _make_event(
            method='GET',
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders/names',
            path_params={'tourId': MOCK_TOUR_ID},
            groups=['GUEST']
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200

        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['tourId'] == MOCK_TOUR_ID
        assert body['data']['count'] == 2

        riders = body['data']['riders']
        assert riders == [
            {'riderId': 'R1', 'name': 'John Doe', 'personalCode': 'D220'},
            {'riderId': 'R2', 'name': 'Jane Smith', 'personalCode': 'E221'}
        ]

    def test_get_names_forbidden_without_read_permission(self, dynamodb_full_mock):
        """Reject caller when READ permission is not granted by group mapping"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_tour_rider_names import lambda_handler

        event = _make_event(
            method='GET',
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders/names',
            path_params={'tourId': MOCK_TOUR_ID},
            groups=['NO_SUCH_GROUP']
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_get_names_invalid_tour_id(self, dynamodb_full_mock):
        """Fail for invalid tour ID format"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_tour_rider_names import lambda_handler

        event = _make_event(
            method='GET',
            path='/v1/tours/@/riders/names',
            path_params={'tourId': '@'},
            groups=['ADMINISTRATOR']
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400


# ============================================================================
# GET RIDER STATISTICS TESTS
# ============================================================================

class TestGetRiderStatistics:
    """Tests for GET /v1/tours/{tourId}/riders/{riderId}/statistics"""

    def test_get_statistics_success(self, dynamodb_full_mock):
        """Successfully get rider statistics"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_statistics import lambda_handler

        event = _make_event(
            method='GET',
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders/R1/statistics',
            path_params={'tourId': MOCK_TOUR_ID, 'riderId': 'R1'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['riderId'] == 'R1'
        assert body['data']['tourId'] == MOCK_TOUR_ID
        assert 'totalRides' in body['data']
        assert 'ridesCompleted' in body['data']
        assert 'currentStreak' in body['data']
        assert 'totalDistance' in body['data']
        assert 'totalCheckins' in body['data']

    def test_get_statistics_rider_not_found(self, dynamodb_full_mock):
        """Fail when rider is not in tour"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_statistics import lambda_handler

        event = _make_event(
            method='GET',
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders/R999/statistics',
            path_params={'tourId': MOCK_TOUR_ID, 'riderId': 'R999'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404

    def test_get_statistics_invalid_rider_id(self, dynamodb_full_mock):
        """Fail with invalid rider ID format"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_statistics import lambda_handler

        event = _make_event(
            method='GET',
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders/INVALID/statistics',
            path_params={'tourId': MOCK_TOUR_ID, 'riderId': 'INVALID'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400


# ============================================================================
# UPLOAD PROFILE PICTURE TESTS
# ============================================================================

class TestUploadProfilePicture:
    """Tests for POST /v1/riders/profile/{profileId}/picture"""

    @patch('upload_profile_picture.s3_client')
    def test_upload_picture_success(self, mock_s3, dynamodb_full_mock):
        """Successfully generate presigned upload URL"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        mock_s3.generate_presigned_url.return_value = 'https://s3.example.com/presigned-url'

        from upload_profile_picture import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile/P001/picture',
            path_params={'profileId': 'P001'},
            body={'contentType': 'image/jpeg'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert 'uploadUrl' in body['data']
        assert 'photoS3Key' in body['data']
        assert body['data']['profileId'] == 'P001'

    @patch('upload_profile_picture.s3_client')
    def test_upload_picture_profile_not_found(self, mock_s3, dynamodb_full_mock):
        """Fail when profile does not exist"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from upload_profile_picture import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile/NONEXISTENT/picture',
            path_params={'profileId': 'NONEXISTENT'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404

    @patch('upload_profile_picture.s3_client')
    def test_upload_picture_invalid_content_type(self, mock_s3, dynamodb_full_mock):
        """Fail with unsupported content type"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from upload_profile_picture import lambda_handler

        event = _make_event(
            method='POST',
            path='/v1/riders/profile/P001/picture',
            path_params={'profileId': 'P001'},
            body={'contentType': 'image/gif'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400


# ============================================================================
# LIST NOTIFICATIONS TESTS
# ============================================================================

class TestListNotifications:
    """Tests for GET /v1/tours/{tourId}/notifications"""

    def test_list_notifications_empty(self, dynamodb_full_mock):
        """List notifications returns empty when no notifications exist"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from list_notifications import lambda_handler

        event = _make_event(
            method='GET',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications',
            path_params={'tourId': MOCK_TOUR_ID}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['count'] == 0

    def test_list_notifications_with_data(self, dynamodb_full_mock):
        """List notifications returns notifications after creating them"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Insert a notification directly
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        notif_table = dynamodb.Table(f'test-stack-Notification-{MOCK_TOUR_ID}')
        notif_table.put_item(Item={
            'notificationId': 'notif-001',
            'type': 'TOUR_ANNOUNCEMENT',
            'title': 'Test Notification',
            'message': 'Test message',
            'createdBy': 'admin',
            'readBy': [],
            'createdAt': '2026-02-11T10:00:00Z'
        })

        from list_notifications import lambda_handler

        event = _make_event(
            method='GET',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications',
            path_params={'tourId': MOCK_TOUR_ID}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['data']['count'] == 1
        assert body['data']['notifications'][0]['title'] == 'Test Notification'

    def test_list_notifications_filter_by_type(self, dynamodb_full_mock):
        """List notifications filtered by type"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Insert notifications of different types
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        notif_table = dynamodb.Table(f'test-stack-Notification-{MOCK_TOUR_ID}')
        notif_table.put_item(Item={
            'notificationId': 'notif-001',
            'type': 'TOUR_ANNOUNCEMENT',
            'title': 'Announcement',
            'message': 'Tour announcement',
            'createdBy': 'admin',
            'readBy': [],
            'createdAt': '2026-02-11T10:00:00Z'
        })
        notif_table.put_item(Item={
            'notificationId': 'notif-002',
            'type': 'SAFETY_ALERT',
            'title': 'Safety Alert',
            'message': 'Weather warning',
            'createdBy': 'admin',
            'readBy': [],
            'createdAt': '2026-02-11T11:00:00Z'
        })

        from list_notifications import lambda_handler

        event = _make_event(
            method='GET',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications',
            path_params={'tourId': MOCK_TOUR_ID},
            query_params={'type': 'SAFETY_ALERT'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['data']['count'] == 1
        assert body['data']['notifications'][0]['type'] == 'SAFETY_ALERT'

    def test_list_notifications_invalid_type(self, dynamodb_full_mock):
        """Fail with invalid notification type filter"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from list_notifications import lambda_handler

        event = _make_event(
            method='GET',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications',
            path_params={'tourId': MOCK_TOUR_ID},
            query_params={'type': 'INVALID_TYPE'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400


# ============================================================================
# CREATE NOTIFICATION TESTS
# ============================================================================

class TestCreateNotification:
    """Tests for POST /v1/tours/{tourId}/notifications"""

    def test_create_notification_success(self, dynamodb_full_mock):
        """Successfully create a notification"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_notification import lambda_handler

        event = _make_event(
            method='POST',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications',
            path_params={'tourId': MOCK_TOUR_ID},
            body={
                'type': 'TOUR_ANNOUNCEMENT',
                'title': 'Tour Update',
                'message': 'Important tour update for all riders'
            },
            groups=['ADMINISTRATOR']
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['type'] == 'TOUR_ANNOUNCEMENT'
        assert body['data']['title'] == 'Tour Update'
        assert 'notificationId' in body['data']

    def test_create_notification_forbidden(self, dynamodb_full_mock):
        """Fail when user lacks NOTIFICATION_MANAGE permission"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_notification import lambda_handler

        event = _make_event(
            method='POST',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications',
            path_params={'tourId': MOCK_TOUR_ID},
            body={
                'type': 'TOUR_ANNOUNCEMENT',
                'title': 'Tour Update',
                'message': 'Message'
            },
            groups=['GUEST']  # GUEST does not have NOTIFICATION_MANAGE
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_create_notification_missing_fields(self, dynamodb_full_mock):
        """Fail with missing required fields"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_notification import lambda_handler

        event = _make_event(
            method='POST',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications',
            path_params={'tourId': MOCK_TOUR_ID},
            body={'type': 'TOUR_ANNOUNCEMENT'},
            groups=['ADMINISTRATOR']
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400

    def test_create_notification_invalid_type(self, dynamodb_full_mock):
        """Fail with invalid notification type"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_notification import lambda_handler

        event = _make_event(
            method='POST',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications',
            path_params={'tourId': MOCK_TOUR_ID},
            body={
                'type': 'INVALID_TYPE',
                'title': 'Test',
                'message': 'Test'
            },
            groups=['ADMINISTRATOR']
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400


# ============================================================================
# UPDATE NOTIFICATION TESTS
# ============================================================================

class TestUpdateNotification:
    """Tests for PUT /v1/tours/{tourId}/notifications/{notificationId}"""

    def test_mark_as_read_success(self, dynamodb_full_mock):
        """Successfully mark a notification as read"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Insert a notification
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        notif_table = dynamodb.Table(f'test-stack-Notification-{MOCK_TOUR_ID}')
        notif_table.put_item(Item={
            'notificationId': 'notif-001',
            'type': 'TOUR_ANNOUNCEMENT',
            'title': 'Test',
            'message': 'Test',
            'createdBy': 'admin',
            'readBy': [],
            'createdAt': '2026-02-11T10:00:00Z'
        })

        from update_notification import lambda_handler

        event = _make_event(
            method='PUT',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications/notif-001',
            path_params={'tourId': MOCK_TOUR_ID, 'notificationId': 'notif-001'},
            body={'profileId': 'P001'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert 'P001' in body['data']['readBy']

    def test_mark_as_read_not_found(self, dynamodb_full_mock):
        """Fail when notification does not exist"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from update_notification import lambda_handler

        event = _make_event(
            method='PUT',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications/nonexistent',
            path_params={'tourId': MOCK_TOUR_ID, 'notificationId': 'nonexistent'},
            body={'profileId': 'P001'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404

    def test_mark_as_read_missing_profile_id(self, dynamodb_full_mock):
        """Fail with missing profileId"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from update_notification import lambda_handler

        event = _make_event(
            method='PUT',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications/notif-001',
            path_params={'tourId': MOCK_TOUR_ID, 'notificationId': 'notif-001'},
            body={}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400

    def test_mark_as_read_idempotent(self, dynamodb_full_mock):
        """Marking as read twice doesn't duplicate profileId"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Insert a notification already read by P001
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        notif_table = dynamodb.Table(f'test-stack-Notification-{MOCK_TOUR_ID}')
        notif_table.put_item(Item={
            'notificationId': 'notif-002',
            'type': 'TOUR_ANNOUNCEMENT',
            'title': 'Test',
            'message': 'Test',
            'createdBy': 'admin',
            'readBy': ['P001'],
            'createdAt': '2026-02-11T10:00:00Z'
        })

        from update_notification import lambda_handler

        event = _make_event(
            method='PUT',
            path=f'/v1/tours/{MOCK_TOUR_ID}/notifications/notif-002',
            path_params={'tourId': MOCK_TOUR_ID, 'notificationId': 'notif-002'},
            body={'profileId': 'P001'}
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        # Should only have P001 once
        assert body['data']['readBy'].count('P001') == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
