"""Focused event engine API tests."""

import json
import os
import re
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/events')
sys.path.insert(0, 'src/functions/hotels')
sys.path.insert(0, 'src/functions/users')


MOCK_TOUR_ID = 'TestTour-2026'


def test_effective_event_self_service_precedence():
    from event_permissions import effective_event_self_service_allowed

    event = {'selfServiceAllowed': False}
    activity = {'activityId': 'ACT-001', 'selfServiceAllowed': True}
    occurrence = {}
    assert effective_event_self_service_allowed(event, occurrence, activity) is True

    occurrence['selfServiceAllowed'] = False
    assert effective_event_self_service_allowed(event, occurrence, activity) is False

    occurrence['activityOverrides'] = [
        {'activityId': 'ACT-001', 'selfServiceAllowed': True}
    ]
    assert effective_event_self_service_allowed(event, occurrence, activity) is True

    occurrence['activityOverrides'][0]['selfServiceAllowed'] = False
    assert effective_event_self_service_allowed(event, occurrence, activity) is False


# create_tour_user derives username/email/name from the managed Cognito user,
# so tests stub a client that synthesizes one for any valid sub-shaped filter.
USER_1 = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
SCANNER_1 = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
SCANNER_2 = 'cccccccc-cccc-cccc-cccc-cccccccccccc'


class _FakeManagedUserCognitoClient:
    def list_users(self, UserPoolId, Filter=None, Limit=None):
        match = re.match(r'^sub = "(.+)"$', Filter or '')
        if not match:
            return {'Users': []}
        sub = match.group(1)
        return {
            'Users': [{
                'Username': f'user-{sub[:8]}',
                'Attributes': [
                    {'Name': 'sub', 'Value': sub},
                    {'Name': 'email', 'Value': f'{sub[:8]}@example.com'},
                    {'Name': 'name', 'Value': f'Test User {sub[:8]}'},
                ],
                'Enabled': True,
                'UserStatus': 'CONFIRMED',
            }]
        }


@pytest.fixture
def event_engine_env():
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
    os.environ['STACK_NAME'] = 'test-stack'
    os.environ['APP_CONFIG_TABLE'] = 'test-app-config-table'
    os.environ['RIDER_PROFILE_TABLE'] = 'test-rider-profile-table'
    os.environ['ARTIFACTS_BUCKET'] = 'test-artifacts-bucket'
    os.environ['LOG_LEVEL'] = 'INFO'


