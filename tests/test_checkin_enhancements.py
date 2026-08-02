"""
Unit tests for check-in enhancements:
- Timestamp-based Quit Riding validation (offline sync support)
- Late-sync for closed rides
- Duplicate check-in detection with specific error codes
- ETag support for dashboard endpoint

Tests use moto for DynamoDB mocking with the hybrid table strategy.
"""

import os
import json
import hashlib
import copy
import pytest
import boto3
from moto import mock_aws
from datetime import datetime
from decimal import Decimal

# Set up path for imports
import sys
sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/checkins')
sys.path.insert(0, 'src/functions/riders')

from tests.fixtures.mock_data import (
    MOCK_TOUR_ID, MOCK_TOURS, MOCK_TOUR_RIDERS, MOCK_RIDES,
    MOCK_RIDER_PROFILES, MOCK_CHECKINS
)
from models import RideStatus, CheckInMethod


def _convert_floats(obj):
    """Recursively convert float values to Decimal for DynamoDB compatibility"""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: _convert_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_floats(i) for i in obj]
    return obj


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(scope='function')
def checkin_dynamodb(aws_credentials):
    """Create mock DynamoDB tables with tour-specific data for check-in tests"""
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        stack_name = 'test-stack'

        # Shared TourMaster table
        tour_table = dynamodb.create_table(
            TableName='test-tour-master-table',
            KeySchema=[
                {'AttributeName': 'tourId', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'tourId', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[{
                'IndexName': 'StatusIndex',
                'KeySchema': [{'AttributeName': 'status', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'},
                'ProvisionedThroughput': {
                    'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1
                }
            }],
            BillingMode='PAY_PER_REQUEST'
        )
        for tour in MOCK_TOURS:
            tour_table.put_item(Item=tour)

        # Shared RiderProfile table
        profile_table = dynamodb.create_table(
            TableName='test-rider-table',
            KeySchema=[
                {'AttributeName': 'profileId', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'profileId', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        for profile in MOCK_RIDER_PROFILES:
            profile_table.put_item(Item=profile)

        # Tour-specific TourRider table
        rider_table = dynamodb.create_table(
            TableName=f'{stack_name}-TourRider-{MOCK_TOUR_ID}',
            KeySchema=[
                {'AttributeName': 'riderId', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'riderId', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        for rider in MOCK_TOUR_RIDERS:
            rider_table.put_item(Item=rider)

        # Tour-specific Ride table
        ride_table = dynamodb.create_table(
            TableName=f'{stack_name}-Ride-{MOCK_TOUR_ID}',
            KeySchema=[
                {'AttributeName': 'rideId', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'rideId', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        for ride in MOCK_RIDES:
            ride_table.put_item(Item=_convert_floats(ride))

        # Tour-specific CheckIn table (composite key: rideId + checkInId)
        checkin_table = dynamodb.create_table(
            TableName=f'{stack_name}-CheckIn-{MOCK_TOUR_ID}',
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
            GlobalSecondaryIndexes=[{
                'IndexName': 'RiderIdIndex',
                'KeySchema': [
                    {'AttributeName': 'riderId', 'KeyType': 'HASH'},
                    {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
                ],
                'Projection': {'ProjectionType': 'ALL'}
            }],
            BillingMode='PAY_PER_REQUEST'
        )
        for checkin in MOCK_CHECKINS:
            checkin_table.put_item(Item=checkin)

        # Set environment variables
        os.environ['TOUR_MASTER_TABLE'] = 'test-tour-master-table'
        os.environ['RIDER_PROFILE_TABLE'] = 'test-rider-table'
        os.environ['STACK_NAME'] = stack_name
        os.environ['ENVIRONMENT'] = 'test'
        os.environ['SUBSCRIPTION_ID'] = 'test-sub-001'
        os.environ['PHOTOS_BUCKET'] = 'test-photos-bucket'
        os.environ['LOG_LEVEL'] = 'INFO'

        yield dynamodb


def _make_checkin_event(tour_id, body):
    """Helper to create a check-in API Gateway event"""
    return {
        'version': '2.0',
        'routeKey': f'POST /v1/tours/{tour_id}/checkins',
        'rawPath': f'/v1/tours/{tour_id}/checkins',
        'pathParameters': {'tourId': tour_id},
        'headers': {'content-type': 'application/json'},
        'requestContext': {
            'http': {'method': 'POST'},
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': 'test-user-001',
                        'cognito:groups': 'ADMINISTRATOR'
                    }
                }
            }
        },
        'body': json.dumps(body)
    }


def _make_dashboard_event(tour_id, ride_id, headers=None):
    """Helper to create a dashboard GET API Gateway event"""
    event = {
        'version': '2.0',
        'routeKey': f'GET /v1/tours/{tour_id}/rides/{ride_id}/dashboard',
        'rawPath': f'/v1/tours/{tour_id}/rides/{ride_id}/dashboard',
        'pathParameters': {'tourId': tour_id, 'rideId': ride_id},
        'headers': headers or {},
        'requestContext': {
            'http': {'method': 'GET'},
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': 'test-user-001',
                        'cognito:groups': 'ADMINISTRATOR'
                    }
                }
            }
        }
    }
    return event


def _make_dashboard_progress_event(tour_id, ride_id, headers=None):
    """Helper to create dashboard progress GET API Gateway event."""
    event = {
        'version': '2.0',
        'routeKey': f'GET /v1/tours/{tour_id}/rides/{ride_id}/dashboard/progress',
        'rawPath': f'/v1/tours/{tour_id}/rides/{ride_id}/dashboard/progress',
        'pathParameters': {'tourId': tour_id, 'rideId': ride_id},
        'headers': headers or {},
        'requestContext': {
            'http': {'method': 'GET'},
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': 'test-user-001',
                        'cognito:groups': 'ADMINISTRATOR'
                    }
                }
            }
        }
    }
    return event


def _make_rider_details_event(tour_id, ride_id, rider_id, headers=None):
    """Helper to create rider details GET API Gateway event."""
    event = {
        'version': '2.0',
        'routeKey': (
            f'GET /v1/tours/{tour_id}/rides/{ride_id}/riders/{rider_id}/details'
        ),
        'rawPath': f'/v1/tours/{tour_id}/rides/{ride_id}/riders/{rider_id}/details',
        'pathParameters': {
            'tourId': tour_id,
            'rideId': ride_id,
            'riderId': rider_id,
        },
        'headers': headers or {},
        'requestContext': {
            'http': {'method': 'GET'},
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': 'test-user-001',
                        'cognito:groups': 'ADMINISTRATOR'
                    }
                }
            }
        }
    }
    return event


def _make_get_rider_checkins_event(tour_id, rider_id):
    """Helper to create a rider check-ins GET API Gateway event."""
    return {
        'version': '2.0',
        'routeKey': f'GET /v1/tours/{tour_id}/riders/{rider_id}/checkins',
        'rawPath': f'/v1/tours/{tour_id}/riders/{rider_id}/checkins',
        'pathParameters': {'tourId': tour_id, 'riderId': rider_id},
        'requestContext': {
            'http': {'method': 'GET'},
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': 'test-user-001',
                        'cognito:groups': 'ADMINISTRATOR'
                    }
                }
            }
        }
    }


