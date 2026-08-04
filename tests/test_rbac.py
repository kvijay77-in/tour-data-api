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


def test_decimal_encoder_preserves_integer_values():
    from response import DecimalEncoder

    payload = {
        'rideNo': Decimal('1'),
        'stageNumber': Decimal('2'),
        'floatNo': Decimal('3'),
        'totalDistance': Decimal('120.5'),
    }

    encoded = json.dumps(payload, cls=DecimalEncoder)
    decoded = json.loads(encoded)

    assert decoded['rideNo'] == 1
    assert isinstance(decoded['rideNo'], int)
    assert decoded['stageNumber'] == 2
    assert isinstance(decoded['stageNumber'], int)
    assert decoded['floatNo'] == 3
    assert isinstance(decoded['floatNo'], int)
    assert decoded['totalDistance'] == 120.5
    assert isinstance(decoded['totalDistance'], float)


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

    def test_bracketed_group_string(self):
        from rbac import get_user_groups
        event = {
            'requestContext': {
                'authorizer': {
                    'jwt': {
                        'claims': {'cognito:groups': '[SUPER_USER]'}
                    }
                }
            }
        }
        assert get_user_groups(event) == ['SUPER_USER']

    def test_json_array_group_string(self):
        from rbac import get_user_groups
        event = {
            'requestContext': {
                'authorizer': {
                    'jwt': {
                        'claims': {'cognito:groups': '["PS_1_USER", "PS_3_USER"]'}
                    }
                }
            }
        }
        assert get_user_groups(event) == ['PS_1_USER', 'PS_3_USER']

    def test_whitespace_separated_group_string(self):
        from rbac import get_user_groups
        event = {
            'requestContext': {
                'authorizer': {
                    'jwt': {
                        'claims': {'cognito:groups': 'PS_1_USER PS_3_USER'}
                    }
                }
            }
        }
        assert get_user_groups(event) == ['PS_1_USER', 'PS_3_USER']

    def test_falls_back_to_custom_roles_claim(self):
        from rbac import get_user_groups
        event = {
            'requestContext': {
                'authorizer': {
                    'jwt': {
                        'claims': {'custom:roles': '["PS_1_USER", "PS_3_USER"]'}
                    }
                }
            }
        }
        assert get_user_groups(event) == ['PS_1_USER', 'PS_3_USER']


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


class TestGroupPermissionsMapping:
    """Verify the GROUP_PERMISSIONS mapping is internally consistent."""

    def test_administrator_has_all_permissions(self):
        from rbac import GROUP_PERMISSIONS, Permission
        admin_perms = set(GROUP_PERMISSIONS['ADMINISTRATOR'])
        assert admin_perms == set(Permission)

    def test_guest_only_read_and_dashboard(self):
        from rbac import GROUP_PERMISSIONS, Permission
        guest_perms = set(GROUP_PERMISSIONS['GUEST'])
        assert guest_perms == {Permission.READ, Permission.DASHBOARD}

    def test_hotel_staff_has_no_dashboard(self):
        from rbac import GROUP_PERMISSIONS, Permission
        hotel_perms = set(GROUP_PERMISSIONS['HOTEL_STAFF'])
        assert Permission.DASHBOARD not in hotel_perms

    def test_dynamic_pit_stop_group_has_no_manual_checkin(self):
        from rbac import Permission, get_user_permissions
        event = _make_event(groups=['PS_3_USER'])
        pit_perms = get_user_permissions(event)
        assert Permission.CHECKIN_MANUAL not in pit_perms
        assert Permission.PIT_STOP_MANAGE in pit_perms

    def test_super_user_has_no_tour_or_ride_manage(self):
        from rbac import GROUP_PERMISSIONS, Permission
        su_perms = set(GROUP_PERMISSIONS['SUPER_USER'])
        assert Permission.TOUR_MANAGE not in su_perms
        assert Permission.RIDE_MANAGE not in su_perms

    def test_standard_groups_present(self):
        from rbac import GROUP_PERMISSIONS
        expected = {'ADMINISTRATOR', 'SUPER_USER', 'HOTEL_STAFF', 'GUEST', 'RIDER'}
        assert expected == set(GROUP_PERMISSIONS.keys())

    def test_dynamic_pit_stop_group_pattern_not_stored_in_mapping(self):
        from rbac import GROUP_PERMISSIONS
        assert 'PS_1_USER' not in GROUP_PERMISSIONS

    def test_unknown_group_not_in_mapping(self):
        from rbac import GROUP_PERMISSIONS
        assert 'UNKNOWN_GROUP' not in GROUP_PERMISSIONS