@pytest.fixture
def event_engine_setup(event_engine_env):
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        dynamodb.create_table(
            TableName='test-app-config-table',
            KeySchema=[
                {'AttributeName': 'configType', 'KeyType': 'HASH'},
                {'AttributeName': 'configId', 'KeyType': 'RANGE'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'configType', 'AttributeType': 'S'},
                {'AttributeName': 'configId', 'AttributeType': 'S'},
            ],
            BillingMode='PAY_PER_REQUEST',
        ).put_item(Item={
            'configType': 'ID_CODE_TYPE',
            'configId': '1',
            'enabled': True,
            'config': {'name': 'RIDER'}
        })
        dynamodb.create_table(
            TableName='test-rider-profile-table',
            KeySchema=[{'AttributeName': 'profileId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'profileId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        ).put_item(Item={'profileId': 'P001', 'name': 'John Doe'})
        tables = [
            {
                'TableName': f'test-stack-Event-{MOCK_TOUR_ID}',
                'KeySchema': [{'AttributeName': 'eventId', 'KeyType': 'HASH'}],
                'AttributeDefinitions': [{'AttributeName': 'eventId', 'AttributeType': 'S'}],
            },
            {
                'TableName': f'test-stack-EventOccurrence-{MOCK_TOUR_ID}',
                'KeySchema': [{'AttributeName': 'eventId', 'KeyType': 'HASH'}, {'AttributeName': 'dateSeq', 'KeyType': 'RANGE'}],
                'AttributeDefinitions': [
                    {'AttributeName': 'eventId', 'AttributeType': 'S'},
                    {'AttributeName': 'dateSeq', 'AttributeType': 'S'},
                    {'AttributeName': 'date', 'AttributeType': 'S'},
                    {'AttributeName': 'status', 'AttributeType': 'S'},
                ],
                'GlobalSecondaryIndexes': [
                    {
                        'IndexName': 'DateIndex',
                        'KeySchema': [{'AttributeName': 'date', 'KeyType': 'HASH'}, {'AttributeName': 'eventId', 'KeyType': 'RANGE'}],
                        'Projection': {'ProjectionType': 'ALL'},
                    },
                    {
                        'IndexName': 'StatusIndex',
                        'KeySchema': [{'AttributeName': 'status', 'KeyType': 'HASH'}, {'AttributeName': 'date', 'KeyType': 'RANGE'}],
                        'Projection': {'ProjectionType': 'ALL'},
                    },
                ],
            },
            {
                'TableName': f'test-stack-EventActivityLogs-{MOCK_TOUR_ID}',
                'KeySchema': [{'AttributeName': 'occurrenceId', 'KeyType': 'HASH'}, {'AttributeName': 'recordId', 'KeyType': 'RANGE'}],
                'AttributeDefinitions': [
                    {'AttributeName': 'occurrenceId', 'AttributeType': 'S'},
                    {'AttributeName': 'recordId', 'AttributeType': 'S'},
                    {'AttributeName': 'riderId', 'AttributeType': 'S'},
                    {'AttributeName': 'timestamp', 'AttributeType': 'S'},
                ],
                'GlobalSecondaryIndexes': [
                    {
                        'IndexName': 'RiderTimestampIndex',
                        'KeySchema': [{'AttributeName': 'riderId', 'KeyType': 'HASH'}, {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}],
                        'Projection': {'ProjectionType': 'ALL'},
                    },
                ],
            },
            {
                'TableName': f'test-stack-Hotel-{MOCK_TOUR_ID}',
                'KeySchema': [{'AttributeName': 'hotelId', 'KeyType': 'HASH'}],
                'AttributeDefinitions': [{'AttributeName': 'hotelId', 'AttributeType': 'S'}],
            },
            {
                'TableName': f'test-stack-RoomAllocation-{MOCK_TOUR_ID}',
                'KeySchema': [{'AttributeName': 'stayDate', 'KeyType': 'HASH'}, {'AttributeName': 'riderId', 'KeyType': 'RANGE'}],
                'AttributeDefinitions': [
                    {'AttributeName': 'stayDate', 'AttributeType': 'S'},
                    {'AttributeName': 'riderId', 'AttributeType': 'S'},
                    {'AttributeName': 'hotelId', 'AttributeType': 'S'},
                ],
                'GlobalSecondaryIndexes': [
                    {
                        'IndexName': 'RiderIdIndex',
                        'KeySchema': [{'AttributeName': 'riderId', 'KeyType': 'HASH'}, {'AttributeName': 'stayDate', 'KeyType': 'RANGE'}],
                        'Projection': {'ProjectionType': 'ALL'},
                    },
                    {
                        'IndexName': 'HotelDateIndex',
                        'KeySchema': [{'AttributeName': 'hotelId', 'KeyType': 'HASH'}, {'AttributeName': 'stayDate', 'KeyType': 'RANGE'}],
                        'Projection': {'ProjectionType': 'ALL'},
                    },
                ],
            },
            {
                'TableName': f'test-stack-TourRider-{MOCK_TOUR_ID}',
                'KeySchema': [{'AttributeName': 'riderId', 'KeyType': 'HASH'}],
                'AttributeDefinitions': [
                    {'AttributeName': 'riderId', 'AttributeType': 'S'},
                    {'AttributeName': 'profileId', 'AttributeType': 'S'},
                ],
                'GlobalSecondaryIndexes': [
                    {
                        'IndexName': 'ProfileIdIndex',
                        'KeySchema': [{'AttributeName': 'profileId', 'KeyType': 'HASH'}],
                        'Projection': {'ProjectionType': 'ALL'},
                    },
                ],
            },
            {
                'TableName': f'test-stack-EventRegistration-{MOCK_TOUR_ID}',
                'KeySchema': [
                    {'AttributeName': 'occurrenceId', 'KeyType': 'HASH'},
                    {'AttributeName': 'riderId', 'KeyType': 'RANGE'},
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'occurrenceId', 'AttributeType': 'S'},
                    {'AttributeName': 'riderId', 'AttributeType': 'S'},
                ],
            },
            {
                'TableName': f'test-stack-User-{MOCK_TOUR_ID}',
                'KeySchema': [{'AttributeName': 'userId', 'KeyType': 'HASH'}],
                'AttributeDefinitions': [{'AttributeName': 'userId', 'AttributeType': 'S'}, {'AttributeName': 'email', 'AttributeType': 'S'}],
                'GlobalSecondaryIndexes': [
                    {
                        'IndexName': 'EmailIndex',
                        'KeySchema': [{'AttributeName': 'email', 'KeyType': 'HASH'}],
                        'Projection': {'ProjectionType': 'ALL'},
                    },
                ],
            },
        ]
        for table in tables:
            dynamodb.create_table(BillingMode='PAY_PER_REQUEST', **table)

        dynamodb.Table(f'test-stack-TourRider-{MOCK_TOUR_ID}').put_item(Item={
            'riderId': 'R1',
            'profileId': 'P001',
            'status': 'ACTIVE',
            'baggageStatus': 'ACTIVE',
        })

        os.environ['MGMT_USER_POOL_ID'] = 'test-mgmt-pool'
        import event_engine
        event_engine.cognito_client = _FakeManagedUserCognitoClient()

        yield dynamodb


def _event(groups, path_params, method='GET', body=None, query=None, sub='admin-1'):
    return {
        'version': '2.0',
        'rawPath': 'ignored',
        'requestContext': {
            'http': {'method': method},
            'authorizer': {'jwt': {'claims': {'sub': sub, 'cognito:groups': ','.join(groups)}}},
        },
        'pathParameters': path_params,
        'queryStringParameters': query,
        'headers': {},
        'body': json.dumps(body) if body is not None else None,
    }


def test_create_event_and_occurrence_flow(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from create_event import lambda_handler as create_event_handler
    from create_occurrence import lambda_handler as create_occurrence_handler
    from get_event import lambda_handler as get_event_handler

    create_response = create_event_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'eventId': 'EVT-REG',
                'eventName': 'Day 0 Registration',
                'eventType': 'SINGLE',
                'location': 'Venue',
                'sequenceEnforced': True,
                'defaultAllowedTypeCodes': ['1'],
                'activities': [{'activityId': 'ACT-001', 'name': 'ID Card', 'sequenceNo': 0}],
            },
        ),
        None,
    )
    assert create_response['statusCode'] == 201

    get_response = get_event_handler(_event(['ADMINISTRATOR'], {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-REG'}), None)
    assert get_response['statusCode'] == 200

    occurrence_response = create_occurrence_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-REG'},
            method='POST',
            body={'date': '2026-02-10', 'seq': 1},
        ),
        None,
    )
    assert occurrence_response['statusCode'] == 201
    data = json.loads(occurrence_response['body'])['data']
    assert data['occurrenceId'] == 'EVT-REG#2026-02-10#1'


def test_event_registration_and_self_service_flags_are_boolean(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from create_event import lambda_handler as create_event_handler
    from create_occurrence import lambda_handler as create_occurrence_handler

    invalid_event = create_event_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'eventId': 'EVT-INVALID',
                'eventName': 'Invalid Event',
                'eventType': 'SINGLE',
                'location': 'Venue',
                'sequenceEnforced': True,
                'defaultAllowedTypeCodes': ['1'],
                'registrationEnabled': 'true',
                'activities': [
                    {'activityId': 'ACT-001', 'name': 'Check-in', 'sequenceNo': 1}
                ],
            },
        ),
        None,
    )
    assert invalid_event['statusCode'] == 400

    dynamodb_utils.get_tour_table('Event', MOCK_TOUR_ID).put_item(Item={
        'eventId': 'EVT-INVALID',
        'registrationEnabled': True,
        'activities': [],
    })
    invalid_occurrence = create_occurrence_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-INVALID'},
            method='POST',
            body={
                'date': '2026-02-10',
                'seq': 1,
                'selfServiceAllowed': 'true',
            },
        ),
        None,
    )
    assert invalid_occurrence['statusCode'] == 400


