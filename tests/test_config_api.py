"""Unit tests for GET /v1/config Lambda function."""

import json
import os
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/config')


@pytest.fixture
def aws_credentials():
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture
def app_config_mock(aws_credentials):
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

        table.put_item(Item={
            'configType': 'ID_CODE_FORMAT',
            'configId': 'SUBSTRING',
            'enabled': True,
            'version': 1,
            'updatedAt': '2026-08-01T00:00:00Z',
            'updatedBy': 'seed',
            'config': {
                'method': 'SUBSTRING',
                'idCode': {'startPosition': 12, 'length': 5},
                'idCodeType': {'startPosition': 1, 'length': 1},
                'personalCode': {'startPosition': 2, 'length': 4},
            },
        })

        table.put_item(Item={
            'configType': 'ID_CODE_FORMAT',
            'configId': 'REGEX',
            'enabled': False,
            'version': 1,
            'updatedAt': '2026-08-01T00:00:00Z',
            'updatedBy': 'seed',
            'config': {'method': 'REGEX'},
        })

        table.put_item(Item={
            'configType': 'ID_CODE_TYPE',
            'configId': '1',
            'enabled': True,
            'version': 1,
            'updatedAt': '2026-08-01T00:00:00Z',
            'updatedBy': 'seed',
            'config': {'code': '1', 'type': 'RIDER', 'name': 'Personal'},
        })

        table.put_item(Item={
            'configType': 'ID_CODE_TYPE',
            'configId': '0',
            'enabled': False,
            'version': 1,
            'updatedAt': '2026-08-01T00:00:00Z',
            'updatedBy': 'seed',
            'config': {'code': '0', 'type': None, 'name': 'Blank'},
        })

        table.put_item(Item={
            'configType': 'ARTIFACTS',
            'configId': 'ride-plan',
            'enabled': True,
            'version': 1,
            'updatedAt': '2026-08-01T00:00:00Z',
            'updatedBy': 'seed',
            'config': {'category': 'tour'},
        })

        table.put_item(Item={
            'configType': 'ARTIFACTS',
            'configId': 'ride-elevation',
            'enabled': True,
            'version': 1,
            'updatedAt': '2026-08-01T00:00:00Z',
            'updatedBy': 'seed',
            'config': {'category': 'ride'},
        })

        os.environ['APP_CONFIG_TABLE'] = 'test-app-config-table'
        os.environ['LOG_LEVEL'] = 'INFO'

        yield


def _event(query=None, headers=None, groups=None):
    return {
        'version': '2.0',
        'routeKey': 'GET /v1/config',
        'rawPath': '/v1/config',
        'headers': headers or {},
        'queryStringParameters': query,
        'requestContext': {
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': 'test-user',
                        'cognito:groups': ','.join(groups or ['GUEST']),
                    }
                }
            }
        }
    }


def test_get_config_default_returns_all_enabled(app_config_mock):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from get_config import lambda_handler

    response = lambda_handler(_event(), None)
    assert response['statusCode'] == 200

    body = json.loads(response['body'])
    items = body['data']['items']
    assert len(items) == 4
    assert all(item['enabled'] is True for item in items)


def test_get_config_all_alias_returns_all_enabled(app_config_mock):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from get_config import lambda_handler

    response = lambda_handler(_event(query={'configType': 'ALL'}), None)
    assert response['statusCode'] == 200

    body = json.loads(response['body'])
    assert len(body['data']['items']) == 4


def test_get_config_single_type(app_config_mock):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from get_config import lambda_handler

    response = lambda_handler(_event(query={'configType': 'ID_CODE_FORMAT'}), None)
    assert response['statusCode'] == 200

    body = json.loads(response['body'])
    items = body['data']['items']
    assert len(items) == 1
    assert items[0]['configType'] == 'ID_CODE_FORMAT'
    assert items[0]['configId'] == 'SUBSTRING'


def test_get_config_multiple_types(app_config_mock):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from get_config import lambda_handler

    response = lambda_handler(_event(query={'configType': 'ID_CODE_FORMAT,ID_CODE_TYPE'}), None)
    assert response['statusCode'] == 200

    body = json.loads(response['body'])
    items = body['data']['items']
    assert len(items) == 2
    assert {item['configType'] for item in items} == {'ID_CODE_FORMAT', 'ID_CODE_TYPE'}


def test_get_config_artifacts_type(app_config_mock):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from get_config import lambda_handler

    response = lambda_handler(_event(query={'configType': 'ARTIFACTS'}), None)
    assert response['statusCode'] == 200

    body = json.loads(response['body'])
    items = body['data']['items']
    assert len(items) == 2
    assert {item['configId'] for item in items} == {'ride-plan', 'ride-elevation'}
    assert {item['config']["category"] for item in items} == {'tour', 'ride'}


def test_get_config_unknown_type_returns_404(app_config_mock):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from get_config import lambda_handler

    response = lambda_handler(_event(query={'configType': 'UNKNOWN'}), None)
    assert response['statusCode'] == 404

    body = json.loads(response['body'])
    assert body['error']['code'] == 'INVALID_CONFIG_TYPE'
    assert body['error']['message'] == 'Missing or Invalid configType'


def test_get_config_any_type_returned(app_config_mock):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    dynamodb_utils.dynamodb.Table('test-app-config-table').put_item(Item={
        'configType': 'HOTEL_UPLOAD',
        'configId': 'PROCESSING',
        'enabled': True,
        'config': {'maxDataRows': 500},
    })

    from get_config import lambda_handler

    response = lambda_handler(_event(query={'configType': 'hotel_upload'}), None)
    assert response['statusCode'] == 200

    items = json.loads(response['body'])['data']['items']
    assert [(i['configType'], i['configId']) for i in items] == [('HOTEL_UPLOAD', 'PROCESSING')]


def test_get_config_multiple_types_partial_match(app_config_mock):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from get_config import lambda_handler

    response = lambda_handler(_event(query={'configType': 'ID_CODE_FORMAT,UNKNOWN'}), None)
    assert response['statusCode'] == 200
    assert len(json.loads(response['body'])['data']['items']) == 1


def test_get_config_all_combined_rejected(app_config_mock):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from get_config import lambda_handler

    response = lambda_handler(_event(query={'configType': 'ALL,ID_CODE_TYPE'}), None)
    assert response['statusCode'] == 400
    assert json.loads(response['body'])['error']['code'] == 'BAD_REQUEST'


def test_get_config_etag_not_modified(app_config_mock):
    import dynamodb_utils
    dynamodb_utils.TABLES = {}
    dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    from get_config import lambda_handler

    first_response = lambda_handler(_event(), None)
    assert first_response['statusCode'] == 200
    etag = first_response['headers']['ETag']

    second_response = lambda_handler(_event(headers={'If-None-Match': etag}), None)
    assert second_response['statusCode'] == 304
    assert second_response['headers']['ETag'] == etag
