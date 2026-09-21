"""Focused event engine API tests."""

import json
import os
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/events')
sys.path.insert(0, 'src/functions/hotels')
sys.path.insert(0, 'src/functions/users')


MOCK_TOUR_ID = 'TestTour-2026'


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
                'userId': 'user-1',
                'username': 'hotelstaff',
                'email': 'hotel@example.com',
                'name': 'Hotel Staff',
                'role': 'HOTEL_STAFF',
                'hotelId': 'HTL-MDU-01',
                'eventAssignments': [{'eventId': 'EVT-BAGLOAD', 'dates': 'ALL'}],
            },
        ),
        None,
    )
    assert user_response['statusCode'] == 201