def test_event_registration_lists_rider_and_staff_sources(event_engine_setup, monkeypatch):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from registration import lambda_handler as registration_handler
    import registration

    monkeypatch.setattr(registration, '_rider_for_claims', lambda event, tour_id: 'R1')
    event_table = dynamodb_utils.get_tour_table('Event', MOCK_TOUR_ID)
    event_table.put_item(Item={
        'eventId': 'EVT-REG',
        'registrationEnabled': True,
    })
    dynamodb_utils.get_tour_table('EventOccurrence', MOCK_TOUR_ID).put_item(Item={
        'eventId': 'EVT-REG',
        'dateSeq': '2026-02-10#1',
        'occurrenceId': 'EVT-REG#2026-02-10#1',
        'status': 'PLANNED',
    })
    tour_riders = dynamodb_utils.get_tour_table('TourRider', MOCK_TOUR_ID)
    tour_riders.put_item(Item={'riderId': 'R2', 'profileId': 'P002', 'status': 'ACTIVE'})
    dynamodb_utils.get_table('RIDER_PROFILE_TABLE').put_item(
        Item={'profileId': 'P002', 'name': 'Sam Rider'}
    )

    rider_registration = registration_handler(
        _event(
            ['RIDER'],
            {
                'tourId': MOCK_TOUR_ID,
                'eventId': 'EVT-REG',
                'occurrenceId': 'EVT-REG#2026-02-10#1',
            },
            method='POST',
            sub='rider-sub',
        ),
        None,
    )
    assert rider_registration['statusCode'] == 201
    rider_data = json.loads(rider_registration['body'])['data']
    assert rider_data['source'] == 'rider'
    assert rider_data['registeredBy'] == 'rider-sub'

    staff_registration = registration_handler(
        _event(
            ['ADMINISTRATOR'],
            {
                'tourId': MOCK_TOUR_ID,
                'eventId': 'EVT-REG',
                'occurrenceId': 'EVT-REG#2026-02-10#1',
                'riderId': 'R2',
            },
            method='PUT',
            sub='staff-sub',
        ),
        None,
    )
    assert staff_registration['statusCode'] == 200
    staff_data = json.loads(staff_registration['body'])['data']
    assert staff_data['source'] == 'staff'
    assert staff_data['registeredBy'] == 'staff-sub'

    list_response = registration_handler(
        _event(
            ['ADMINISTRATOR'],
            {
                'tourId': MOCK_TOUR_ID,
                'eventId': 'EVT-REG',
                'occurrenceId': 'EVT-REG#2026-02-10#1',
            },
            method='GET',
        ),
        None,
    )
    assert list_response['statusCode'] == 200
    listed = json.loads(list_response['body'])['data']['registrations']
    assert listed == [
        {
            'riderId': 'R1',
            'name': 'John Doe',
            'registeredAt': rider_data['registeredAt'],
            'registeredBy': 'rider-sub',
            'source': 'rider',
        },
        {
            'riderId': 'R2',
            'name': 'Sam Rider',
            'registeredAt': staff_data['registeredAt'],
            'registeredBy': 'staff-sub',
            'source': 'staff',
        },
    ]

    template = open('template.yaml', encoding='utf-8').read()
    registration_resource = template.split('  EventRegistrationFunction:', 1)[1].split(
        '  RiderSelfEventRecordFunction:', 1
    )[0]
    assert 'Method: GET' in registration_resource
    assert '/occurrences/{occurrenceId}/registrations' in registration_resource
    assert '/occurrences/{occurrenceId}/registrations/{riderId}' in registration_resource
    assert 'Method: PUT' in registration_resource
    assert 'Method: DELETE' in registration_resource
    cancel_resource = template.split('  RiderCancelSelfEventRecordFunction:', 1)[1].split(
        '  GetDashboardDataFunction:', 1
    )[0]
    assert 'ManageRegister:' not in cancel_resource


