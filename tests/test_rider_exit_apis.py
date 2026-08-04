"""Unit tests for rider exit and cancel-exit APIs."""

import os
import json
import boto3
import pytest
from moto import mock_aws


# Set up path for imports
import sys
sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/riders')

from models import TourRiderStatus


MOCK_TOUR_ID = 'TestTour-2026'


@pytest.fixture
def aws_credentials():
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture
def rider_exit_dynamodb_mock(aws_credentials):
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        tour_rider_table = dynamodb.create_table(
            TableName=f'test-stack-TourRider-{MOCK_TOUR_ID}',
            KeySchema=[
                {'AttributeName': 'riderId', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'riderId', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )

        tour_rider_table.put_item(Item={
            'riderId': 'R1',
            'profileId': 'P001',
            'status': TourRiderStatus.ACTIVE.value,
            'registeredAt': '2026-01-15T00:00:00Z',
            'createdAt': '2026-01-15T00:00:00Z',
            'updatedAt': '2026-01-15T00:00:00Z'
        })

        os.environ['STACK_NAME'] = 'test-stack'
        os.environ['LOG_LEVEL'] = 'INFO'

        yield dynamodb


def _make_event(path, groups, rider_id='R1', sub='test-user-123'):
    return {
        'version': '2.0',
        'routeKey': f'POST {path}',
        'rawPath': path,
        'headers': {},
        'requestContext': {
            'http': {'method': 'POST'},
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': sub,
                        'cognito:groups': ','.join(groups),
                    }
                }
            }
        },
        'pathParameters': {
            'tourId': MOCK_TOUR_ID,
            'riderId': rider_id,
        }
    }


class TestRiderExitApis:
    def test_exit_allowed_for_admin(self, rider_exit_dynamodb_mock):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from exit_tour_rider import lambda_handler

        event = _make_event(
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders/R1/exit',
            groups=['ADMINISTRATOR'],
            sub='admin-sub-1'
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200

        body = json.loads(response['body'])
        data = body['data']
        assert data['status'] == TourRiderStatus.EXITED.value
        assert data['prevStatus'] == TourRiderStatus.ACTIVE.value
        assert data['exitedBy'] == 'admin-sub-1'
        assert 'exitedAt' in data

    def test_exit_forbidden_for_rider(self, rider_exit_dynamodb_mock):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from exit_tour_rider import lambda_handler

        event = _make_event(
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders/R1/exit',
            groups=['RIDER']
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 403

    def test_cancel_allowed_for_super_user(self, rider_exit_dynamodb_mock):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from exit_tour_rider import lambda_handler as exit_handler
        from cancel_rider_exit import lambda_handler as cancel_handler

        exit_event = _make_event(
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders/R1/exit',
            groups=['ADMINISTRATOR'],
            sub='admin-sub-1'
        )
        first = exit_handler(exit_event, None)
        assert first['statusCode'] == 200

        cancel_event = _make_event(
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders/R1/exit/cancel',
            groups=['SUPER_USER'],
            sub='super-sub-1'
        )

        response = cancel_handler(cancel_event, None)
        assert response['statusCode'] == 200

        body = json.loads(response['body'])
        data = body['data']
        assert data['status'] == TourRiderStatus.ACTIVE.value
        assert 'prevStatus' not in data
        assert 'exitedAt' not in data
        assert 'exitedBy' not in data

    def test_cancel_forbidden_for_guest(self, rider_exit_dynamodb_mock):
        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        from cancel_rider_exit import lambda_handler

        event = _make_event(
            path=f'/v1/tours/{MOCK_TOUR_ID}/riders/R1/exit/cancel',
            groups=['GUEST']
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 403