def _make_get_rider_ride_checkins_event(tour_id, rider_id, ride_no):
    """Helper to create a rider + rideNo check-ins GET API Gateway event."""
    return {
        'version': '2.0',
        'routeKey': f'GET /v1/tours/{tour_id}/riders/{rider_id}/rides/{ride_no}/checkins',
        'rawPath': f'/v1/tours/{tour_id}/riders/{rider_id}/rides/{ride_no}/checkins',
        'pathParameters': {
            'tourId': tour_id,
            'riderId': rider_id,
            'rideNo': str(ride_no)
        },
        'requestContext': {
            'http': {'method': 'GET'},
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': 'test-user-001',
                        'cognito:groups': 'ADMINISTRATOR'
                    }
                }
            }
        }
    }


def _make_cancel_checkin_event(tour_id, ride_id, checkin_id, body):
    """Helper to create a cancel check-in POST API Gateway event."""
    return {
        'version': '2.0',
        'routeKey': (
            f'POST /v1/tours/{tour_id}/rides/{ride_id}/checkins/{checkin_id}/cancel'
        ),
        'rawPath': f'/v1/tours/{tour_id}/rides/{ride_id}/checkins/{checkin_id}/cancel',
        'pathParameters': {
            'tourId': tour_id,
            'rideId': ride_id,
            'checkInId': checkin_id,
        },
        'headers': {'content-type': 'application/json'},
        'requestContext': {
            'http': {'method': 'POST'},
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': 'test-user-001',
                        'cognito:groups': 'ADMINISTRATOR'
                    }
                }
            }
        },
        'body': json.dumps(body)
    }


# ============================================================================
# TEST: Timestamp-Based Quit Riding Validation
# ============================================================================