def test_rider_event_progress_is_limited_to_calling_rider(monkeypatch):
    import event_engine

    monkeypatch.setattr(event_engine, 'is_rider_api_request', lambda event: True)
    monkeypatch.setattr(event_engine, '_rider_id_for_request', lambda event, tour_id: 'R1')
    monkeypatch.setattr(event_engine, 'validate_tour_id', lambda value: None)
    monkeypatch.setattr(event_engine, 'validate_rider_id', lambda value: None)
    monkeypatch.setattr(event_engine, 'query_tour_items', lambda *args, **kwargs: [])
    monkeypatch.setattr(event_engine, 'scan_tour_items', lambda *args, **kwargs: [])

    response = event_engine.get_rider_progress({
        'pathParameters': {'tourId': MOCK_TOUR_ID, 'riderId': 'R2'},
        'queryStringParameters': {},
    })

    assert response['statusCode'] == 403
    assert json.loads(response['body'])['error']['code'] == 'PROFILE_ACCESS_DENIED'


def test_create_hotel_and_tour_user(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from create_event import lambda_handler as create_event_handler
    from create_hotel import lambda_handler as create_hotel_handler
    from create_tour_user import lambda_handler as create_tour_user_handler

    create_event_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'eventId': 'EVT-BAGLOAD',
                'eventName': 'Baggage Loading',
                'eventType': 'REPEATING',
                'location': 'Origin hotel',
                'sequenceEnforced': True,
                'defaultAllowedTypeCodes': ['1'],
                'activities': [{'activityId': 'ACT-001', 'name': 'Pickup', 'sequenceNo': 0}],
            },
        ),
        None,
    )

    hotel_response = create_hotel_handler(
        _event(
            ['SUPER_USER'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={'hotelId': 'HTL-MDU-01', 'name': 'Hotel', 'city': 'Madurai', 'address': 'Addr'},
        ),
        None,
    )
    assert hotel_response['statusCode'] == 201

    user_response = create_tour_user_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'userId': USER_1,
                'role': 'HOTEL_STAFF',
                'hotelId': 'HTL-MDU-01',
                'eventAssignments': [{'eventId': 'EVT-BAGLOAD', 'dates': 'ALL'}],
            },
        ),
        None,
    )
    assert user_response['statusCode'] == 201


