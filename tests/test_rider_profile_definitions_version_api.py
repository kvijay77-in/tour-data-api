import json
import os
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/riders')
os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')

import dynamodb_utils
from profile_schema import clear_schema_cache, get_definitions_version


@pytest.fixture
def aws_credentials():
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture
def version_fixture(aws_credentials):
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        app_config = dynamodb.create_table(
            TableName='test-app-config-table',
            KeySchema=[{'AttributeName': 'configType', 'KeyType': 'HASH'}, {'AttributeName': 'configId', 'KeyType': 'RANGE'}],
            AttributeDefinitions=[{'AttributeName': 'configType', 'AttributeType': 'S'}, {'AttributeName': 'configId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        app_config.put_item(Item={'configType': 'RIDER_PROFILE_SECTION', 'configId': 'personal', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Personal', 'order': 1}})
        app_config.put_item(Item={'configType': 'LOV', 'configId': 'GENDER', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Gender', 'items': [{'value': 'Male', 'label': 'Male', 'enabled': True}]}})
        app_config.put_item(Item={'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'name', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Name', 'sectionId': 'personal', 'order': 1, 'type': 'TEXT', 'storage': {'scope': 'CORE', 'path': 'name'}, 'required': True}})
        app_config.put_item(Item={'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'gender', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Gender', 'sectionId': 'personal', 'order': 2, 'type': 'SELECT', 'lovId': 'GENDER', 'storage': {'scope': 'CORE', 'path': 'gender'}, 'required': True}})

        rider = dynamodb.create_table(
            TableName='test-rider-table',
            KeySchema=[{'AttributeName': 'profileId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[
                {'AttributeName': 'profileId', 'AttributeType': 'S'},
                {'AttributeName': 'email', 'AttributeType': 'S'},
                {'AttributeName': 'personalCode', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[
                {'IndexName': 'EmailIndex', 'KeySchema': [{'AttributeName': 'email', 'KeyType': 'HASH'}], 'Projection': {'ProjectionType': 'ALL'}, 'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1}},
                {'IndexName': 'PersonalCodeIndex', 'KeySchema': [{'AttributeName': 'personalCode', 'KeyType': 'HASH'}], 'Projection': {'ProjectionType': 'ALL'}, 'ProvisionedThroughput': {'ReadCapacityUnits': 1, 'WriteCapacityUnits': 1}},
            ],
            BillingMode='PAY_PER_REQUEST',
        )
        rider.put_item(Item={'profileId': 'P001', 'name': 'Rider', 'gender': 'Male', 'email': 'rider@example.com'})

        os.environ['APP_CONFIG_TABLE'] = 'test-app-config-table'
        os.environ['RIDER_PROFILE_TABLE'] = 'test-rider-table'

        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        clear_schema_cache()
        yield


def _event(method, path, path_params=None, body=None):
    return {
        'rawPath': path,
        'routeKey': f'{method} {path}',
        'requestContext': {
            'http': {'method': method},
            'authorizer': {'jwt': {'claims': {'sub': 'test-user-123', 'email': 'test@example.com', 'cognito:groups': 'RIDER'}}},
        },
        'pathParameters': path_params or {},
        'body': json.dumps(body) if body is not None else None,
    }


def test_create_profile_stale_definitions_version_returns_409(version_fixture):
    from create_rider_profile import lambda_handler

    response = lambda_handler(_event('POST', '/v1/riders/profile', body={'name': 'N', 'gender': 'Male', 'definitionsVersion': 'stale'}), None)
    assert response['statusCode'] == 409
    assert json.loads(response['body'])['error']['code'] == 'PROFILE_DEFINITIONS_CHANGED'


def test_update_profile_stale_definitions_version_returns_409(version_fixture):
    from update_rider_profile import lambda_handler

    current_version = get_definitions_version()
    response_ok = lambda_handler(_event('PUT', '/v1/riders/profile/P001', path_params={'profileId': 'P001'}, body={'name': 'Updated', 'gender': 'Male', 'definitionsVersion': current_version}), None)
    assert response_ok['statusCode'] == 200

    response = lambda_handler(_event('PUT', '/v1/riders/profile/P001', path_params={'profileId': 'P001'}, body={'name': 'Again', 'gender': 'Male', 'definitionsVersion': 'stale'}), None)
    assert response['statusCode'] == 409
    assert json.loads(response['body'])['error']['code'] == 'PROFILE_DEFINITIONS_CHANGED'