class TestTimestampBasedQuitRidingValidation:
    """Tests for offline sync scenario: check-in captured before rider quit"""

    def test_reject_checkin_after_quit_no_timestamp(self, checkin_dynamodb):
        """Check-in after quit with no client timestamp should be rejected"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # First: add a quit-riding record for R1
        stack_name = os.environ['STACK_NAME']
        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        checkin_table.put_item(Item={
            'rideId': 'RIDE001',
            'checkInId': 'R1#001#2026-02-11T12:00:00Z',
            'riderId': 'R1',
            'stageNumber': 1,
            'stageId': 'S001',
            'timestamp': '2026-02-11T12:00:00Z',
            'checkedInBy': 'system',
            'method': 'MANUAL',
            'isNotRiding': False,
            'isQuitRiding': True,
            'isManualEntry': True,
            'status': 'QUIT_RIDING',
            'createdAt': '2026-02-11T12:00:00Z'
        })

        from create_checkin import lambda_handler

        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R1',
            'rideId': 'RIDE001',
            'stageNumber': 1,
            'method': 'QR_SCAN'
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 409
        body = json.loads(response['body'])
        assert body['error']['code'] == 'RIDER_QUIT_RIDING'

    def test_accept_checkin_before_quit_with_timestamp(self, checkin_dynamodb):
        """Check-in captured before quit (offline sync) should be accepted"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Add quit-riding record at PS2 (timestamp 12:00)
        stack_name = os.environ['STACK_NAME']
        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        checkin_table.put_item(Item={
            'rideId': 'RIDE001',
            'checkInId': 'R1#001#2026-02-11T12:00:00Z',
            'riderId': 'R1',
            'stageNumber': 1,
            'stageId': 'S001',
            'timestamp': '2026-02-11T12:00:00Z',
            'checkedInBy': 'system',
            'method': 'MANUAL',
            'isNotRiding': False,
            'isQuitRiding': True,
            'isManualEntry': True,
            'status': 'QUIT_RIDING',
            'createdAt': '2026-02-11T12:00:00Z'
        })

        from create_checkin import lambda_handler

        # Offline check-in captured at 11:00 (before quit at 12:00)
        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R1',
            'rideId': 'RIDE001',
            'stageNumber': 1,
            'method': 'QR_SCAN',
            'timestamp': '2026-02-11T11:00:00Z'
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['riderId'] == 'R1'

    def test_reject_checkin_after_quit_with_timestamp(self, checkin_dynamodb):
        """Check-in with timestamp after quit should still be rejected"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Add quit-riding record at 12:00
        stack_name = os.environ['STACK_NAME']
        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        checkin_table.put_item(Item={
            'rideId': 'RIDE001',
            'checkInId': 'R1#001#2026-02-11T12:00:00Z',
            'riderId': 'R1',
            'stageNumber': 1,
            'stageId': 'S001',
            'timestamp': '2026-02-11T12:00:00Z',
            'checkedInBy': 'system',
            'method': 'MANUAL',
            'isNotRiding': False,
            'isQuitRiding': True,
            'isManualEntry': True,
            'status': 'QUIT_RIDING',
            'createdAt': '2026-02-11T12:00:00Z'
        })

        from create_checkin import lambda_handler

        # Timestamp at 13:00 — after quit at 12:00
        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R1',
            'rideId': 'RIDE001',
            'stageNumber': 2,
            'method': 'QR_SCAN',
            'timestamp': '2026-02-11T13:00:00Z'
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 409
        body = json.loads(response['body'])
        assert body['error']['code'] == 'RIDER_QUIT_RIDING'


# ============================================================================
# TEST: Not Riding Validation (unchanged — should still reject)
# ============================================================================

class TestNotRidingValidation:
    """Tests confirming Not Riding validation remains unchanged"""

    def test_reject_checkin_when_not_riding(self, checkin_dynamodb):
        """Normal check-in should be rejected if rider is marked Not Riding"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Mark R2 as Not Riding
        stack_name = os.environ['STACK_NAME']
        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        checkin_table.put_item(Item={
            'rideId': 'RIDE001',
            'checkInId': 'R2#000#2026-02-11T07:00:00Z',
            'riderId': 'R2',
            'stageNumber': 0,
            'stageId': 'S000',
            'timestamp': '2026-02-11T07:00:00Z',
            'checkedInBy': 'admin',
            'method': 'QR_SCAN',
            'isNotRiding': True,
            'isQuitRiding': False,
            'isManualEntry': False,
            'status': 'NOT_RIDING',
            'createdAt': '2026-02-11T07:00:00Z'
        })

        from create_checkin import lambda_handler

        # Even with a timestamp before NR, it should be rejected
        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'stageNumber': 0,
            'method': 'QR_SCAN',
            'timestamp': '2026-02-11T06:00:00Z'
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 409
        body = json.loads(response['body'])
        assert body['error']['code'] == 'RIDER_NOT_RIDING'

    def test_reject_duplicate_not_riding(self, checkin_dynamodb):
        """Duplicate Not Riding should be rejected with specific error code"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Mark R2 as Not Riding
        stack_name = os.environ['STACK_NAME']
        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        checkin_table.put_item(Item={
            'rideId': 'RIDE001',
            'checkInId': 'R2#000#2026-02-11T07:00:00Z',
            'riderId': 'R2',
            'stageNumber': 0,
            'stageId': 'S000',
            'timestamp': '2026-02-11T07:00:00Z',
            'checkedInBy': 'admin',
            'method': 'QR_SCAN',
            'isNotRiding': True,
            'isQuitRiding': False,
            'isManualEntry': False,
            'status': 'NOT_RIDING',
            'createdAt': '2026-02-11T07:00:00Z'
        })

        from create_checkin import lambda_handler

        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'stageNumber': 0,
            'method': 'QR_SCAN',
            'isNotRiding': True
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 409
        body = json.loads(response['body'])
        assert body['error']['code'] == 'DUPLICATE_NOT_RIDING'


class TestStageOptionalForStatusCheckins:
    """Tests for conditional stage requirement based on check-in status flags"""

    def test_create_not_riding_without_stage(self, checkin_dynamodb):
        """Not Riding check-in should be accepted without stageNumber"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_checkin import lambda_handler

        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'method': 'QR_SCAN',
            'isNotRiding': True
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['isNotRiding'] is True
        assert body['data'].get('stageNumber') is None

    def test_create_quit_riding_without_stage(self, checkin_dynamodb):
        """Quit Riding check-in should be accepted without stageNumber"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_checkin import lambda_handler

        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'method': 'QR_SCAN',
            'isQuitRiding': True
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['isQuitRiding'] is True
        assert body['data'].get('stageNumber') is None


# ============================================================================
# TEST: Late-Sync for Closed Rides
# ============================================================================

class TestLateSyncClosedRides:
    """Tests for offline check-ins synced after ride closure"""

    def test_reject_checkin_closed_ride_no_timestamp(self, checkin_dynamodb):
        """Check-in on closed ride without client timestamp should be rejected"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Close the ride
        stack_name = os.environ['STACK_NAME']
        ride_table = checkin_dynamodb.Table(f'{stack_name}-Ride-{MOCK_TOUR_ID}')
        ride_table.update_item(
            Key={'rideId': 'RIDE001'},
            UpdateExpression='SET #s = :status, closedAt = :closed',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':status': RideStatus.CLOSED.value,
                ':closed': '2026-02-11T18:00:00Z'
            }
        )

        from create_checkin import lambda_handler

        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'stageNumber': 0,
            'method': 'QR_SCAN'
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 409
        body = json.loads(response['body'])
        assert body['error']['code'] == 'RIDE_CLOSED'

    def test_accept_late_sync_before_closure(self, checkin_dynamodb):
        """Offline check-in captured before ride closure should be accepted"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Close the ride at 18:00
        stack_name = os.environ['STACK_NAME']
        ride_table = checkin_dynamodb.Table(f'{stack_name}-Ride-{MOCK_TOUR_ID}')
        ride_table.update_item(
            Key={'rideId': 'RIDE001'},
            UpdateExpression='SET #s = :status, closedAt = :closed',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':status': RideStatus.CLOSED.value,
                ':closed': '2026-02-11T18:00:00Z'
            }
        )

        from create_checkin import lambda_handler

        # Check-in captured at 14:00 (before closure at 18:00)
        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'stageNumber': 0,
            'method': 'QR_SCAN',
            'timestamp': '2026-02-11T14:00:00Z'
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['success'] is True

    def test_reject_late_sync_after_closure(self, checkin_dynamodb):
        """Check-in with timestamp after ride closure should be rejected"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Close the ride at 18:00
        stack_name = os.environ['STACK_NAME']
        ride_table = checkin_dynamodb.Table(f'{stack_name}-Ride-{MOCK_TOUR_ID}')
        ride_table.update_item(
            Key={'rideId': 'RIDE001'},
            UpdateExpression='SET #s = :status, closedAt = :closed',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':status': RideStatus.CLOSED.value,
                ':closed': '2026-02-11T18:00:00Z'
            }
        )

        from create_checkin import lambda_handler

        # Timestamp at 19:00 — after closure
        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'stageNumber': 0,
            'method': 'QR_SCAN',
            'timestamp': '2026-02-11T19:00:00Z'
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 409
        body = json.loads(response['body'])
        assert body['error']['code'] == 'RIDE_CLOSED'