def test_event_read_endpoints_require_read_permission(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from create_event import lambda_handler as create_event_handler
    from create_occurrence import lambda_handler as create_occurrence_handler
    from get_activity_overrides import lambda_handler as get_activity_overrides_handler
    from get_event import lambda_handler as get_event_handler
    from list_events import lambda_handler as list_events_handler
    from list_occurrences import lambda_handler as list_occurrences_handler

    create_event_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'eventId': 'EVT-READ',
                'eventName': 'Read Protected Event',
                'eventType': 'SINGLE',
                'location': 'Venue',
                'sequenceEnforced': False,
                'defaultAllowedTypeCodes': ['1'],
                'activities': [{'activityId': 'ACT-001', 'name': 'Desk', 'sequenceNo': 1}],
            },
        ),
        None,
    )
    create_occurrence_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-READ'},
            method='POST',
            body={'date': '2026-02-10', 'seq': 1},
        ),
        None,
    )
    for response in (
        list_events_handler(_event([], {'tourId': MOCK_TOUR_ID}), None),
        get_event_handler(_event([], {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-READ'}), None),
        list_occurrences_handler(_event([], {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-READ'}), None),
        get_activity_overrides_handler(
            _event([], {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-READ', 'occurrenceId': 'EVT-READ#2026-02-10#1'}),
            None,
        ),
    ):
        assert response['statusCode'] == 403


def test_create_activity_record_allows_opt_out_without_type_code(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from create_activity_record import lambda_handler as create_activity_record_handler
    from create_event import lambda_handler as create_event_handler
    from create_occurrence import lambda_handler as create_occurrence_handler
    from create_tour_user import lambda_handler as create_tour_user_handler
    from start_occurrence import lambda_handler as start_occurrence_handler

    create_event_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'eventId': 'EVT-OPT',
                'eventName': 'Optional Scan Event',
                'eventType': 'SINGLE',
                'location': 'Venue',
                'sequenceEnforced': False,
                'defaultAllowedTypeCodes': ['1'],
                'activities': [
                    {
                        'activityId': 'ACT-001',
                        'name': 'Desk',
                        'sequenceNo': 1,
                        'allowOptOut': True,
                    }
                ],
            },
        ),
        None,
    )
    create_occurrence_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-OPT'},
            method='POST',
            body={'date': '2026-02-10', 'seq': 1},
        ),
        None,
    )
    start_occurrence_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-OPT', 'occurrenceId': 'EVT-OPT#2026-02-10#1'},
            method='POST',
            body={'startedAt': '2026-02-10T08:00:00Z'},
        ),
        None,
    )
    create_tour_user_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'userId': SCANNER_1,
                'role': 'SUPER_USER',
                'status': 'ACTIVE',
            },
        ),
        None,
    )

    response = create_activity_record_handler(
        _event(
            ['SUPER_USER'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-OPT', 'occurrenceId': 'EVT-OPT#2026-02-10#1'},
            method='POST',
            sub=SCANNER_1,
            body={
                'activityId': 'ACT-001',
                'riderId': 'R1',
                'outcome': 'OPTED_OUT',
                'method': 'MANUAL',
                'timestamp': '2026-02-10T08:05:00Z',
            },
        ),
        None,
    )

    assert response['statusCode'] == 201
    body = json.loads(response['body'])
    assert body['data']['outcome'] == 'OPTED_OUT'
    assert body['data'].get('typeCode') is None


def test_create_activity_record_requires_type_code_for_non_opt_out(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from create_activity_record import lambda_handler as create_activity_record_handler
    from create_event import lambda_handler as create_event_handler
    from create_occurrence import lambda_handler as create_occurrence_handler
    from create_tour_user import lambda_handler as create_tour_user_handler
    from start_occurrence import lambda_handler as start_occurrence_handler

    create_event_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'eventId': 'EVT-REQ',
                'eventName': 'Required Type Event',
                'eventType': 'SINGLE',
                'location': 'Venue',
                'sequenceEnforced': False,
                'defaultAllowedTypeCodes': ['1'],
                'activities': [{'activityId': 'ACT-001', 'name': 'Desk', 'sequenceNo': 1}],
            },
        ),
        None,
    )
    create_occurrence_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-REQ'},
            method='POST',
            body={'date': '2026-02-10', 'seq': 1},
        ),
        None,
    )
    start_occurrence_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-REQ', 'occurrenceId': 'EVT-REQ#2026-02-10#1'},
            method='POST',
            body={'startedAt': '2026-02-10T08:00:00Z'},
        ),
        None,
    )
    create_tour_user_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'userId': SCANNER_2,
                'role': 'SUPER_USER',
                'status': 'ACTIVE',
            },
        ),
        None,
    )

    response = create_activity_record_handler(
        _event(
            ['SUPER_USER'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-REQ', 'occurrenceId': 'EVT-REQ#2026-02-10#1'},
            method='POST',
            sub=SCANNER_2,
            body={
                'activityId': 'ACT-001',
                'riderId': 'R1',
                'method': 'MANUAL',
                'timestamp': '2026-02-10T08:05:00Z',
            },
        ),
        None,
    )

    assert response['statusCode'] == 400
    body = json.loads(response['body'])
    assert body['error']['message'] == 'typeCode is required for this activity record.'


def test_update_event_definition_updates_allowed_codes_and_activities(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from create_event import lambda_handler as create_event_handler
    from update_event import lambda_handler as update_event_handler

    create_event_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'eventId': 'EVT-UPD',
                'eventName': 'Needs Update',
                'eventType': 'SINGLE',
                'location': 'Venue',
                'sequenceEnforced': False,
                'defaultAllowedTypeCodes': ['1'],
                'activities': [{'activityId': 'ACT-001', 'name': 'Desk', 'sequenceNo': 1}],
            },
        ),
        None,
    )

    response = update_event_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-UPD'},
            method='PUT',
            body={
                'defaultAllowedTypeCodes': ['1'],
                'activities': [
                    {'activityId': 'ACT-001', 'name': 'Desk Updated', 'sequenceNo': 1},
                    {'activityId': 'ACT-002', 'name': 'Badge', 'sequenceNo': 2, 'allowedTypeCodes': ['1']},
                ],
                'sequenceEnforced': True,
            },
        ),
        None,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['data']['sequenceEnforced'] is True
    assert len(body['data']['activities']) == 2
    assert body['data']['activities'][0]['name'] == 'Desk Updated'
    assert body['data']['activities'][1]['activityId'] == 'ACT-002'


