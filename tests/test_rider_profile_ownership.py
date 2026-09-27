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
from profile_schema import clear_schema_cache


@pytest.fixture
def aws_credentials():
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture
def ownership_fixture(aws_credentials):
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        rider_profile = dynamodb.create_table(
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
        rider_profile.put_item(Item={'profileId': 'P001', 'name': 'Rider', 'email': 'rider@example.com'})

        dynamodb.create_table(
            TableName='test-rider-cognito-user-table',
            KeySchema=[{'AttributeName': 'cognitoUserName', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'cognitoUserName', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        ).put_item(Item={'cognitoUserName': 'test-user-123', 'profileId': 'P001'})

        dynamodb.create_table(
            TableName='test-rider-tours-table',
            KeySchema=[{'AttributeName': 'profileId', 'KeyType': 'HASH'}, {'AttributeName': 'tourId', 'KeyType': 'RANGE'}],
            AttributeDefinitions=[{'AttributeName': 'profileId', 'AttributeType': 'S'}, {'AttributeName': 'tourId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        ).put_item(Item={'profileId': 'P001', 'tourId': 'TOT-2026', 'status': 'CONFIRMED'})

        app_config = dynamodb.create_table(
            TableName='test-app-config-table',
            KeySchema=[{'AttributeName': 'configType', 'KeyType': 'HASH'}, {'AttributeName': 'configId', 'KeyType': 'RANGE'}],
            AttributeDefinitions=[{'AttributeName': 'configType', 'AttributeType': 'S'}, {'AttributeName': 'configId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        app_config.put_item(Item={'configType': 'RIDER_PROFILE_SECTION', 'configId': 'personal', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Personal', 'order': 1}})
        app_config.put_item(Item={'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'name', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Name', 'sectionId': 'personal', 'order': 1, 'type': 'TEXT', 'storage': {'scope': 'CORE', 'path': 'name'}}})

        os.environ['RIDER_PROFILE_TABLE'] = 'test-rider-table'
        os.environ['RIDER_COGNITO_USER_TABLE'] = 'test-rider-cognito-user-table'
        os.environ['RIDER_TOURS_TABLE'] = 'test-rider-tours-table'
        os.environ['APP_CONFIG_TABLE'] = 'test-app-config-table'
        os.environ['RIDER_API_ID'] = 'rider-api-id'
        os.environ['FORCE_RIDER_API_OWNERSHIP'] = 'true'

        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        clear_schema_cache()
        yield
        os.environ.pop('RIDER_API_ID', None)
        os.environ.pop('FORCE_RIDER_API_OWNERSHIP', None)


def _event(path, method='GET', path_params=None, body=None, sub='test-user-123'):
    return {
        'rawPath': path,
        'routeKey': f'{method} {path}',
        'requestContext': {
            'apiId': 'rider-api-id',
            'http': {'method': method},
            'authorizer': {'jwt': {'claims': {'sub': sub, 'cognito:groups': 'RIDER'}}},
        },
        'pathParameters': path_params or {},
        'body': json.dumps(body) if body is not None else None,
    }


def test_get_rider_profile_denied_for_other_profile(ownership_fixture):
    from get_rider_profile import lambda_handler

    response = lambda_handler(_event('/v1/riders/profile/P999', path_params={'profileId': 'P999'}), None)
    assert response['statusCode'] == 403
    assert json.loads(response['body'])['error']['code'] == 'PROFILE_ACCESS_DENIED'


def test_get_rider_tours_denied_for_other_profile(ownership_fixture):
    from get_rider_tours import lambda_handler

    response = lambda_handler(_event('/v1/profile/P999/tours', path_params={'profileId': 'P999'}), None)
    assert response['statusCode'] == 403
    assert json.loads(response['body'])['error']['code'] == 'PROFILE_ACCESS_DENIED'


def test_link_route_subject_must_match_sub(ownership_fixture):
    from link_rider_cognito_user import lambda_handler

    response = lambda_handler(_event('/v1/riders/link/another-user', method='GET', path_params={'cognitoUserName': 'another-user'}), None)
    assert response['statusCode'] == 403
    assert json.loads(response['body'])['error']['code'] == 'PROFILE_ACCESS_DENIED'