class TestGetUserPermissions:
    def test_administrator_gets_all_permissions(self):
        from rbac import get_user_permissions, Permission
        event = _make_event(groups=['ADMINISTRATOR'])
        perms = get_user_permissions(event)
        assert perms == set(Permission)

    def test_super_user_gets_pit_stop_manage(self):
        from rbac import get_user_permissions, Permission
        event = _make_event(groups=['SUPER_USER'])
        perms = get_user_permissions(event)
        assert Permission.PIT_STOP_MANAGE in perms


class TestRequirePitStopStageAccess:
    def test_admin_not_stage_bound(self):
        from rbac import require_pit_stop_stage_access
        event = _make_event(groups=['ADMINISTRATOR'])
        assert require_pit_stop_stage_access(event, 3) is None

    def test_pit_stop_user_allowed_for_assigned_stage(self):
        from rbac import require_pit_stop_stage_access
        event = _make_event(groups=['PS_2_USER'])
        assert require_pit_stop_stage_access(event, 2) is None

    def test_pit_stop_user_denied_for_unassigned_stage(self):
        from rbac import require_pit_stop_stage_access
        event = _make_event(groups=['PS_2_USER'])
        response = require_pit_stop_stage_access(event, 1)
        assert response['statusCode'] == 403

    def test_guest_gets_read_and_dashboard_only(self):
        from rbac import get_user_permissions, Permission
        event = _make_event(groups=['GUEST'])
        perms = get_user_permissions(event)
        assert perms == {Permission.READ, Permission.DASHBOARD}

    def test_hotel_staff_has_no_dashboard(self):
        from rbac import get_user_permissions, Permission
        event = _make_event(groups=['HOTEL_STAFF'])
        perms = get_user_permissions(event)
        assert Permission.DASHBOARD not in perms

    def test_no_groups_gives_empty_permissions(self):
        from rbac import get_user_permissions
        event = _make_event(groups=None)
        assert get_user_permissions(event) == set()

    def test_unknown_group_gives_empty_permissions(self):
        from rbac import get_user_permissions
        event = _make_event(groups=['UNKNOWN_GROUP'])
        assert get_user_permissions(event) == set()

    def test_dynamic_pit_stop_group_gets_standard_permissions(self):
        from rbac import get_user_permissions, Permission
        event = _make_event(groups=['PS_2_USER'])
        perms = get_user_permissions(event)
        assert perms == {
            Permission.READ,
            Permission.CHECKIN,
            Permission.PIT_STOP_MANAGE,
            Permission.DASHBOARD,
        }

    def test_multiple_groups_union_permissions(self):
        """User in multiple groups receives union of all their permissions."""
        from rbac import get_user_permissions, Permission
        # PS_2_USER     = [READ, CHECKIN, DASHBOARD]
        # HOTEL_STAFF   = [READ, CHECKIN]
        # Union         = [READ, CHECKIN, DASHBOARD]
        event = _make_event(groups=['PS_2_USER', 'HOTEL_STAFF'])
        perms = get_user_permissions(event)
        assert Permission.READ in perms
        assert Permission.CHECKIN in perms
        assert Permission.DASHBOARD in perms

    def test_admin_and_pit_stop_roles_use_admin_priority(self):
        from rbac import get_user_permissions, Permission
        event = _make_event(groups=['PS_1_USER', 'ADMINISTRATOR'])
        perms = get_user_permissions(event)
        assert Permission.TOUR_MANAGE in perms
        assert Permission.RIDE_MANAGE in perms
        assert Permission.CHECKIN_MANUAL in perms

    def test_super_user_and_pit_stop_roles_use_super_user_priority(self):
        from rbac import get_user_permissions, Permission
        event = _make_event(groups=['PS_1_USER', 'SUPER_USER'])
        perms = get_user_permissions(event)
        assert Permission.CHECKIN_MANUAL in perms
        assert Permission.TOUR_MANAGE not in perms

    def test_pit_stop_role_has_priority_over_hotel_staff(self):
        from rbac import get_user_permissions, Permission
        event = _make_event(groups=['HOTEL_STAFF', 'PS_2_USER'])
        perms = get_user_permissions(event)
        assert Permission.DASHBOARD in perms

    def test_hotel_staff_has_priority_over_guest(self):
        from rbac import get_user_permissions, Permission
        event = _make_event(groups=['GUEST', 'HOTEL_STAFF'])
        perms = get_user_permissions(event)
        assert Permission.CHECKIN in perms
        assert Permission.DASHBOARD not in perms

    def test_effective_group_priority_chain(self):
        from rbac import get_effective_group
        assert get_effective_group(['GUEST', 'HOTEL_STAFF']) == 'HOTEL_STAFF'
        assert get_effective_group(['HOTEL_STAFF', 'PS_4_USER']) == 'PS_4_USER'
        assert get_effective_group(['PS_3_USER', 'SUPER_USER']) == 'SUPER_USER'
        assert get_effective_group(['SUPER_USER', 'ADMINISTRATOR']) == 'ADMINISTRATOR'

    def test_multiple_pit_stop_roles_use_first_role(self):
        from rbac import get_effective_group
        assert get_effective_group(['PS_3_USER', 'PS_1_USER']) == 'PS_3_USER'

    def test_multiple_pit_stop_groups_return_multiple_stage_numbers(self):
        from rbac import get_user_pit_stop_stage_numbers
        event = _make_event(groups=['PS_1_USER', 'PS_3_USER'])
        assert get_user_pit_stop_stage_numbers(event) == {1, 3}


