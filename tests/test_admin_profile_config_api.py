import json
import os
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/config')
os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')

import dynamodb_utils
from profile_schema import clear_schema_cache


@pytest.fixture
def aws_credentials():
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture
def config_table(aws_credentials):
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamodb.create_table(
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
        )

        table.put_item(Item={'configType': 'RIDER_PROFILE_SECTION', 'configId': 'personal', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'updatedBy': 'seed', 'config': {'label': 'Personal', 'order': 1}})
        table.put_item(Item={'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'name', 'enabled': True, 'version': 2, 'updatedAt': '2026-01-01T00:00:00Z', 'updatedBy': 'seed', 'config': {'label': 'Name', 'sectionId': 'personal', 'order': 1, 'type': 'TEXT', 'storage': {'scope': 'CORE', 'path': 'name'}, 'system': True}})

        os.environ['APP_CONFIG_TABLE'] = 'test-app-config-table'
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        clear_schema_cache()
        yield


def _event(method, path, path_params, body=None, groups=None):
    return {
        'requestContext': {
            'http': {'method': method},
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': 'admin-sub',
                        'cognito:groups': ','.join(groups or ['ADMINISTRATOR']),
                    }
                }
            }
        },
        'pathParameters': path_params,
        'body': json.dumps(body) if body is not None else None,
        'rawPath': path,
    }


def test_get_admin_config_includes_disabled(config_table):
    from get_admin_config import lambda_handler

    boto3.resource('dynamodb', region_name='us-east-1').Table('test-app-config-table').put_item(
        Item={'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'oldField', 'enabled': False, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'updatedBy': 'seed', 'config': {'label': 'Old', 'sectionId': 'personal', 'order': 99, 'type': 'TEXT', 'storage': {'scope': 'ATTRIBUTES'}}}
    )

    res = lambda_handler(_event('GET', '/v1/admin/config/RIDER_PROFILE_ATTRIBUTE', {'configType': 'RIDER_PROFILE_ATTRIBUTE'}), None)
    assert res['statusCode'] == 200
    items = json.loads(res['body'])['data']['items']
    assert any(item['configId'] == 'oldField' and item['enabled'] is False for item in items)


def test_put_admin_config_version_conflict(config_table):
    from put_admin_config import lambda_handler

    body = {
        'version': 1,
        'enabled': True,
        'config': {
            'label': 'Name',
            'sectionId': 'personal',
            'order': 1,
            'type': 'TEXT',
            'storage': {'scope': 'CORE', 'path': 'name'},
            'system': True,
        },
    }
    res = lambda_handler(_event('PUT', '/v1/admin/config/RIDER_PROFILE_ATTRIBUTE/name', {'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'name'}, body=body), None)
    assert res['statusCode'] == 409
    assert json.loads(res['body'])['error']['code'] == 'CONFIG_VERSION_CONFLICT'


def test_put_admin_config_system_attribute_protected(config_table):
    from put_admin_config import lambda_handler

    body = {
        'version': 2,
        'enabled': False,
        'config': {
            'label': 'Name',
            'sectionId': 'personal',
            'order': 1,
            'type': 'TEXT',
            'storage': {'scope': 'CORE', 'path': 'name'},
            'system': True,
        },
    }
    res = lambda_handler(_event('PUT', '/v1/admin/config/RIDER_PROFILE_ATTRIBUTE/name', {'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'name'}, body=body), None)
    assert res['statusCode'] == 422
    assert json.loads(res['body'])['error']['code'] == 'SYSTEM_ATTRIBUTE_PROTECTED'


def test_put_admin_config_creates_attribute(config_table):
    from put_admin_config import lambda_handler

    body = {
        'version': 0,
        'enabled': True,
        'description': 'Dietary preference',
        'config': {
            'label': 'Dietary',
            'sectionId': 'personal',
            'order': 2,
            'type': 'TEXT',
            'storage': {'scope': 'ATTRIBUTES'},
        },
    }
    res = lambda_handler(_event('PUT', '/v1/admin/config/RIDER_PROFILE_ATTRIBUTE/dietaryPreference', {'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'dietaryPreference'}, body=body), None)
    assert res['statusCode'] == 200
    data = json.loads(res['body'])['data']
    assert data['configId'] == 'dietaryPreference'
    assert data['version'] == 1
