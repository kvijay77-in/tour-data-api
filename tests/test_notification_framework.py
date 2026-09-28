import json
import os
import sys
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')
os.environ.setdefault('AWS_ACCESS_KEY_ID', 'testing')
os.environ.setdefault('AWS_SECRET_ACCESS_KEY', 'testing')
os.environ.setdefault('AWS_SESSION_TOKEN', 'testing')

sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/notifications')

from notification_service import notify
import register_device
import delete_device
import get_notifications
import get_unread_count
import mark_read
import create_rule
import update_rule
import push_sender


@pytest.fixture
def notification_env():
    env = {
        'AWS_ACCESS_KEY_ID': 'testing',
        'AWS_SECRET_ACCESS_KEY': 'testing',
        'AWS_SESSION_TOKEN': 'testing',
        'AWS_DEFAULT_REGION': 'us-east-1',
        'STACK_NAME': 'test-stack',
        'NOTIFICATION_RULE_TABLE': 'test-stack-NotificationRule',
        'RIDER_NOTIFICATION_TABLE': 'test-stack-RiderNotification',
        'MGMT_NOTIFICATION_TABLE': 'test-stack-MgmtNotification',
        'RIDER_PUSH_DEVICE_TABLE': 'test-stack-RiderPushDevice',
        'MGMT_PUSH_DEVICE_TABLE': 'test-stack-MgmtPushDevice',
        'RIDER_COGNITO_USER_TABLE': 'test-stack-RiderCognitoUser',
        'RIDER_TOURS_TABLE': 'test-stack-RiderTours',
        'TOUR_MASTER_TABLE': 'test-stack-TourMaster',
        'EXPO_TOKEN_PARAM_RIDER': '/test/push/rider',
        'EXPO_TOKEN_PARAM_MGMT': '/test/push/mgmt',
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    yield
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def ddb(notification_env):
    with mock_aws():
        ddb = boto3.resource('dynamodb', region_name='us-east-1')

        ddb.create_table(
            TableName=os.environ['NOTIFICATION_RULE_TABLE'],
            KeySchema=[{'AttributeName': 'ruleId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'ruleId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )

        for name in ('RIDER_NOTIFICATION_TABLE', 'MGMT_NOTIFICATION_TABLE'):
            ddb.create_table(
                TableName=os.environ[name],
                KeySchema=[{'AttributeName': 'audience', 'KeyType': 'HASH'}, {'AttributeName': 'sk', 'KeyType': 'RANGE'}],
                AttributeDefinitions=[{'AttributeName': 'audience', 'AttributeType': 'S'}, {'AttributeName': 'sk', 'AttributeType': 'S'}],
                BillingMode='PAY_PER_REQUEST',
            )

        ddb.create_table(
            TableName=os.environ['RIDER_PUSH_DEVICE_TABLE'],
            KeySchema=[{'AttributeName': 'profileId', 'KeyType': 'HASH'}, {'AttributeName': 'token', 'KeyType': 'RANGE'}],
            AttributeDefinitions=[{'AttributeName': 'profileId', 'AttributeType': 'S'}, {'AttributeName': 'token', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        ddb.create_table(
            TableName=os.environ['MGMT_PUSH_DEVICE_TABLE'],
            KeySchema=[{'AttributeName': 'cognitoSub', 'KeyType': 'HASH'}, {'AttributeName': 'token', 'KeyType': 'RANGE'}],
            AttributeDefinitions=[
                {'AttributeName': 'cognitoSub', 'AttributeType': 'S'},
                {'AttributeName': 'token', 'AttributeType': 'S'},
                {'AttributeName': 'groupKey', 'AttributeType': 'S'},
                {'AttributeName': 'updatedAt', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'GroupKeyIndex',
                    'KeySchema': [
                        {'AttributeName': 'groupKey', 'KeyType': 'HASH'},
                        {'AttributeName': 'updatedAt', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1},
                }
            ],
            BillingMode='PAY_PER_REQUEST',
        )

        ddb.create_table(
            TableName=os.environ['RIDER_COGNITO_USER_TABLE'],
            KeySchema=[{'AttributeName': 'cognitoUserName', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'cognitoUserName', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )

        ddb.create_table(
            TableName=os.environ['RIDER_TOURS_TABLE'],
            KeySchema=[{'AttributeName': 'profileId', 'KeyType': 'HASH'}, {'AttributeName': 'tourId', 'KeyType': 'RANGE'}],
            AttributeDefinitions=[
                {'AttributeName': 'profileId', 'AttributeType': 'S'},
                {'AttributeName': 'tourId', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'TourStatusIndex',
                    'KeySchema': [
                        {'AttributeName': 'tourId', 'KeyType': 'HASH'},
                        {'AttributeName': 'status', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1},
                }
            ],
            BillingMode='PAY_PER_REQUEST',
        )

        ddb.create_table(
            TableName=os.environ['TOUR_MASTER_TABLE'],
            KeySchema=[{'AttributeName': 'tourId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'tourId', 'AttributeType': 'S'}, {'AttributeName': 'status', 'AttributeType': 'S'}],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'StatusIndex',
                    'KeySchema': [{'AttributeName': 'status', 'KeyType': 'HASH'}],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1},
                }
            ],
            BillingMode='PAY_PER_REQUEST',
        )

        ddb.create_table(
            TableName='test-stack-TourRider-TOT-2026',
            KeySchema=[{'AttributeName': 'riderId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'riderId', 'AttributeType': 'S'}, {'AttributeName': 'profileId', 'AttributeType': 'S'}],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'ProfileIdIndex',
                    'KeySchema': [{'AttributeName': 'profileId', 'KeyType': 'HASH'}],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1},
                }
            ],
            BillingMode='PAY_PER_REQUEST',
        )

        ddb.create_table(
            TableName='test-stack-Notification-TOT-2026',
            KeySchema=[{'AttributeName': 'audience', 'KeyType': 'HASH'}, {'AttributeName': 'sk', 'KeyType': 'RANGE'}],
            AttributeDefinitions=[{'AttributeName': 'audience', 'AttributeType': 'S'}, {'AttributeName': 'sk', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )

        yield ddb


def _rider_event(body=None, username='rider-user', sub='rider-sub'):
    return {
        'body': json.dumps(body or {}),
        'requestContext': {
            'authorizer': {
                'jwt': {
                    'claims': {
                        'cognito:username': username,
                        'sub': sub,
                        'cognito:groups': 'RIDER',
                    }
                }
            }
        },
        'queryStringParameters': None,
        'pathParameters': {},
    }


def _mgmt_event(body=None, groups='ADMINISTRATOR', sub='mgmt-sub'):
    return {
        'body': json.dumps(body or {}),
        'requestContext': {
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': sub,
                        'cognito:groups': groups,
                    }
                }
            }
        },
        'queryStringParameters': None,
        'pathParameters': {},
    }


def test_notify_routes_and_converts_tour_rider(ddb):
    ddb.Table(os.environ['NOTIFICATION_RULE_TABLE']).put_item(Item={
        'ruleId': 'ANNOUNCEMENT',
        'enabled': True,
        'category': 'ANNOUNCEMENT',
        'audiences': ['ALL', 'TOUR#TOT-2026#RIDER#R1'],
        'titleTemplate': '{title}',
        'bodyTemplate': '{message}',
        'push': True,
        'priority': 'NORMAL',
        'androidChannel': 'general',
        'target': {'screen': 'Notifications', 'paramKeys': []},
        'ttlHours': 24,
        'allowOverride': True,
    })
    ddb.Table('test-stack-TourRider-TOT-2026').put_item(Item={'riderId': 'R1', 'profileId': 'P001'})

    notification_id = notify('ANNOUNCEMENT', tour_id='TOT-2026', context={'title': 'T', 'message': 'M'})
    assert notification_id

    rider_rows = ddb.Table(os.environ['RIDER_NOTIFICATION_TABLE']).scan()['Items']
    mgmt_rows = ddb.Table(os.environ['MGMT_NOTIFICATION_TABLE']).scan()['Items']
    audiences = {row['audience'] for row in rider_rows}
    assert 'APP#RIDER' in audiences
    assert 'PROFILE#P001' in audiences
    assert any(row['audience'] == 'APP#MGMT' for row in mgmt_rows)


def test_notify_never_raises_for_invalid_rule(ddb):
    ddb.Table(os.environ['NOTIFICATION_RULE_TABLE']).put_item(Item={
        'ruleId': 'BROKEN',
        'enabled': True,
        'category': 'SYSTEM',
        'audiences': ['NOT_VALID'],
        'titleTemplate': 'x',
        'bodyTemplate': 'y',
        'push': False,
        'priority': 'NORMAL',
        'androidChannel': 'general',
        'target': {'screen': 'Notifications', 'paramKeys': []},
        'ttlHours': 24,
        'allowOverride': False,
    })
    assert notify('BROKEN') is None


def test_device_register_move_and_delete(ddb):
    map_table = ddb.Table(os.environ['RIDER_COGNITO_USER_TABLE'])
    map_table.put_item(Item={'cognitoUserName': 'rider-1', 'profileId': 'P001'})
    map_table.put_item(Item={'cognitoUserName': 'rider-2', 'profileId': 'P002'})

    os.environ['NOTIFICATION_SCOPE'] = 'rider'
    register_device.lambda_handler(_rider_event({'token': 'ExponentPushToken[x]', 'platform': 'ios'}, username='rider-1'), None)
    register_device.lambda_handler(_rider_event({'token': 'ExponentPushToken[x]', 'platform': 'ios'}, username='rider-2'), None)

    rows = ddb.Table(os.environ['RIDER_PUSH_DEVICE_TABLE']).scan()['Items']
    assert len(rows) == 1
    assert rows[0]['profileId'] == 'P002'

    evt = _rider_event(username='rider-2')
    evt['pathParameters'] = {'token': 'ExponentPushToken[x]'}
    resp = delete_device.lambda_handler(evt, None)
    assert resp['statusCode'] == 204
    assert ddb.Table(os.environ['RIDER_PUSH_DEVICE_TABLE']).scan()['Items'] == []


def test_inbox_list_and_mark_read(ddb):
    map_table = ddb.Table(os.environ['RIDER_COGNITO_USER_TABLE'])
    map_table.put_item(Item={'cognitoUserName': 'rider-user', 'profileId': 'P001'})
    ddb.Table(os.environ['RIDER_TOURS_TABLE']).put_item(Item={'profileId': 'P001', 'tourId': 'TOT-2026', 'status': 'REGISTERED', 'riderId': 'R1'})

    table = ddb.Table(os.environ['RIDER_NOTIFICATION_TABLE'])
    table.put_item(Item={
        'audience': 'APP#RIDER',
        'sk': '2026-02-11T06:00:00Z#n1',
        'notificationId': 'n1',
        'ruleId': 'RIDE_OPENED',
        'title': 'A',
        'body': 'B',
        'createdAt': '2026-02-11T06:00:00Z',
        'push': False,
    })

    os.environ['NOTIFICATION_SCOPE'] = 'rider'
    list_resp = get_notifications.lambda_handler(_rider_event(), None)
    body = json.loads(list_resp['body'])['data']
    assert body['unreadCount'] == 1

    mark_read.lambda_handler(_rider_event({'readAt': '2026-02-11T07:00:00Z'}), None)
    unread_resp = get_unread_count.lambda_handler(_rider_event(), None)
    assert json.loads(unread_resp['body'])['data']['unreadCount'] == 0


def test_rule_crud_validation_and_version_increment(ddb):
    os.environ['NOTIFICATION_SCOPE'] = 'mgmt'

    bad = create_rule.lambda_handler(_mgmt_event({'ruleId': 'X', 'enabled': True, 'category': 'BAD'}), None)
    assert bad['statusCode'] == 400

    good_payload = {
        'ruleId': 'ANNOUNCEMENT',
        'enabled': True,
        'category': 'ANNOUNCEMENT',
        'audiences': ['ALL'],
        'titleTemplate': '{title}',
        'bodyTemplate': '{message}',
        'push': True,
        'priority': 'NORMAL',
        'androidChannel': 'general',
        'target': {'screen': 'Notifications', 'paramKeys': []},
        'ttlHours': 24,
        'allowOverride': True,
    }
    created = create_rule.lambda_handler(_mgmt_event(good_payload), None)
    assert created['statusCode'] == 201

    updated = update_rule.lambda_handler({**_mgmt_event(good_payload), 'pathParameters': {'ruleId': 'ANNOUNCEMENT'}}, None)
    assert updated['statusCode'] == 200
    assert json.loads(updated['body'])['data']['version'] == 2


def test_push_sender_deletes_device_not_registered_token(ddb):
    ddb.Table(os.environ['RIDER_PUSH_DEVICE_TABLE']).put_item(Item={'profileId': 'P001', 'token': 'ExponentPushToken[x]'})

    event = {
        'Records': [
            {
                'eventName': 'INSERT',
                'dynamodb': {
                    'NewImage': {
                        'audience': {'S': 'PROFILE#P001'},
                        'sk': {'S': '2026-02-11T06:00:00Z#n1'},
                        'notificationId': {'S': 'n1'},
                        'title': {'S': 'A'},
                        'body': {'S': 'B'},
                        'push': {'BOOL': True},
                        'androidChannel': {'S': 'general'},
                        'priority': {'S': 'NORMAL'},
                    }
                }
            }
        ]
    }

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({'data': [{'status': 'error', 'details': {'error': 'DeviceNotRegistered'}}]}).encode('utf-8')

    with patch.object(push_sender, '_get_ssm_parameter', return_value='token'), patch('urllib.request.urlopen', return_value=_Resp()):
        push_sender.lambda_handler(event, None)

    assert ddb.Table(os.environ['RIDER_PUSH_DEVICE_TABLE']).scan()['Items'] == []