# ============================================================================
# TEST: Duplicate Check-In Detection
# ============================================================================

class TestDuplicateCheckInDetection:
    """Tests for duplicate check-in (same rider + same stage) handling"""

    def test_reject_duplicate_normal_checkin(self, checkin_dynamodb):
        """Duplicate normal check-in at same stage should return DUPLICATE_CHECKIN"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # R1 already has a check-in at stage 0 (from MOCK_CHECKINS)
        from create_checkin import lambda_handler

        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R1',
            'rideId': 'RIDE001',
            'stageNumber': 0,
            'method': 'QR_SCAN'
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 409
        body = json.loads(response['body'])
        assert body['error']['code'] == 'DUPLICATE_CHECKIN'
        assert 'already checked in at stage 0' in body['error']['message']

    def test_allow_checkin_at_different_stage(self, checkin_dynamodb):
        """Check-in at a different stage should succeed"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # R1 has check-in at stage 0; stage 1 should be fine
        from create_checkin import lambda_handler

        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R1',
            'rideId': 'RIDE001',
            'stageNumber': 1,
            'method': 'QR_SCAN'
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201

    def test_allow_quit_riding_despite_existing_checkin(self, checkin_dynamodb):
        """Quit Riding at a stage with existing check-in should be allowed"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # R1 has check-in at stage 0; QR at same stage should be allowed
        from create_checkin import lambda_handler

        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R1',
            'rideId': 'RIDE001',
            'stageNumber': 0,
            'method': 'QR_SCAN',
            'isQuitRiding': True
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201


# ============================================================================
# TEST: ETag Support for Dashboard
# ============================================================================

class TestDashboardETag:
    """Tests for ETag / conditional request support on dashboard endpoint"""

    def test_dashboard_returns_etag_header(self, checkin_dynamodb):
        """Dashboard response should include ETag header"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_dashboard_data import lambda_handler

        event = _make_dashboard_event(MOCK_TOUR_ID, 'RIDE001')
        response = lambda_handler(event, None)

        assert response['statusCode'] == 200
        assert 'ETag' in response['headers']
        etag = response['headers']['ETag']
        assert etag.startswith('"') and etag.endswith('"')

    def test_dashboard_304_on_etag_match(self, checkin_dynamodb):
        """Dashboard should return 304 when If-None-Match matches ETag"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_dashboard_data import lambda_handler

        # First request to get ETag
        event1 = _make_dashboard_event(MOCK_TOUR_ID, 'RIDE001')
        response1 = lambda_handler(event1, None)
        etag = response1['headers']['ETag']

        # Second request with If-None-Match
        event2 = _make_dashboard_event(
            MOCK_TOUR_ID, 'RIDE001',
            headers={'if-none-match': etag}
        )
        response2 = lambda_handler(event2, None)

        assert response2['statusCode'] == 304
        assert response2['body'] == ''
        assert response2['headers']['ETag'] == etag

    def test_dashboard_200_on_etag_mismatch(self, checkin_dynamodb):
        """Dashboard should return 200 when If-None-Match does not match"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_dashboard_data import lambda_handler

        event = _make_dashboard_event(
            MOCK_TOUR_ID, 'RIDE001',
            headers={'if-none-match': '"stale-etag"'}
        )
        response = lambda_handler(event, None)

        assert response['statusCode'] == 200
        assert 'ETag' in response['headers']

    def test_dashboard_200_on_data_change(self, checkin_dynamodb):
        """Dashboard ETag should change when data changes"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_dashboard_data import lambda_handler

        # First request
        event1 = _make_dashboard_event(MOCK_TOUR_ID, 'RIDE001')
        response1 = lambda_handler(event1, None)
        etag1 = response1['headers']['ETag']

        # Add a new check-in to change the data
        stack_name = os.environ['STACK_NAME']
        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        checkin_table.put_item(Item={
            'rideId': 'RIDE001',
            'checkInId': 'R2#000#2026-02-11T11:00:00Z',
            'riderId': 'R2',
            'stageNumber': 0,
            'stageId': 'S000',
            'timestamp': '2026-02-11T11:00:00Z',
            'checkedInBy': 'system',
            'method': 'QR_SCAN',
            'isNotRiding': False,
            'isQuitRiding': False,
            'isManualEntry': False,
            'status': 'CHECKED_IN',
            'createdAt': '2026-02-11T11:00:00Z'
        })

        # Reset dynamodb_utils cache for fresh query
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Second request with old ETag — should get 200 with new ETag
        event2 = _make_dashboard_event(
            MOCK_TOUR_ID, 'RIDE001',
            headers={'if-none-match': etag1}
        )
        response2 = lambda_handler(event2, None)

        assert response2['statusCode'] == 200
        etag2 = response2['headers']['ETag']
        assert etag1 != etag2


class TestDashboardProgressEndpoint:
    """Tests for lightweight dashboard progress endpoint."""

    def test_dashboard_progress_returns_compact_payload(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_dashboard_progress import lambda_handler

        event = _make_dashboard_progress_event(MOCK_TOUR_ID, 'RIDE001')
        response = lambda_handler(event, None)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        data = body['data']
        assert data['rideId'] == 'RIDE001'
        assert 'checkIns' in data
        assert 'cancelled' in data
        assert 'summary' in data
        assert 'dataVersion' in data
        assert 'ride' not in data
        assert 'riders' not in data

    def test_dashboard_progress_includes_cancelled_list(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        stack_name = os.environ['STACK_NAME']
        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        checkin_table.put_item(Item={
            'rideId': 'RIDE001',
            'checkInId': 'R2#001#2026-02-11T12:30:00Z',
            'riderId': 'R2',
            'stageNumber': 1,
            'stageId': 'S001',
            'timestamp': '2026-02-11T12:30:00Z',
            'checkedInBy': 'system',
            'method': 'QR_SCAN',
            'isNotRiding': False,
            'isQuitRiding': False,
            'isManualEntry': False,
            'status': 'CANCELLED',
            'prevStatus': 'CHECKED_IN',
            'cancelledBy': 'admin',
            'cancelledAt': '2026-02-11T13:00:00Z',
            'createdAt': '2026-02-11T12:30:00Z'
        })

        from get_dashboard_progress import lambda_handler

        event = _make_dashboard_progress_event(MOCK_TOUR_ID, 'RIDE001')
        response = lambda_handler(event, None)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        data = body['data']
        assert all(checkin['status'] != 'CANCELLED' for checkin in data['checkIns'])
        assert any(
            checkin['checkInId'] == 'R2#001#2026-02-11T12:30:00Z'
            for checkin in data['cancelled']
        )

    def test_dashboard_progress_supports_etag_304(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_dashboard_progress import lambda_handler

        first = _make_dashboard_progress_event(MOCK_TOUR_ID, 'RIDE001')
        first_response = lambda_handler(first, None)
        etag = first_response['headers']['ETag']

        second = _make_dashboard_progress_event(
            MOCK_TOUR_ID,
            'RIDE001',
            headers={'if-none-match': etag}
        )
        second_response = lambda_handler(second, None)

        assert second_response['statusCode'] == 304
        assert second_response['body'] == ''
        assert second_response['headers']['ETag'] == etag


class TestRiderDetailsEndpoint:
    """Tests for rider popup details endpoint."""

    def test_rider_details_returns_timeline_and_latest_status(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_ride_details import lambda_handler

        event = _make_rider_details_event(MOCK_TOUR_ID, 'RIDE001', 'R1')
        response = lambda_handler(event, None)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        data = body['data']
        assert data['rider']['riderId'] == 'R1'
        assert data['rider']['profileId'] == 'P001'
        assert data['latestStatus'] == 'CHECKED_IN'
        assert len(data['checkInTimeline']) >= 1

    def test_rider_details_excludes_cancelled_timeline_entries(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        stack_name = os.environ['STACK_NAME']
        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        checkin_table.put_item(Item={
            'rideId': 'RIDE001',
            'checkInId': 'R1#001#2026-02-11T11:30:00Z',
            'riderId': 'R1',
            'stageNumber': 1,
            'stageId': 'S001',
            'timestamp': '2026-02-11T11:30:00Z',
            'checkedInBy': 'system',
            'method': 'QR_SCAN',
            'isNotRiding': False,
            'isQuitRiding': False,
            'isManualEntry': False,
            'status': 'CANCELLED',
            'prevStatus': 'CHECKED_IN',
            'cancelledBy': 'admin',
            'cancelledAt': '2026-02-11T11:45:00Z',
            'createdAt': '2026-02-11T11:30:00Z'
        })

        from get_rider_ride_details import lambda_handler

        event = _make_rider_details_event(MOCK_TOUR_ID, 'RIDE001', 'R1')
        response = lambda_handler(event, None)
        body = json.loads(response['body'])

        assert response['statusCode'] == 200
        assert all(
            checkin['checkInId'] != 'R1#001#2026-02-11T11:30:00Z'
            for checkin in body['data']['checkInTimeline']
        )

    def test_rider_details_returns_404_for_missing_ride_or_rider(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_ride_details import lambda_handler

        missing_ride_event = _make_rider_details_event(MOCK_TOUR_ID, 'RIDE099', 'R1')
        missing_ride_response = lambda_handler(missing_ride_event, None)
        assert missing_ride_response['statusCode'] == 404

        missing_rider_event = _make_rider_details_event(MOCK_TOUR_ID, 'RIDE001', 'R99')
        missing_rider_response = lambda_handler(missing_rider_event, None)
        assert missing_rider_response['statusCode'] == 404

    def test_rider_details_supports_etag_304(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_ride_details import lambda_handler

        first = _make_rider_details_event(MOCK_TOUR_ID, 'RIDE001', 'R1')
        first_response = lambda_handler(first, None)
        etag = first_response['headers']['ETag']

        second = _make_rider_details_event(
            MOCK_TOUR_ID,
            'RIDE001',
            'R1',
            headers={'If-None-Match': etag}
        )
        second_response = lambda_handler(second, None)

        assert second_response['statusCode'] == 304
        assert second_response['body'] == ''
        assert second_response['headers']['ETag'] == etag


# ============================================================================
# TEST: Client Timestamp Validation
# ============================================================================

class TestClientTimestampValidation:
    """Tests for client-supplied timestamp validation"""

    def test_invalid_timestamp_format_rejected(self, checkin_dynamodb):
        """Invalid timestamp format should return 400"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_checkin import lambda_handler

        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'stageNumber': 0,
            'method': 'QR_SCAN',
            'timestamp': 'not-a-timestamp'
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400

    def test_valid_timestamp_used_in_checkin(self, checkin_dynamodb):
        """Valid client timestamp should be used as the check-in timestamp"""
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from create_checkin import lambda_handler

        client_ts = '2026-02-11T09:30:00Z'
        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'stageNumber': 0,
            'method': 'QR_SCAN',
            'timestamp': client_ts
        })

        response = lambda_handler(event, None)
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['data']['timestamp'] == client_ts