class TestRequirePermission:
    def test_has_permission_returns_none(self):
        from rbac import require_permission, Permission
        event = _make_event(groups=['ADMINISTRATOR'])
        assert require_permission(event, Permission.TOUR_MANAGE) is None

    def test_lacks_permission_returns_403(self):
        from rbac import require_permission, Permission
        event = _make_event(groups=['GUEST'])
        result = require_permission(event, Permission.TOUR_MANAGE)
        assert result is not None
        assert result['statusCode'] == 403

    def test_no_groups_returns_403(self):
        from rbac import require_permission, Permission
        event = _make_event(groups=None)
        result = require_permission(event, Permission.CHECKIN)
        assert result is not None
        assert result['statusCode'] == 403

    def test_custom_message_in_403(self):
        from rbac import require_permission, Permission
        event = _make_event(groups=['GUEST'])
        result = require_permission(event, Permission.TOUR_MANAGE, message='Custom denied')
        body = json.loads(result['body'])
        assert 'Custom denied' in body['error']['message']

    def test_permission_name_in_default_message(self):
        from rbac import require_permission, Permission
        event = _make_event(groups=['GUEST'])
        result = require_permission(event, Permission.RIDE_MANAGE)
        body = json.loads(result['body'])
        assert 'RIDE_MANAGE' in body['error']['message']

    def test_hotel_staff_denied_dashboard(self):
        from rbac import require_permission, Permission
        event = _make_event(groups=['HOTEL_STAFF'])
        result = require_permission(event, Permission.DASHBOARD)
        assert result['statusCode'] == 403

    def test_pit_stop_user_allowed_checkin(self):
        from rbac import require_permission, Permission
        event = _make_event(groups=['PS_1_USER'])
        assert require_permission(event, Permission.CHECKIN) is None

    def test_pit_stop_user_denied_checkin_manual(self):
        from rbac import require_permission, Permission
        event = _make_event(groups=['PS_1_USER'])
        result = require_permission(event, Permission.CHECKIN_MANUAL)
        assert result['statusCode'] == 403


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
                'openTime': '07:30',
                'closeTime': '13:30',
                'stages': [
                    {'stageId': 'S000', 'stageNumber': 0, 'type': 'START', 'name': 'Start'},
                    {
                        'stageId': 'S001', 'stageNumber': 1, 'type': 'PIT_STOP',
                        'name': 'PS1', 'estimatedOpenTime': 90, 'pitStopDuration': 30
                    },
                    {'stageId': 'S002', 'stageNumber': 2, 'type': 'FINISH', 'name': 'Finish'}
                ]
            },
            method='POST'
        )
        response = create_ride.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_create_ride_persists_floats(self, rbac_dynamodb):
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
                'stages': [
                    {'stageId': 'S000', 'stageNumber': 0, 'type': 'START', 'name': 'Start'},
                    {'stageId': 'S001', 'stageNumber': 1, 'type': 'PIT_STOP', 'name': 'PS1'},
                    {'stageId': 'S002', 'stageNumber': 2, 'type': 'FINISH', 'name': 'Finish'}
                ],
                'floats': [
                    {'floatNo': 2, 'floatToStage': 2},
                    {'floatNo': 1, 'floatToStage': 1}
                ]
            },
            method='POST'
        )

        response = create_ride.lambda_handler(event, None)

        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body['data']['floats'] == [
            {'floatNo': 1, 'floatToStage': 1},
            {'floatNo': 2, 'floatToStage': 2},
        ]

        table = rbac_dynamodb.Table(f'test-stack-Ride-{MOCK_TOUR_ID}')
        item = table.get_item(Key={'rideId': 'RIDE002'})['Item']
        assert item['floats'] == [
            {'floatNo': Decimal('1'), 'floatToStage': Decimal('1')},
            {'floatNo': Decimal('2'), 'floatToStage': Decimal('2')},
        ]

    def test_pit_stop_user_denied(self, rbac_dynamodb):
        create_ride = _load_handler('rides', 'create_ride')
        event = _make_event(
            groups=['PS_1_USER'],
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

    def test_get_ride_returns_existing_floats(self, rbac_dynamodb):
        get_ride = _load_handler('rides', 'get_ride')
        event = _make_event(
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'}
        )

        response = get_ride.lambda_handler(event, None)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['data']['rideNo'] == 1
        assert isinstance(body['data']['rideNo'], int)
        assert body['data']['floats'] == [{'floatNo': 1, 'floatToStage': 1}]
        assert isinstance(body['data']['floats'][0]['floatNo'], int)
        assert isinstance(body['data']['floats'][0]['floatToStage'], int)
        assert isinstance(body['data']['stages'][0]['stageNumber'], int)
        assert isinstance(body['data']['totalDistance'], float)


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
# open_ride RBAC tests
# ---------------------------------------------------------------------------

class TestOpenRideRBAC:
    def test_administrator_allowed(self, rbac_dynamodb):
        open_ride = _load_handler('rides', 'open_ride')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID},
            method='POST'
        )
        response = open_ride.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_super_user_denied(self, rbac_dynamodb):
        open_ride = _load_handler('rides', 'open_ride')
        event = _make_event(
            groups=['SUPER_USER'],
            path_params={'tourId': MOCK_TOUR_ID},
            method='POST'
        )
        response = open_ride.lambda_handler(event, None)
        assert response['statusCode'] == 403


