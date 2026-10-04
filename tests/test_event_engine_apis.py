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
                'TableName': f'test-stack-EventRegistration-{MOCK_TOUR_ID}',
                'KeySchema': [
                    {'AttributeName': 'occurrenceId', 'KeyType': 'HASH'},
                    {'AttributeName': 'riderId', 'KeyType': 'RANGE'},
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'occurrenceId', 'AttributeType': 'S'},
                    {'AttributeName': 'riderId', 'AttributeType': 'S'},
                ],
                'GlobalSecondaryIndexes': [{
                    'IndexName': 'RiderIdIndex',
                    'KeySchema': [
                        {'AttributeName': 'riderId', 'KeyType': 'HASH'},
                        {'AttributeName': 'occurrenceId', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                }],
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
                'AttributeDefinitions': [{'AttributeName': 'riderId', 'AttributeType': 'S'}],
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


def test_activity_override_null_clears_self_service_value(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from update_activity_overrides import lambda_handler

    dynamodb_utils.get_tour_table('Event', MOCK_TOUR_ID).put_item(Item={
        'eventId': 'EVT-REG',
        'eventName': 'Day 0 Registration',
        'eventType': 'SINGLE',
        'location': 'Venue',
        'sequenceEnforced': True,
        'defaultAllowedTypeCodes': ['1'],
        'activities': [{'activityId': 'ACT-001', 'name': 'ID Card', 'sequenceNo': 0}],
    })
    dynamodb_utils.get_tour_table('EventOccurrence', MOCK_TOUR_ID).put_item(Item={
        'eventId': 'EVT-REG',
        'dateSeq': '2026-02-10#1',
        'occurrenceId': 'EVT-REG#2026-02-10#1',
        'date': '2026-02-10',
        'seq': 1,
        'status': 'PLANNED',
        'activityOverrides': [{'activityId': 'ACT-001', 'enabled': True, 'selfServiceAllowed': True}],
    })

    response = lambda_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-REG', 'occurrenceId': 'EVT-REG#2026-02-10#1'},
            method='PUT',
            body={'activityId': 'ACT-001', 'selfServiceAllowed': None},
        ),
        None,
    )

    assert response['statusCode'] == 200
    override = json.loads(response['body'])['data']['items'][0]
    assert override['enabled'] is True
    assert 'selfServiceAllowed' not in override


def test_occurrence_null_clears_self_service_value(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from create_occurrence import lambda_handler as create_occurrence_handler
    from update_occurrence import lambda_handler as update_occurrence_handler

    dynamodb_utils.get_tour_table('Event', MOCK_TOUR_ID).put_item(Item={
        'eventId': 'EVT-REG', 'selfServiceAllowed': True,
    })
    params = {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-REG'}
    create_response = create_occurrence_handler(
        _event(['ADMINISTRATOR'], params, method='POST',
               body={'date': '2026-02-10', 'seq': 1, 'selfServiceAllowed': None}), None,
    )
    assert create_response['statusCode'] == 201
    assert 'selfServiceAllowed' not in json.loads(create_response['body'])['data']

    params['occurrenceId'] = 'EVT-REG#2026-02-10#1'
    for value in (False, None):
        response = update_occurrence_handler(
            _event(['ADMINISTRATOR'], params, method='PUT', body={'selfServiceAllowed': value}), None,
        )
        assert response['statusCode'] == 200
        occurrence = json.loads(response['body'])['data']
        if value is None:
            assert 'selfServiceAllowed' not in occurrence
        else:
            assert occurrence['selfServiceAllowed'] is False
    stored = dynamodb_utils.get_tour_table('EventOccurrence', MOCK_TOUR_ID).get_item(
        Key={'eventId': 'EVT-REG', 'dateSeq': '2026-02-10#1'},
    )['Item']
    assert 'selfServiceAllowed' not in stored

    invalid_response = update_occurrence_handler(
        _event(['ADMINISTRATOR'], params, method='PUT', body={'selfServiceAllowed': 'false'}), None,
    )
    assert invalid_response['statusCode'] == 400


def test_event_activity_flags_reject_null(event_engine_setup):
    import dynamodb_utils
    import event_engine
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    with pytest.raises(event_engine.ValidationError):
        event_engine._normalise_activity({
            'activityId': 'ACT-001',
            'name': 'Activity',
            'sequenceNo': 0,
            'selfServiceAllowed': None,
        })

    with pytest.raises(event_engine.ValidationError):
        event_engine._bool_if_present({'selfServiceAllowed': None}, 'selfServiceAllowed')


def test_legacy_event_fields_are_ignored_and_never_returned(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from create_event import lambda_handler as create_event_handler
    from get_event import lambda_handler as get_event_handler
    from get_occurrence import lambda_handler as get_occurrence_handler

    create_response = create_event_handler(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID},
            method='POST',
            body={
                'eventId': 'EVT-LEGACY',
                'eventName': 'Legacy input',
                'eventType': 'SINGLE',
                'location': 'Venue',
                'sequenceEnforced': False,
                'defaultAllowedTypeCodes': [],
                'allowSelfService': True,
                'allow_self_service': True,
                'activities': [{
                    'activityId': 'ACT-001',
                    'name': 'Activity',
                    'sequenceNo': 0,
                    'selfServiceEnabled': True,
                    'self_service_enabled': True,
                }],
            },
        ),
        None,
    )
    assert create_response['statusCode'] == 201
    created = json.loads(create_response['body'])['data']
    assert created['registrationEnabled'] is False
    assert created['selfServiceAllowed'] is False
    assert 'allowSelfService' not in created
    assert 'self_service_enabled' not in created['activities'][0]

    event_table = dynamodb_utils.get_tour_table('Event', MOCK_TOUR_ID)
    event_table.put_item(Item={
        'eventId': 'EVT-OLDSTORED',
        'eventName': 'Old stored fields',
        'eventType': 'SINGLE',
        'location': 'Venue',
        'sequenceEnforced': False,
        'defaultAllowedTypeCodes': [],
        'allowSelfService': True,
        'activities': [{
            'activityId': 'ACT-001',
            'name': 'Activity',
            'sequenceNo': 0,
            'selfServiceEnabled': True,
        }],
    })
    occurrence_table = dynamodb_utils.get_tour_table('EventOccurrence', MOCK_TOUR_ID)
    occurrence_table.put_item(Item={
        'eventId': 'EVT-OLDSTORED',
        'dateSeq': '2026-02-10#1',
        'occurrenceId': 'EVT-OLDSTORED#2026-02-10#1',
        'date': '2026-02-10',
        'seq': 1,
        'status': 'PLANNED',
        'selfServiceEnabled': True,
        'activityOverrides': [{'activityId': 'ACT-001', 'selfServiceEnabled': True}],
    })

    event_response = get_event_handler(
            _event(['ADMINISTRATOR'], {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-OLDSTORED'}),
        None,
    )
    occurrence_response = get_occurrence_handler(
        _event(
            ['ADMINISTRATOR'],
            {
                'tourId': MOCK_TOUR_ID,
                'eventId': 'EVT-OLDSTORED',
                'occurrenceId': 'EVT-OLDSTORED#2026-02-10#1',
            },
        ),
        None,
    )
    assert event_response['statusCode'] == 200, event_response
    assert occurrence_response['statusCode'] == 200, occurrence_response
    event_data = json.loads(event_response['body'])['data']
    occurrence_data = json.loads(occurrence_response['body'])['data']
    assert 'allowSelfService' not in event_data
    assert 'selfServiceEnabled' not in event_data['activities'][0]
    assert 'selfServiceEnabled' not in occurrence_data
    assert 'selfServiceEnabled' not in occurrence_data['activityOverrides'][0]


def _store_registration_event(dynamodb_utils, registration_enabled=True, occurrence_status='PLANNED'):
    dynamodb_utils.get_tour_table('Event', MOCK_TOUR_ID).put_item(Item={
        'eventId': 'EVT-REG',
        'eventName': 'Registration',
        'eventType': 'SINGLE',
        'location': 'Venue',
        'sequenceEnforced': False,
        'defaultAllowedTypeCodes': ['1'],
        'registrationEnabled': registration_enabled,
        'selfServiceAllowed': True,
        'activities': [{
            'activityId': 'ACT-001',
            'name': 'Check in',
            'sequenceNo': 0,
            'restrictToAssignedUsers': False,
            'selfServiceAllowed': True,
        }],
    })
    dynamodb_utils.get_tour_table('EventOccurrence', MOCK_TOUR_ID).put_item(Item={
        'eventId': 'EVT-REG',
        'dateSeq': '2026-02-10#1',
        'occurrenceId': 'EVT-REG#2026-02-10#1',
        'date': '2026-02-10',
        'seq': 1,
        'status': occurrence_status,
        'restrictToAssignedUsers': False,
        'activityOverrides': [],
    })


def _rider_event_request(method='POST', body=None, rider_id=None):
    path_params = {
        'tourId': MOCK_TOUR_ID,
        'eventId': 'EVT-REG',
        'occurrenceId': 'EVT-REG#2026-02-10#1',
    }
    if rider_id:
        path_params['riderId'] = rider_id
    return _event(['RIDER'], path_params, method=method, body=body or {})


def test_rider_registration_is_idempotent_and_closes_when_occurrence_starts(event_engine_setup, monkeypatch):
    import dynamodb_utils
    import event_self_service
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    _store_registration_event(dynamodb_utils)
    monkeypatch.setattr(
        event_self_service,
        'resolve_active_caller_tour_rider',
        lambda event, tour_id: ({'riderId': 'R1', 'profileId': 'P001', 'tourRider': {'status': 'ACTIVE'}}, None),
    )

    first = event_self_service.register_self(_rider_event_request())
    second = event_self_service.register_self(_rider_event_request())
    first_record = json.loads(first['body'])['data']
    second_record = json.loads(second['body'])['data']

    assert first['statusCode'] == 201
    assert second['statusCode'] == 200
    assert first_record == second_record
    assert first_record['source'] == 'RIDER'
    assert first_record['registeredBy'] == 'P001'

    dynamodb_utils.get_tour_table('EventOccurrence', MOCK_TOUR_ID).update_item(
        Key={'eventId': 'EVT-REG', 'dateSeq': '2026-02-10#1'},
        UpdateExpression='SET #status = :status',
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues={':status': 'ACTIVE'},
    )
    closed = event_self_service.register_self(_rider_event_request())
    assert closed['statusCode'] == 409
    assert json.loads(closed['body'])['error']['code'] == 'REGISTRATION_CLOSED'


def test_registration_disabled_and_unregister_missing_return_contract_errors(event_engine_setup, monkeypatch):
    import dynamodb_utils
    import event_self_service
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    _store_registration_event(dynamodb_utils, registration_enabled=False)
    monkeypatch.setattr(
        event_self_service,
        'resolve_active_caller_tour_rider',
        lambda event, tour_id: ({'riderId': 'R1', 'profileId': 'P001', 'tourRider': {'status': 'ACTIVE'}}, None),
    )

    disabled = event_self_service.register_self(_rider_event_request())
    assert disabled['statusCode'] == 409
    assert json.loads(disabled['body'])['error']['code'] == 'REGISTRATION_NOT_ENABLED'

    _store_registration_event(dynamodb_utils, registration_enabled=True)
    missing = event_self_service.unregister_self(_rider_event_request(method='DELETE'))
    assert missing['statusCode'] == 404
    assert json.loads(missing['body'])['error']['code'] == 'REGISTRATION_NOT_FOUND'


def test_staff_registration_list_register_and_unregister(event_engine_setup):
    import dynamodb_utils
    import event_self_service
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    _store_registration_event(dynamodb_utils)

    staff_event = _event(
        ['ADMINISTRATOR'],
        {
            'tourId': MOCK_TOUR_ID,
            'eventId': 'EVT-REG',
            'occurrenceId': 'EVT-REG#2026-02-10#1',
            'riderId': 'R1',
        },
        method='PUT',
    )
    registered = event_self_service.staff_register(staff_event)
    listed = event_self_service.list_registrations(_event(
        ['ADMINISTRATOR'],
        {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-REG', 'occurrenceId': 'EVT-REG#2026-02-10#1'},
    ))
    unregistered = event_self_service.staff_unregister(_event(
        ['ADMINISTRATOR'],
        {
            'tourId': MOCK_TOUR_ID,
            'eventId': 'EVT-REG',
            'occurrenceId': 'EVT-REG#2026-02-10#1',
            'riderId': 'R1',
        },
        method='DELETE',
    ))

    assert registered['statusCode'] == 201
    assert json.loads(registered['body'])['data']['source'] == 'STAFF'
    list_data = json.loads(listed['body'])['data']
    assert list_data['registrationEnabled'] is True
    assert list_data['count'] == 1
    assert list_data['items'][0]['name'] == 'John Doe'
    assert unregistered['statusCode'] == 200


def test_staff_and_rider_activity_records_require_registration(event_engine_setup, monkeypatch):
    import dynamodb_utils
    import event_engine
    import event_self_service
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    _store_registration_event(dynamodb_utils, occurrence_status='ACTIVE')
    monkeypatch.setattr(
        event_self_service,
        'resolve_active_caller_tour_rider',
        lambda event, tour_id: ({'riderId': 'R1', 'profileId': 'P001', 'tourRider': {'status': 'ACTIVE'}}, None),
    )
    self_record = event_self_service.create_self_record(_rider_event_request(body={
        'activityId': 'ACT-001',
        'timestamp': '2026-02-10T06:00:00Z',
    }))
    staff_record = event_engine.create_activity_record(
        _event(
            ['ADMINISTRATOR'],
            {'tourId': MOCK_TOUR_ID, 'eventId': 'EVT-REG', 'occurrenceId': 'EVT-REG#2026-02-10#1'},
            method='POST',
            body={
                'activityId': 'ACT-001',
                'riderId': 'R1',
                'typeCode': '1',
                'method': 'QR_SCAN',
                'timestamp': '2026-02-10T06:01:00Z',
            },
        ),
    )

    for response in (self_record, staff_record):
        assert response['statusCode'] == 403
        assert json.loads(response['body'])['error']['code'] == 'RIDER_NOT_REGISTERED_FOR_EVENT'


def test_rider_self_record_create_cancel_and_occurrence_status(event_engine_setup, monkeypatch):
    import dynamodb_utils
    import event_self_service
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    _store_registration_event(dynamodb_utils, occurrence_status='ACTIVE')
    dynamodb_utils.get_tour_table('EventRegistration', MOCK_TOUR_ID).put_item(Item={
        'occurrenceId': 'EVT-REG#2026-02-10#1',
        'riderId': 'R1',
        'eventId': 'EVT-REG',
        'registeredAt': '2026-02-09T12:00:00Z',
        'registeredBy': 'P001',
        'source': 'RIDER',
    })
    identity = {'riderId': 'R1', 'profileId': 'P001', 'tourRider': {'status': 'ACTIVE'}}
    monkeypatch.setattr(
        event_self_service,
        'resolve_active_caller_tour_rider',
        lambda event, tour_id: (identity, None),
    )

    created = event_self_service.create_self_record(_rider_event_request(body={
        'activityId': 'ACT-001',
        'timestamp': '2026-02-10T06:00:00Z',
    }))
    record = json.loads(created['body'])['data']
    assert created['statusCode'] == 201
    assert record['method'] == 'SELF_SERVICE'
    assert 'typeCode' not in record
    assert record['riderId'] == 'R1'

    cancel_event = _rider_event_request(method='POST', body={}, rider_id=None)
    cancel_event['pathParameters']['recordId'] = record['recordId']
    cancelled = event_self_service.cancel_self_record(cancel_event)
    assert cancelled['statusCode'] == 200
    assert json.loads(cancelled['body'])['data']['cancelledBy'] == 'P001'

    identity['riderId'] = 'R2'
    identity['profileId'] = 'P002'
    not_owner = event_self_service.cancel_self_record(cancel_event)
    assert not_owner['statusCode'] == 403
    assert json.loads(not_owner['body'])['error']['code'] == 'NOT_OWN_RECORD'

    dynamodb_utils.get_tour_table('EventOccurrence', MOCK_TOUR_ID).update_item(
        Key={'eventId': 'EVT-REG', 'dateSeq': '2026-02-10#1'},
        UpdateExpression='SET #status = :status',
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues={':status': 'PLANNED'},
    )
    identity['riderId'] = 'R1'
    identity['profileId'] = 'P001'
    inactive = event_self_service.create_self_record(_rider_event_request(body={
        'activityId': 'ACT-001',
        'timestamp': '2026-02-10T06:05:00Z',
    }))
    assert inactive['statusCode'] == 409
    assert json.loads(inactive['body'])['error']['code'] == 'OCCURRENCE_NOT_ACTIVE'


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


def test_event_bootstrap_supports_conditional_requests(event_engine_setup):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from get_bootstrap import lambda_handler as get_bootstrap_handler

    event = _event(['ADMINISTRATOR'], {'tourId': MOCK_TOUR_ID})
    response = get_bootstrap_handler(event, None)

    assert response['statusCode'] == 200
    etag = response['headers']['ETag']
    assert etag

    conditional_event = _event(['ADMINISTRATOR'], {'tourId': MOCK_TOUR_ID})
    conditional_event['headers'] = {'if-none-match': etag}
    not_modified = get_bootstrap_handler(conditional_event, None)

    assert not_modified['statusCode'] == 304
    assert not_modified['body'] == ''


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