# ============================================================================
# TEST: Rider Check-In Query APIs
# ============================================================================

class TestRiderCheckInQueryApis:
    """Tests for rider check-in query endpoints."""

    def test_get_all_checkins_for_rider(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from get_rider_checkins import lambda_handler

        event = _make_get_rider_checkins_event(MOCK_TOUR_ID, 'R1')
        response = lambda_handler(event, None)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['riderId'] == 'R1'
        assert body['data']['count'] >= 1

    def test_get_checkins_for_rider_and_ride_no(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        stack_name = os.environ['STACK_NAME']
        ride_table = checkin_dynamodb.Table(f'{stack_name}-Ride-{MOCK_TOUR_ID}')
        ride_table.put_item(Item={
            'rideId': 'RIDE002',
            'rideNo': 2,
            'date': '2026-02-12',
            'name': 'City B to City C',
            'startLocation': 'City B',
            'finishLocation': 'City C',
            'totalDistance': Decimal('95.0'),
            'flagOffTime': '08:30',
            'status': 'ACTIVE',
            'stages': [
                {'stageId': 'S000', 'stageNumber': 0, 'type': 'START', 'name': 'Start'},
                {'stageId': 'S001', 'stageNumber': 1, 'type': 'PIT_STOP', 'name': 'PS1'},
                {'stageId': 'S002', 'stageNumber': 2, 'type': 'FINISH', 'name': 'Finish'}
            ],
            'createdAt': '2026-02-02T00:00:00Z',
            'updatedAt': '2026-02-02T00:00:00Z'
        })

        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        checkin_table.put_item(Item={
            'rideId': 'RIDE002',
            'checkInId': 'R1#000#2026-02-12T10:30:00Z',
            'riderId': 'R1',
            'stageNumber': 0,
            'stageId': 'S000',
            'timestamp': '2026-02-12T10:30:00Z',
            'checkedInBy': 'system',
            'method': 'QR_SCAN',
            'isNotRiding': False,
            'isQuitRiding': False,
            'isManualEntry': False,
            'status': 'CHECKED_IN',
            'createdAt': '2026-02-12T10:30:00Z'
        })

        from get_rider_ride_checkins import lambda_handler

        event = _make_get_rider_ride_checkins_event(MOCK_TOUR_ID, 'R1', 2)
        response = lambda_handler(event, None)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['rideNo'] == 2
        assert body['data']['count'] == 1
        assert body['data']['checkIns'][0]['rideId'] == 'RIDE002'

    def test_get_apis_exclude_cancelled_checkins(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        stack_name = os.environ['STACK_NAME']
        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        checkin_table.put_item(Item={
            'rideId': 'RIDE001',
            'checkInId': 'R2#001#2026-02-11T12:30:00Z',
            'riderId': 'R2',
            'stageNumber': 1,
            'stageId': 'S001',
            'timestamp': '2026-02-11T12:30:00Z',
            'checkedInBy': 'system',
            'method': 'QR_SCAN',
            'isNotRiding': False,
            'isQuitRiding': False,
            'isManualEntry': False,
            'status': 'CANCELLED',
            'prevStatus': 'CHECKED_IN',
            'cancelledBy': 'admin',
            'cancelledAt': '2026-02-11T13:00:00Z',
            'createdAt': '2026-02-11T12:30:00Z'
        })

        from get_ride_checkins import lambda_handler as get_ride_checkins_handler
        from get_rider_checkins import lambda_handler as get_rider_checkins_handler
        from get_rider_ride_checkins import lambda_handler as get_rider_ride_checkins_handler
        from get_dashboard_data import lambda_handler as get_dashboard_handler

        ride_event = {
            'pathParameters': {'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'}
        }
        ride_response = get_ride_checkins_handler(ride_event, None)
        ride_body = json.loads(ride_response['body'])
        assert all(
            checkin['status'] != 'CANCELLED'
            for checkin in ride_body['data']['checkIns']
        )

        rider_event = _make_get_rider_checkins_event(MOCK_TOUR_ID, 'R2')
        rider_response = get_rider_checkins_handler(rider_event, None)
        rider_body = json.loads(rider_response['body'])
        assert rider_body['data']['count'] == 0

        rider_ride_event = _make_get_rider_ride_checkins_event(MOCK_TOUR_ID, 'R2', 1)
        rider_ride_response = get_rider_ride_checkins_handler(rider_ride_event, None)
        rider_ride_body = json.loads(rider_ride_response['body'])
        assert rider_ride_body['data']['count'] == 0

        dashboard_event = _make_dashboard_event(MOCK_TOUR_ID, 'RIDE001')
        dashboard_response = get_dashboard_handler(dashboard_event, None)
        dashboard_body = json.loads(dashboard_response['body'])
        assert all(
            checkin['status'] != 'CANCELLED'
            for checkin in dashboard_body['data']['checkIns']
        )


class TestCancelledCheckinValidationExclusion:
    """Cancelled check-ins should not block new validation decisions."""

    def test_cancelled_duplicate_does_not_block_new_checkin(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        stack_name = os.environ['STACK_NAME']
        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        checkin_table.put_item(Item={
            'rideId': 'RIDE001',
            'checkInId': 'R2#001#2026-02-11T11:00:00Z',
            'riderId': 'R2',
            'stageNumber': 1,
            'stageId': 'S001',
            'timestamp': '2026-02-11T11:00:00Z',
            'checkedInBy': 'admin',
            'method': 'QR_SCAN',
            'isNotRiding': False,
            'isQuitRiding': False,
            'isManualEntry': False,
            'status': 'CANCELLED',
            'prevStatus': 'CHECKED_IN',
            'cancelledBy': 'admin',
            'cancelledAt': '2026-02-11T11:05:00Z',
            'createdAt': '2026-02-11T11:00:00Z'
        })

        from create_checkin import lambda_handler

        event = _make_checkin_event(MOCK_TOUR_ID, {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'stageNumber': 1,
            'method': 'QR_SCAN'
        })
        response = lambda_handler(event, None)

        assert response['statusCode'] == 201


# ============================================================================
# TEST: Cancel Check-In API
# ============================================================================

class TestCancelCheckInApi:
    """Tests for status-driven cancel check-in update flow."""

    def test_cancel_updates_only_cancellation_fields(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        stack_name = os.environ['STACK_NAME']
        checkin_table = checkin_dynamodb.Table(f'{stack_name}-CheckIn-{MOCK_TOUR_ID}')
        key = {
            'rideId': 'RIDE001',
            'checkInId': 'R1#000#2026-02-11T10:30:00Z'
        }
        original = checkin_table.get_item(Key=key)['Item']

        from cancel_checkin import lambda_handler

        event = _make_cancel_checkin_event(
            MOCK_TOUR_ID,
            'RIDE001',
            'R1#000#2026-02-11T10:30:00Z',
            {'status': 'CANCELLED', 'prevStatus': 'CHECKED_IN'}
        )
        response = lambda_handler(event, None)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['data']['status'] == 'CANCELLED'

        updated = checkin_table.get_item(Key=key)['Item']
        assert updated['status'] == 'CANCELLED'
        assert updated['prevStatus'] == 'CHECKED_IN'
        assert updated['cancelledBy'] == 'test-user-001'
        assert 'cancelledAt' in updated

        mutable_fields = {'status', 'prevStatus', 'cancelledBy', 'cancelledAt'}
        for field_name, field_value in original.items():
            if field_name in mutable_fields:
                continue
            assert updated[field_name] == field_value

    def test_cancel_rejects_non_cancelled_status(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from cancel_checkin import lambda_handler

        event = _make_cancel_checkin_event(
            MOCK_TOUR_ID,
            'RIDE001',
            'R1#000#2026-02-11T10:30:00Z',
            {'status': 'CHECKED_IN', 'prevStatus': 'CHECKED_IN'}
        )
        response = lambda_handler(event, None)

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['error']['code'] == 'INVALID_CANCEL_INVOCATION'

    def test_cancel_requires_prev_status(self, checkin_dynamodb):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from cancel_checkin import lambda_handler

        event = _make_cancel_checkin_event(
            MOCK_TOUR_ID,
            'RIDE001',
            'R1#000#2026-02-11T10:30:00Z',
            {'status': 'CANCELLED'}
        )
        response = lambda_handler(event, None)

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['error']['code'] == 'BAD_REQUEST'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