# ---------------------------------------------------------------------------
# start_ride RBAC tests
# ---------------------------------------------------------------------------

class TestStartRideRBAC:
    def test_administrator_allowed(self, rbac_dynamodb):
        start_ride = _load_handler('rides', 'start_ride')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID},
            method='POST'
        )
        response = start_ride.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_super_user_denied(self, rbac_dynamodb):
        start_ride = _load_handler('rides', 'start_ride')
        event = _make_event(
            groups=['SUPER_USER'],
            path_params={'tourId': MOCK_TOUR_ID},
            method='POST'
        )
        response = start_ride.lambda_handler(event, None)
        assert response['statusCode'] == 403


class TestPitStopManageRBAC:
    def test_super_user_allowed_to_open_pit_stop(self, rbac_dynamodb):
        open_pit_stop = _load_handler('rides', 'open_pit_stop')
        event = _make_event(
            groups=['SUPER_USER'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001', 'stageNumber': '1'},
            method='POST'
        )
        response = open_pit_stop.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_hotel_staff_denied_to_open_pit_stop(self, rbac_dynamodb):
        open_pit_stop = _load_handler('rides', 'open_pit_stop')
        event = _make_event(
            groups=['HOTEL_STAFF'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001', 'stageNumber': '1'},
            method='POST'
        )
        response = open_pit_stop.lambda_handler(event, None)
        assert response['statusCode'] == 403


class TestPitStopHandlers:
    def _set_started_ride(self, dynamodb, stage_status=None):
        table = dynamodb.Table(f'test-stack-Ride-{MOCK_TOUR_ID}')
        ride = dict(MOCK_RIDES[0])
        ride['status'] = 'STARTED'
        ride['startedAt'] = '2026-02-11T08:00:00Z'
        if stage_status is not None:
            ride['stages'] = [dict(stage) for stage in ride['stages']]
            ride['stages'][1]['pitStopStatus'] = stage_status
            if stage_status == 'OPEN':
                ride['stages'][1]['openedAt'] = '2026-02-11T09:30:00Z'
            if stage_status == 'CLOSED':
                ride['stages'][1]['openedAt'] = '2026-02-11T09:30:00Z'
                ride['stages'][1]['closedAt'] = '2026-02-11T10:15:00Z'
        table.put_item(Item=_convert_floats(ride))

    def test_open_pit_stop_success_for_assigned_user(self, rbac_dynamodb):
        self._set_started_ride(rbac_dynamodb)
        open_pit_stop = _load_handler('rides', 'open_pit_stop')
        event = _make_event(
            groups=['PS_1_USER'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001', 'stageNumber': '1'},
            method='POST'
        )
        response = open_pit_stop.lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['data']['stages'][1]['pitStopStatus'] == 'OPEN'
        assert 'openedAt' in body['data']['stages'][1]

    def test_open_pit_stop_denied_for_wrong_stage_user(self, rbac_dynamodb):
        self._set_started_ride(rbac_dynamodb)
        open_pit_stop = _load_handler('rides', 'open_pit_stop')
        event = _make_event(
            groups=['PS_2_USER'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001', 'stageNumber': '1'},
            method='POST'
        )
        response = open_pit_stop.lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_open_pit_stop_requires_started_ride(self, rbac_dynamodb):
        open_pit_stop = _load_handler('rides', 'open_pit_stop')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001', 'stageNumber': '1'},
            method='POST'
        )
        response = open_pit_stop.lambda_handler(event, None)
        assert response['statusCode'] == 400

    def test_open_pit_stop_rejects_non_pit_stop_stage(self, rbac_dynamodb):
        self._set_started_ride(rbac_dynamodb)
        open_pit_stop = _load_handler('rides', 'open_pit_stop')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001', 'stageNumber': '0'},
            method='POST'
        )
        response = open_pit_stop.lambda_handler(event, None)
        assert response['statusCode'] == 400

    def test_close_pit_stop_success(self, rbac_dynamodb):
        self._set_started_ride(rbac_dynamodb, stage_status='OPEN')
        close_pit_stop = _load_handler('rides', 'close_pit_stop')
        event = _make_event(
            groups=['PS_1_USER'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001', 'stageNumber': '1'},
            method='POST'
        )
        response = close_pit_stop.lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['data']['stages'][1]['pitStopStatus'] == 'CLOSED'
        assert 'closedAt' in body['data']['stages'][1]

    def test_close_pit_stop_requires_open_status(self, rbac_dynamodb):
        self._set_started_ride(rbac_dynamodb)
        close_pit_stop = _load_handler('rides', 'close_pit_stop')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001', 'stageNumber': '1'},
            method='POST'
        )
        response = close_pit_stop.lambda_handler(event, None)
        assert response['statusCode'] == 400

    def test_update_ride_preserves_pit_stop_runtime_fields(self, rbac_dynamodb):
        self._set_started_ride(rbac_dynamodb, stage_status='OPEN')
        update_ride = _load_handler('rides', 'update_ride')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'},
            body={
                'stages': [
                    {'stageId': 'S000', 'stageNumber': 0, 'type': 'START', 'name': 'Start Point'},
                    {
                        'stageId': 'S001', 'stageNumber': 1, 'type': 'PIT_STOP',
                        'name': 'Pit Stop 1 Updated', 'estimatedOpenTime': 100, 'pitStopDuration': 50
                    },
                    {'stageId': 'S002', 'stageNumber': 2, 'type': 'FINISH', 'name': 'Finish Line'}
                ]
            },
            method='PUT'
        )
        response = update_ride.lambda_handler(event, None)
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['data']['stages'][1]['pitStopStatus'] == 'OPEN'
        assert body['data']['stages'][1]['openedAt'] == '2026-02-11T09:30:00Z'

    def test_update_ride_updates_floats(self, rbac_dynamodb):
        update_ride = _load_handler('rides', 'update_ride')
        event = _make_event(
            groups=['ADMINISTRATOR'],
            path_params={'tourId': MOCK_TOUR_ID, 'rideId': 'RIDE001'},
            body={
                'floats': [
                    {'floatNo': 2, 'floatToStage': 2},
                    {'floatNo': 1, 'floatToStage': 1}
                ]
            },
            method='PUT'
        )

        response = update_ride.lambda_handler(event, None)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['data']['floats'] == [
            {'floatNo': 1, 'floatToStage': 1},
            {'floatNo': 2, 'floatToStage': 2},
        ]


# ---------------------------------------------------------------------------
# create_checkin RBAC tests
# ---------------------------------------------------------------------------

class TestCreateCheckinRBAC:
    def _checkin_body(self, method='QR_SCAN'):
        return {
            'riderId': 'R2',
            'rideId': 'RIDE001',
            'stageNumber': 1,
            'method': method
        }

    def test_pit_stop_user_qr_scan_allowed_for_assigned_stage(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['PS_1_USER'],
            path_params={'tourId': MOCK_TOUR_ID},
            body=self._checkin_body('QR_SCAN'),
            method='POST'
        )
        response = create_checkin.lambda_handler(event, None)
        assert response['statusCode'] != 403

    def test_pit_stop_user_denied_for_unassigned_stage(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['PS_2_USER'],
            path_params={'tourId': MOCK_TOUR_ID},
            body=self._checkin_body('QR_SCAN'),
            method='POST'
        )
        response = create_checkin.lambda_handler(event, None)
        assert response['statusCode'] == 403
        body = json.loads(response['body'])
        assert body['error']['code'] == 'PIT_STOP_ROLE_STAGE_MISMATCH'

    def test_pit_stop_user_denied_for_finish_stage_regular_checkin(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['PS_2_USER'],
            path_params={'tourId': MOCK_TOUR_ID},
            body={
                'riderId': 'R2',
                'rideId': 'RIDE001',
                'stageNumber': 2,
                'method': 'QR_SCAN'
            },
            method='POST'
        )
        response = create_checkin.lambda_handler(event, None)
        assert response['statusCode'] == 403
        body = json.loads(response['body'])
        assert body['error']['code'] == 'PIT_STOP_ROLE_STAGE_MISMATCH'

    def test_pit_stop_user_allowed_for_quit_riding(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['PS_2_USER'],
            path_params={'tourId': MOCK_TOUR_ID},
            body={
                'riderId': 'R2',
                'rideId': 'RIDE001',
                'method': 'QR_SCAN',
                'isQuitRiding': True
            },
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

    def test_pit_stop_user_manual_denied(self, rbac_dynamodb):
        create_checkin = _load_handler('checkins', 'create_checkin')
        event = _make_event(
            groups=['PS_1_USER'],
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

    def test_pit_stop_user_allowed(self, rbac_dynamodb):
        get_dashboard_data = _load_handler('checkins', 'get_dashboard_data')
        event = _make_event(
            groups=['PS_1_USER'],
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

    def test_pit_stop_user_denied(self, rbac_dynamodb):
        list_tour_users = _load_handler('users', 'list_tour_users')
        event = _make_event(
            groups=['PS_1_USER'],
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