def test_update_event_definition_rejects_invalid_activity_order(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from create_event import lambda_handler as create_event_handler
    from update_event import lambda_handler as update_event_handler

    create_event_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'eventId': 'EVT-BAD',
                'eventName': 'Bad Update Event',
                'eventType': 'SINGLE',
                'location': 'Venue',
                'sequenceEnforced': False,
                'defaultAllowedTypeCodes': ['1'],
                'activities': [{'activityId': 'ACT-001', 'name': 'Desk', 'sequenceNo': 1}],
            },
        ),
        None,
    )

    response = update_event_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-BAD'},
            method='PUT',
            body={
                'activities': [
                    {'activityId': 'ACT-002', 'name': 'Badge', 'sequenceNo': 2},
                    {'activityId': 'ACT-001', 'name': 'Desk', 'sequenceNo': 1},
                ]
            },
        ),
        None,
    )

    assert response['statusCode'] == 400
    body = json.loads(response['body'])
    assert body['error']['message'] == 'activities must be ordered by ascending sequenceNo'


LOAD_OCCURRENCE_ID = 'EVT-BAGLOAD#2026-02-12#1'
UNLOAD_OCCURRENCE_ID = 'EVT-BAGUNLOAD#2026-02-12#1'


def _seed_reconciliation_data(dynamodb, load_overrides=None):
    def activity(activity_id, sequence_no):
        return {'activityId': activity_id, 'name': activity_id, 'sequenceNo': sequence_no, 'enabled': True}

    events = dynamodb.Table(f'test-stack-Event-{MOCK_TOUR_ID}')
    events.put_item(Item={
        'eventId': 'EVT-BAGLOAD',
        'activities': [activity('ACT-001', 1), activity('ACT-002', 2), activity('ACT-003', 3)],
    })
    events.put_item(Item={
        'eventId': 'EVT-BAGUNLOAD',
        'activities': [activity('ACT-001', 1), activity('ACT-002', 2)],
    })

    occurrences = dynamodb.Table(f'test-stack-EventOccurrence-{MOCK_TOUR_ID}')
    occurrences.put_item(Item={
        'eventId': 'EVT-BAGLOAD',
        'dateSeq': '2026-02-12#1',
        'occurrenceId': LOAD_OCCURRENCE_ID,
        'date': '2026-02-12',
        'status': 'ACTIVE',
        'activityOverrides': load_overrides or [],
        'linkedOccurrenceRef': UNLOAD_OCCURRENCE_ID,
    })
    occurrences.put_item(Item={
        'eventId': 'EVT-BAGUNLOAD',
        'dateSeq': '2026-02-12#1',
        'occurrenceId': UNLOAD_OCCURRENCE_ID,
        'date': '2026-02-12',
        'status': 'ACTIVE',
        'activityOverrides': [],
    })

    records = dynamodb.Table(f'test-stack-EventActivityLogs-{MOCK_TOUR_ID}')

    def record(occurrence_id, rider_id, activity_id, type_code=None, outcome='COMPLETED', cancelled=False):
        timestamp = '2026-02-12T05:40:00Z'
        item = {
            'occurrenceId': occurrence_id,
            'recordId': f'{rider_id}#{activity_id}#{type_code}#{timestamp}',
            'riderId': rider_id,
            'activityId': activity_id,
            'outcome': outcome,
            'timestamp': timestamp,
        }
        if type_code:
            item['typeCode'] = type_code
        if cancelled:
            item['cancelledAt'] = '2026-02-12T06:00:00Z'
        records.put_item(Item=item)

    # Loading: R1 loads two bags; R2 opts out; R3 only reaches the first step; R4's scan is cancelled; R5 at ACT-002
    record(LOAD_OCCURRENCE_ID, 'R1', 'ACT-003', '3')
    record(LOAD_OCCURRENCE_ID, 'R1', 'ACT-003', '4')
    record(LOAD_OCCURRENCE_ID, 'R2', 'ACT-001', outcome='OPTED_OUT')
    record(LOAD_OCCURRENCE_ID, 'R3', 'ACT-001', '3')
    record(LOAD_OCCURRENCE_ID, 'R4', 'ACT-003', '3', cancelled=True)
    record(LOAD_OCCURRENCE_ID, 'R5', 'ACT-002', '3')
    # Unloading: only R1's bag 3 reaches the final step; bag 4 stops at the first step
    record(UNLOAD_OCCURRENCE_ID, 'R1', 'ACT-002', '3')
    record(UNLOAD_OCCURRENCE_ID, 'R1', 'ACT-001', '4')


def _call_reconciliation():
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    from get_reconciliation import lambda_handler as get_reconciliation_handler

    response = get_reconciliation_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-BAGLOAD', 'occurrenceId': LOAD_OCCURRENCE_ID},
        ),
        None,
    )
    assert response['statusCode'] == 200
    return json.loads(response['body'])['data']


def test_reconciliation_counts_only_final_activity_bags(event_engine_setup):
    _seed_reconciliation_data(event_engine_setup)

    data = _call_reconciliation()

    assert data == {'loadedCount': 2, 'unloadedCount': 1, 'missingRiderIds': ['R1']}


def test_reconciliation_uses_last_enabled_activity_after_override(event_engine_setup):
    _seed_reconciliation_data(
        event_engine_setup,
        load_overrides=[{'activityId': 'ACT-003', 'enabled': False}],
    )

    data = _call_reconciliation()

    assert data == {'loadedCount': 1, 'unloadedCount': 1, 'missingRiderIds': ['R5']}
