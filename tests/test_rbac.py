"""
Unit tests for server-side RBAC (Role-Based Access Control)

Tests cover:
- rbac.py utility functions (get_user_groups, has_any_group, require_groups)
- RBAC enforcement in Lambda handlers:
    create_tour, archive_tour, create_ride, update_ride, close_ride,
    create_checkin, get_dashboard_data, list_tour_users, get_current_user
"""

import importlib
import os
import json
import pytest
import boto3
from decimal import Decimal
from moto import mock_aws

import sys
sys.path.insert(0, 'src/layers/common')

from tests.fixtures.mock_data import (
    MOCK_TOUR_ID, MOCK_TOURS, MOCK_TOUR_RIDERS, MOCK_RIDES,
    MOCK_RIDER_PROFILES, MOCK_CHECKINS
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(groups=None, path_params=None, query_params=None, body=None,
                method='GET'):
    """Build a minimal API Gateway v2 event with JWT claims."""
    claims = {
        'sub': 'user-001',
        'email': 'user@example.com',
        'cognito:username': 'testuser',
        'email_verified': 'true',
    }
    if groups is not None:
        claims['cognito:groups'] = ','.join(groups) if isinstance(groups, list) else groups

    event = {
        'version': '2.0',
        'requestContext': {
            'http': {'method': method},
            'authorizer': {
                'jwt': {'claims': claims}
            }
        },
        'pathParameters': path_params or {},
        'queryStringParameters': query_params,
        'headers': {},
        'body': json.dumps(body) if body else None
    }
    return event


def _load_handler(src_subpath: str, module_name: str):
    """
    Import (or reload) a Lambda handler module from src_subpath.

    Inserts the source directory into sys.path once and then reloads the
    module to pick up the current mocked environment.  Returns the module
    so callers can invoke ``module.lambda_handler``.
    """
    path = f'src/functions/{src_subpath}'
    if path not in sys.path:
        sys.path.insert(0, path)
    mod = importlib.import_module(module_name)
    importlib.reload(mod)
    return mod


def _convert_floats(obj):
    """Recursively convert float to Decimal for DynamoDB put_item."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _convert_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_floats(i) for i in obj]
    return obj


# ---------------------------------------------------------------------------
# rbac.py unit tests
# ---------------------------------------------------------------------------

class TestGetUserGroups:
    def test_no_claims_returns_empty(self):
        from rbac import get_user_groups
        assert get_user_groups({}) == []

    def test_no_groups_claim_returns_empty(self):
        from rbac import get_user_groups
        event = _make_event(groups=None)
        assert get_user_groups(event) == []

    def test_single_group_string(self):
        from rbac import get_user_groups
        event = _make_event(groups=['ADMINISTRATOR'])
        assert get_user_groups(event) == ['ADMINISTRATOR']

    def test_multiple_groups_comma_separated(self):
        from rbac import get_user_groups
        event = _make_event(groups=['ADMINISTRATOR', 'SUPER_USER'])
        groups = get_user_groups(event)
        assert 'ADMINISTRATOR' in groups
        assert 'SUPER_USER' in groups

    def test_groups_already_a_list(self):
        """Handles list values (used in unit-test mocks / local invocations)."""
        from rbac import get_user_groups
        event = {
            'requestContext': {
                'authorizer': {
                    'jwt': {
                        'claims': {'cognito:groups': ['ADMINISTRATOR', 'SUPER_USER']}
                    }
                }
            }
        }
        groups = get_user_groups(event)
        assert 'ADMINISTRATOR' in groups
        assert 'SUPER_USER' in groups

    def test_empty_string_returns_empty(self):
        from rbac import get_user_groups
        event = {
            'requestContext': {
                'authorizer': {
                    'jwt': {'claims': {'cognito:groups': ''}}
                }
            }
        }
        assert get_user_groups(event) == []


class TestHasAnyGroup:
    def test_has_matching_group(self):
        from rbac import has_any_group
        assert has_any_group(['ADMINISTRATOR'], ['ADMINISTRATOR', 'SUPER_USER']) is True

    def test_no_matching_group(self):
        from rbac import has_any_group
        assert has_any_group(['GUEST'], ['ADMINISTRATOR', 'SUPER_USER']) is False

    def test_empty_user_groups(self):
        from rbac import has_any_group
        assert has_any_group([], ['ADMINISTRATOR']) is False

    def test_empty_required_groups(self):
        from rbac import has_any_group
        assert has_any_group(['ADMINISTRATOR'], []) is False


class TestRequireGroups:
    def test_allowed_group_returns_none(self):
        from rbac import require_groups
        event = _make_event(groups=['ADMINISTRATOR'])
        assert require_groups(event, ['ADMINISTRATOR']) is None

    def test_denied_group_returns_403(self):
        from rbac import require_groups
        event = _make_event(groups=['GUEST'])
        result = require_groups(event, ['ADMINISTRATOR'])
        assert result is not None
        assert result['statusCode'] == 403

    def test_no_groups_claim_returns_403(self):
        from rbac import require_groups
        event = _make_event(groups=None)
        result = require_groups(event, ['ADMINISTRATOR'])
        assert result is not None
        assert result['statusCode'] == 403

    def test_custom_message_in_403(self):
        from rbac import require_groups
        event = _make_event(groups=['GUEST'])
        result = require_groups(event, ['ADMINISTRATOR'], message='Custom denied')
        body = json.loads(result['body'])
        assert 'Custom denied' in body['error']['message']

    def test_one_of_multiple_allowed_groups(self):
        from rbac import require_groups
        event = _make_event(groups=['SUPER_USER'])
        assert require_groups(event, ['ADMINISTRATOR', 'SUPER_USER']) is None


# ---------------------------------------------------------------------------
# Fixtures for Lambda handler tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope='function')
def aws_credentials():
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture(scope='function')
def rbac_dynamodb(aws_credentials):
    """Shared DynamoDB mock tables used across RBAC handler tests."""
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        stack_name = 'test-stack'

        # Shared TourMaster table
        tour_table = dynamodb.create_table(
            TableName='test-tour-master-table',
            KeySchema=[{'AttributeName': 'tourId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[
                {'AttributeName': 'tourId', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[{
                'IndexName': 'StatusIndex',
                'KeySchema': [{'AttributeName': 'status', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'},
                'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1}
            }],
            BillingMode='PAY_PER_REQUEST'
        )
        for tour in MOCK_TOURS:
            tour_table.put_item(Item=tour)

        # Shared RiderProfile table
        profile_table = dynamodb.create_table(
            TableName='test-rider-table',
            KeySchema=[{'AttributeName': 'profileId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'profileId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )
        for profile in MOCK_RIDER_PROFILES:
            profile_table.put_item(Item=profile)

        # Tour-specific TourRider table
        tour_rider_table = dynamodb.create_table(
            TableName=f'{stack_name}-TourRider-{MOCK_TOUR_ID}',
            KeySchema=[{'AttributeName': 'riderId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[
                {'AttributeName': 'riderId', 'AttributeType': 'S'},
                {'AttributeName': 'profileId', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[{
                'IndexName': 'ProfileIndex',
                'KeySchema': [{'AttributeName': 'profileId', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'},
                'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1}
            }],
            BillingMode='PAY_PER_REQUEST'
        )
        for rider in MOCK_TOUR_RIDERS:
            tour_rider_table.put_item(Item=rider)

        # Tour-specific Ride table
        ride_table = dynamodb.create_table(
            TableName=f'{stack_name}-Ride-{MOCK_TOUR_ID}',
            KeySchema=[{'AttributeName': 'rideId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[
                {'AttributeName': 'rideId', 'AttributeType': 'S'},
                {'AttributeName': 'date', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'DateIndex',
                    'KeySchema': [{'AttributeName': 'date', 'KeyType': 'HASH'}],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1}
                },
                {
                    'IndexName': 'StatusDateIndex',
                    'KeySchema': [
                        {'AttributeName': 'status', 'KeyType': 'HASH'},
                        {'AttributeName': 'date', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1}
                }
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        for ride in MOCK_RIDES:
            ride_table.put_item(Item=_convert_floats(ride))

        # Tour-specific CheckIn table
        checkin_table = dynamodb.create_table(
            TableName=f'{stack_name}-CheckIn-{MOCK_TOUR_ID}',
            KeySchema=[
                {'AttributeName': 'rideId', 'KeyType': 'HASH'},
                {'AttributeName': 'checkInId', 'KeyType': 'RANGE'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'rideId', 'AttributeType': 'S'},
                {'AttributeName': 'checkInId', 'AttributeType': 'S'},
                {'AttributeName': 'riderId', 'AttributeType': 'S'},
                {'AttributeName': 'timestamp', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[{
                'IndexName': 'RiderTimestampIndex',
                'KeySchema': [
                    {'AttributeName': 'riderId', 'KeyType': 'HASH'},
                    {'AttributeName': 'timestamp', 'KeyType': 'RANGE'},
                ],
                'Projection': {'ProjectionType': 'ALL'},
                'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1}
            }],
            BillingMode='PAY_PER_REQUEST'
        )
        for checkin in MOCK_CHECKINS:
            checkin_table.put_item(Item=checkin)

        # Tour-specific User table
        dynamodb.create_table(
            TableName=f'{stack_name}-User-{MOCK_TOUR_ID}',
            KeySchema=[{'AttributeName': 'userId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[
                {'AttributeName': 'userId', 'AttributeType': 'S'},
                {'AttributeName': 'email', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[{
                'IndexName': 'EmailIndex',
                'KeySchema': [{'AttributeName': 'email', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'},
                'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1}
            }],
            BillingMode='PAY_PER_REQUEST'
        )

        # Environment variables
        os.environ['TOUR_MASTER_TABLE'] = 'test-tour-master-table'
        os.environ['RIDER_PROFILE_TABLE'] = 'test-rider-table'
        os.environ['STACK_NAME'] = stack_name
        os.environ['ENVIRONMENT'] = 'test'
        os.environ['SUBSCRIPTION_ID'] = 'test-sub-001'
        os.environ['PHOTOS_BUCKET'] = 'test-photos-bucket'
        os.environ['LOG_LEVEL'] = 'INFO'

        yield dynamodb


# ---------------------------------------------------------------------------
# create_tour RBAC tests
# ---------------------------------------------------------------------------

class TestCreateTourRBAC:
    def test_administrator_allowed(self, rbac_dynamodb):
        create_tour = _load_handler('tours', 'create_tour')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            body={
                'tourId': 'NewTour-2026',
                'name': 'New Tour',
                'startDate': '2026-06-01',
                'endDate': '2026-06-10'
            },
            method='POST'
        )
        response = create_tour.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_super_user_denied(self, rbac_dynamodb):
        create_tour = _load_handler('tours', 'create_tour')
        event = _make_event(groups=['SUPER_USER'], body={}, method='POST')
        response = create_tour.lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_guest_denied(self, rbac_dynamodb):
        create_tour = _load_handler('tours', 'create_tour')
        event = _make_event(groups=['GUEST'], body={}, method='POST')
        response = create_tour.lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_no_group_denied(self, rbac_dynamodb):
        create_tour = _load_handler('tours', 'create_tour')
        event = _make_event(groups=None, body={}, method='POST')
        response = create_tour.lambda_handler(event, None)
        assert response['statusCode'] == 403


# ---------------------------------------------------------------------------
# create_ride RBAC tests
# ---------------------------------------------------------------------------

class TestCreateRideRBAC:
    def test_administrator_allowed(self, rbac_dynamodb):
        create_ride = _load_handler('rides', 'create_ride')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID},
            body={
                'rideId': 'RIDE002',
                'date': '2026-02-12',
                'rideNo': 2,
                'name': 'Ride 2',
                'startLocation': 'City B',
                'finishLocation': 'City C',
                'totalDistance': 80.0,
                'flagOffTime': '08:00',
                'stages': [{'stageId': 'S001', 'stageNumber': 1, 'type': 'START', 'name': 'Start'}]
            },
            method='POST'
        )
        response = create_ride.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_pit_stop_crew_denied(self, rbac_dynamodb):
        create_ride = _load_handler('rides', 'create_ride')
        event = _make_event(
            groups=['PIT_STOP_CREW'],
            path_params={'tourId': MOCK_TOUR_ID},
            body={},
            method='POST'
        )
        response = create_ride.lambda_handler(event, None)
        assert response['statusCode'] == 403


# ---------------------------------------------------------------------------
# update_ride RBAC tests
# ---------------------------------------------------------------------------

class TestUpdateRideRBAC:
    def test_administrator_allowed(self, rbac_dynamodb):
        update_ride = _load_handler('rides', 'update_ride')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'},
            body={'name': 'Updated Ride Name'},
            method='PUT'
        )
        response = update_ride.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_hotel_staff_denied(self, rbac_dynamodb):
        update_ride = _load_handler('rides', 'update_ride')
        event = _make_event(
            groups=['HOTEL_STAFF'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'},
            body={},
            method='PUT'
        )
        response = update_ride.lambda_handler(event, None)
        assert response['statusCode'] == 403


# ---------------------------------------------------------------------------
# close_ride RBAC tests
# ---------------------------------------------------------------------------

class TestCloseRideRBAC:
    def test_administrator_allowed(self, rbac_dynamodb):
        close_ride = _load_handler('rides', 'close_ride')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'},
            method='POST'
        )
        response = close_ride.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_super_user_denied(self, rbac_dynamodb):
        close_ride = _load_handler('rides', 'close_ride')
        event = _make_event(
            groups=['SUPER_USER'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'},
            method='POST'
        )
        response = close_ride.lambda_handler(event, None)
        assert response['statusCode'] == 403


# ---------------------------------------------------------------------------
# create_checkin RBAC tests
# ---------------------------------------------------------------------------

class TestCreateCheckinRBAC:
    def _checkin_body(self, method='QR_SCAN'):
        return {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'stageNumber': 2,
            'method': method
        }

    def test_pit_stop_crew_qr_scan_allowed(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['PIT_STOP_CREW'],
            path_params={'tourId': MOCK_TOUR_ID},
            body=self._checkin_body('QR_SCAN'),
            method='POST'
        )
        response = create_checkin.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_hotel_staff_qr_scan_allowed(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['HOTEL_STAFF'],
            path_params={'tourId': MOCK_TOUR_ID},
            body=self._checkin_body('QR_SCAN'),
            method='POST'
        )
        response = create_checkin.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_guest_denied(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['GUEST'],
            path_params={'tourId': MOCK_TOUR_ID},
            body=self._checkin_body('QR_SCAN'),
            method='POST'
        )
        response = create_checkin.lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_no_group_denied(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=None,
            path_params={'tourId': MOCK_TOUR_ID},
            body=self._checkin_body(),
            method='POST'
        )
        response = create_checkin.lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_pit_stop_crew_manual_denied(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['PIT_STOP_CREW'],
            path_params={'tourId': MOCK_TOUR_ID},
            body=self._checkin_body('MANUAL'),
            method='POST'
        )
        response = create_checkin.lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_hotel_staff_manual_denied(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['HOTEL_STAFF'],
            path_params={'tourId': MOCK_TOUR_ID},
            body=self._checkin_body('MANUAL'),
            method='POST'
        )
        response = create_checkin.lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_administrator_manual_allowed(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID},
            body=self._checkin_body('MANUAL'),
            method='POST'
        )
        response = create_checkin.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_super_user_manual_allowed(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['SUPER_USER'],
            path_params={'tourId': MOCK_TOUR_ID},
            body=self._checkin_body('MANUAL'),
            method='POST'
        )
        response = create_checkin.lambda_handler(event, None)
        assert response['statusCode'] != 403


# ---------------------------------------------------------------------------
# get_dashboard_data RBAC tests
# ---------------------------------------------------------------------------

class TestGetDashboardDataRBAC:
    def test_administrator_allowed(self, rbac_dynamodb):
        get_dashboard_data = _load_handler('checkins', 'get_dashboard_data')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'},
            method='GET'
        )
        response = get_dashboard_data.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_guest_allowed(self, rbac_dynamodb):
        get_dashboard_data = _load_handler('checkins', 'get_dashboard_data')
        event = _make_event(
            groups=['GUEST'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'},
            method='GET'
        )
        response = get_dashboard_data.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_pit_stop_crew_allowed(self, rbac_dynamodb):
        get_dashboard_data = _load_handler('checkins', 'get_dashboard_data')
        event = _make_event(
            groups=['PIT_STOP_CREW'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'},
            method='GET'
        )
        response = get_dashboard_data.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_hotel_staff_denied(self, rbac_dynamodb):
        get_dashboard_data = _load_handler('checkins', 'get_dashboard_data')
        event = _make_event(
            groups=['HOTEL_STAFF'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'},
            method='GET'
        )
        response = get_dashboard_data.lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_no_group_denied(self, rbac_dynamodb):
        get_dashboard_data = _load_handler('checkins', 'get_dashboard_data')
        event = _make_event(
            groups=None,
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'},
            method='GET'
        )
        response = get_dashboard_data.lambda_handler(event, None)
        assert response['statusCode'] == 403


# ---------------------------------------------------------------------------
# list_tour_users RBAC tests
# ---------------------------------------------------------------------------

class TestListTourUsersRBAC:
    def test_administrator_allowed(self, rbac_dynamodb):
        list_tour_users = _load_handler('users', 'list_tour_users')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID},
            method='GET'
        )
        response = list_tour_users.lambda_handler(event, None)
        assert response['statusCode'] == 200

    def test_super_user_allowed(self, rbac_dynamodb):
        list_tour_users = _load_handler('users', 'list_tour_users')
        event = _make_event(
            groups=['SUPER_USER'],
            path_params={'tourId': MOCK_TOUR_ID},
            method='GET'
        )
        response = list_tour_users.lambda_handler(event, None)
        assert response['statusCode'] == 200

    def test_pit_stop_crew_denied(self, rbac_dynamodb):
        list_tour_users = _load_handler('users', 'list_tour_users')
        event = _make_event(
            groups=['PIT_STOP_CREW'],
            path_params={'tourId': MOCK_TOUR_ID},
            method='GET'
        )
        response = list_tour_users.lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_hotel_staff_denied(self, rbac_dynamodb):
        list_tour_users = _load_handler('users', 'list_tour_users')
        event = _make_event(
            groups=['HOTEL_STAFF'],
            path_params={'tourId': MOCK_TOUR_ID},
            method='GET'
        )
        response = list_tour_users.lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_guest_denied(self, rbac_dynamodb):
        list_tour_users = _load_handler('users', 'list_tour_users')
        event = _make_event(
            groups=['GUEST'],
            path_params={'tourId': MOCK_TOUR_ID},
            method='GET'
        )
        response = list_tour_users.lambda_handler(event, None)
        assert response['statusCode'] == 403


# ---------------------------------------------------------------------------
# get_current_user — groups included in response
# ---------------------------------------------------------------------------

class TestGetCurrentUserGroups:
    def test_groups_included_in_response(self):
        get_current_user = _load_handler('users', 'get_current_user')
        event = _make_event(groups=['ADMINISTRATOR', 'SUPER_USER'])
        response = get_current_user.lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert 'groups' in body['data']
        assert 'ADMINISTRATOR' in body['data']['groups']

    def test_empty_groups_included(self):
        get_current_user = _load_handler('users', 'get_current_user')
        event = _make_event(groups=None)
        response = get_current_user.lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['data']['groups'] == []
