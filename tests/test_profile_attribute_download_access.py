import json
import os
import sys
from unittest.mock import patch

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
def download_fixture(aws_credentials):
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        app_config = dynamodb.create_table(
            TableName='test-app-config-table',
            KeySchema=[{'AttributeName': 'configType', 'KeyType': 'HASH'}, {'AttributeName': 'configId', 'KeyType': 'RANGE'}],
            AttributeDefinitions=[{'AttributeName': 'configType', 'AttributeType': 'S'}, {'AttributeName': 'configId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        app_config.put_item(Item={'configType': 'RIDER_PROFILE_SECTION', 'configId': 'medical', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Medical', 'order': 1}})
        app_config.put_item(Item={'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'medicalFile', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Medical File', 'sectionId': 'medical', 'order': 1, 'type': 'FILE', 'storage': {'scope': 'ATTRIBUTES'}, 'visibleToAllMgmtUsers': False, 'sensitive': True}})
        app_config.put_item(Item={'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'publicFile', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Public File', 'sectionId': 'medical', 'order': 2, 'type': 'FILE', 'storage': {'scope': 'ATTRIBUTES'}, 'visibleToAllMgmtUsers': True, 'sensitive': False}})

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
        rider.put_item(Item={'profileId': 'P001', 'attributes': {
            'medicalFile': {'s3Key': 'riders/P001/attributes/medicalFile/a.pdf', 'fileName': 'a.pdf', 'contentType': 'application/pdf', 'sizeBytes': 100, 'uploadedAt': '2026-01-01T00:00:00Z'},
            'publicFile': {'s3Key': 'riders/P001/attributes/publicFile/b.pdf', 'fileName': 'b.pdf', 'contentType': 'application/pdf', 'sizeBytes': 100, 'uploadedAt': '2026-01-01T00:00:00Z'},
        }})

        dynamodb.create_table(
            TableName='test-rider-cognito-user-table',
            KeySchema=[{'AttributeName': 'cognitoUserName', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'cognitoUserName', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        ).put_item(Item={'cognitoUserName': 'owner-sub', 'profileId': 'P001'})

        os.environ['APP_CONFIG_TABLE'] = 'test-app-config-table'
        os.environ['RIDER_PROFILE_TABLE'] = 'test-rider-table'
        os.environ['RIDER_COGNITO_USER_TABLE'] = 'test-rider-cognito-user-table'
        os.environ['PHOTOS_BUCKET'] = 'test-bucket'
        os.environ['RIDER_API_ID'] = 'rider-api-id'

        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        clear_schema_cache()
        yield


def _event(api_id, groups, key, sub='staff-sub'):
    return {
        'pathParameters': {'profileId': 'P001', 'key': key},
        'requestContext': {
            'apiId': api_id,
            'authorizer': {'jwt': {'claims': {'sub': sub, 'cognito:groups': ','.join(groups)}}},
        },
    }


@patch('download_profile_attribute_file.s3_client')
def test_staff_visibility_enforced(mock_s3, download_fixture):
    from download_profile_attribute_file import lambda_handler

    mock_s3.generate_presigned_url.return_value = 'https://example.com'

    denied = lambda_handler(_event('tour-api-id', ['GUEST'], 'medicalFile'), None)
    assert denied['statusCode'] == 403

    allowed = lambda_handler(_event('tour-api-id', ['GUEST'], 'publicFile'), None)
    assert allowed['statusCode'] == 200


@patch('download_profile_attribute_file.s3_client')
def test_owner_can_download_sensitive_attribute(mock_s3, download_fixture):
    from download_profile_attribute_file import lambda_handler

    mock_s3.generate_presigned_url.return_value = 'https://example.com'

    res = lambda_handler(_event('rider-api-id', ['RIDER'], 'medicalFile', sub='owner-sub'), None)
    assert res['statusCode'] == 200
