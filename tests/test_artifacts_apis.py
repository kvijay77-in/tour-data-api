import json
import os
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

import sys
sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/artifacts')


@pytest.fixture
def artifact_environment():
    os.environ['TOUR_MASTER_TABLE'] = 'test-tour-master-table'
    os.environ['APP_CONFIG_TABLE'] = 'test-app-config-table'
    os.environ['ARTIFACTS_BUCKET'] = 'test-artifacts-bucket'
    os.environ['STACK_NAME'] = 'test-stack'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

    yield

    for key in ['TOUR_MASTER_TABLE', 'APP_CONFIG_TABLE', 'ARTIFACTS_BUCKET', 'STACK_NAME']:
        os.environ.pop(key, None)


@pytest.fixture
def artifact_tables(artifact_environment):
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        tour_table = dynamodb.create_table(
            TableName='test-tour-master-table',
            KeySchema=[{'AttributeName': 'tourId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'tourId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        tour_table.put_item(Item={'tourId': 'TOT-2026', 'name': 'Tour 2026', 'status': 'ACTIVE'})

        app_table = dynamodb.create_table(
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
        app_table.put_item(Item={
            'configType': 'ARTIFACTS',
            'configId': 'ride-plan',
            'enabled': True,
            'config': {'category': 'tour'},
            'description': 'Ride plan'
        })
        app_table.put_item(Item={
            'configType': 'ARTIFACTS',
            'configId': 'gpx-file',
            'enabled': True,
            'config': {'category': 'ride'},
            'description': 'GPX file'
        })

        ride_table = dynamodb.create_table(
            TableName='test-stack-Ride-TOT-2026',
            KeySchema=[{'AttributeName': 'rideId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'rideId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        ride_table.put_item(Item={'rideId': 'RIDE001', 'date': '2026-02-10'})

        artifacts_table = dynamodb.create_table(
            TableName='test-stack-Artifacts-TOT-2026',
            KeySchema=[
                {'AttributeName': 'artifactFor', 'KeyType': 'HASH'},
                {'AttributeName': 'artifactId', 'KeyType': 'RANGE'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'artifactFor', 'AttributeType': 'S'},
                {'AttributeName': 'artifactId', 'AttributeType': 'S'},
            ],
            BillingMode='PAY_PER_REQUEST',
        )

        yield {"dynamodb": dynamodb, "artifacts_table": artifacts_table}


def _event(method, path, body=None, path_params=None, query_params=None, groups=None):
    return {
        'httpMethod': method,
        'path': path,
        'pathParameters': path_params or {},
        'queryStringParameters': query_params or {},
        'body': json.dumps(body) if body is not None else None,
        'requestContext': {
            'authorizer': {'jwt': {'claims': {'cognito:groups': groups or ['ADMINISTRATOR']}}}
        },
    }


class TestArtifactUploadApis:
    @patch('presign_tour_artifact_upload.s3_client')
    def test_presign_tour_artifact_upload_success(self, mock_s3, artifact_tables):
        from presign_tour_artifact_upload import lambda_handler

        mock_s3.generate_presigned_url.return_value = 'https://s3.example.com/presign-tour'

        event = _event(
            'POST',
            '/artifacts/tour/presign-upload',
            body={'tourId': 'TOT-2026', 'artifactId': 'ride-plan', 'contentType': 'application/pdf'},
            path_params={},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        payload = json.loads(response['body'])
        assert payload['success'] is True
        assert payload['data']['artifactFor'] == 'TOT-2026'
        assert payload['data']['artifactId'] == 'ride-plan'
        assert payload['data']['uploadUrl'] == 'https://s3.example.com/presign-tour'

    @patch('presign_ride_artifact_upload.s3_client')
    def test_presign_ride_artifact_upload_success(self, mock_s3, artifact_tables):
        from presign_ride_artifact_upload import lambda_handler

        mock_s3.generate_presigned_url.return_value = 'https://s3.example.com/presign-ride'

        event = _event(
            'POST',
            '/artifacts/ride/presign-upload',
            body={'tourId': 'TOT-2026', 'rideId': 'RIDE001', 'artifactId': 'gpx-file', 'contentType': 'application/gpx+xml'},
            path_params={},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        payload = json.loads(response['body'])
        assert payload['success'] is True
        assert payload['data']['artifactFor'] == 'TOT-2026#RIDE001'
        assert payload['data']['artifactId'] == 'gpx-file'
        assert payload['data']['uploadUrl'] == 'https://s3.example.com/presign-ride'

    @patch('presign_tour_artifact_upload.s3_client')
    def test_presign_tour_artifact_upload_validation_failure(self, mock_s3, artifact_tables):
        from presign_tour_artifact_upload import lambda_handler

        event = _event(
            'POST',
            '/artifacts/tour/presign-upload',
            body={'tourId': 'TOT-2026', 'artifactId': 'ride-plan', 'contentType': 'image/gif'},
            path_params={},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400

    @patch('presign_tour_artifact_upload.s3_client')
    def test_presign_tour_artifact_upload_permission_denied(self, mock_s3, artifact_tables):
        from presign_tour_artifact_upload import lambda_handler

        event = _event(
            'POST',
            '/artifacts/tour/presign-upload',
            body={'tourId': 'TOT-2026', 'artifactId': 'ride-plan', 'contentType': 'application/pdf'},
            path_params={},
            groups=['GUEST'],
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 403

    @patch('delete_tour_artifact.s3_client')
    def test_delete_tour_artifact_success(self, mock_s3, artifact_tables):
        from delete_tour_artifact import lambda_handler

        artifact_tables['artifacts_table'].put_item(Item={
            'artifactFor': 'TOT-2026',
            'artifactId': 'ride-plan',
            's3Key': 'tours/TOT-2026/ride-plan.pdf',
            'contentType': 'application/pdf',
            'version': 1,
        })

        event = _event('DELETE', '/artifacts/tour/TOT-2026/ride-plan', path_params={'tourId': 'TOT-2026', 'artifactId': 'ride-plan'})

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        payload = json.loads(response['body'])
        assert payload['success'] is True
        assert payload['data']['artifactId'] == 'ride-plan'

    @patch('delete_ride_artifact.s3_client')
    def test_delete_ride_artifact_not_found(self, mock_s3, artifact_tables):
        from delete_ride_artifact import lambda_handler

        event = _event(
            'DELETE',
            '/artifacts/ride/TOT-2026/RIDE001/missing',
            path_params={'tourId': 'TOT-2026', 'rideId': 'RIDE001', 'artifactId': 'missing'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404


class TestArtifactReadApis:
    @patch('get_tour_artifacts.s3_client')
    def test_get_tour_artifacts_empty_tour(self, mock_s3, artifact_tables):
        from get_tour_artifacts import lambda_handler

        event = _event(
            'GET',
            '/tours/TOT-2026/artifacts',
            path_params={'tourId': 'TOT-2026'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        payload = json.loads(response['body'])
        assert payload['success'] is True
        assert payload['data'] == []

    @patch('get_tour_artifacts.s3_client')
    def test_get_tour_artifacts_with_artifacts(self, mock_s3, artifact_tables):
        from get_tour_artifacts import lambda_handler

        # Add artifacts to the tour
        artifact_tables['artifacts_table'].put_item(Item={
            'artifactFor': 'TOT-2026',
            'artifactId': 'ride-plan',
            's3Key': 'tours/TOT-2026/ride-plan.png',
            'contentType': 'image/png',
            'version': 1,
            'title': 'Route map',
            'createdAt': '2026-08-01T09:12:00Z',
            'updatedAt': '2026-08-01T09:12:00Z',
        })
        artifact_tables['artifacts_table'].put_item(Item={
            'artifactFor': 'TOT-2026',
            'artifactId': 'tour-elevation',
            's3Key': 'tours/TOT-2026/tour-elevation.png',
            'contentType': 'image/png',
            'version': 2,
            'title': 'Elevation chart',
            'createdAt': '2026-08-02T10:00:00Z',
            'updatedAt': '2026-08-03T14:00:00Z',
        })

        mock_s3.generate_presigned_url.return_value = 'https://s3.example.com/download-url'

        event = _event(
            'GET',
            '/tours/TOT-2026/artifacts',
            path_params={'tourId': 'TOT-2026'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        payload = json.loads(response['body'])
        assert payload['success'] is True
        assert len(payload['data']) == 2
        assert payload['data'][0]['artifactId'] in ['ride-plan', 'tour-elevation']
        assert payload['data'][0]['downloadUrl'] == 'https://s3.example.com/download-url'
        assert payload['data'][0]['expiresIn'] == 900

    @patch('get_tour_artifacts.s3_client')
    def test_get_tour_artifacts_filter_by_id(self, mock_s3, artifact_tables):
        from get_tour_artifacts import lambda_handler

        artifact_tables['artifacts_table'].put_item(Item={
            'artifactFor': 'TOT-2026',
            'artifactId': 'ride-plan',
            's3Key': 'tours/TOT-2026/ride-plan.png',
            'contentType': 'image/png',
            'version': 1,
            'title': 'Route map',
            'createdAt': '2026-08-01T09:12:00Z',
            'updatedAt': '2026-08-01T09:12:00Z',
        })

        mock_s3.generate_presigned_url.return_value = 'https://s3.example.com/download-url'

        event = _event(
            'GET',
            '/tours/TOT-2026/artifacts?artifactId=ride-plan',
            path_params={'tourId': 'TOT-2026'},
            query_params={'artifactId': 'ride-plan'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        payload = json.loads(response['body'])
        assert payload['success'] is True
        assert len(payload['data']) == 1
        assert payload['data'][0]['artifactId'] == 'ride-plan'

    @patch('get_tour_artifacts.s3_client')
    def test_get_tour_artifacts_custom_expires_in(self, mock_s3, artifact_tables):
        from get_tour_artifacts import lambda_handler

        artifact_tables['artifacts_table'].put_item(Item={
            'artifactFor': 'TOT-2026',
            'artifactId': 'ride-plan',
            's3Key': 'tours/TOT-2026/ride-plan.png',
            'contentType': 'image/png',
            'version': 1,
            'title': 'Route map',
            'createdAt': '2026-08-01T09:12:00Z',
            'updatedAt': '2026-08-01T09:12:00Z',
        })

        mock_s3.generate_presigned_url.return_value = 'https://s3.example.com/download-url'

        event = _event(
            'GET',
            '/tours/TOT-2026/artifacts?expiresIn=1800',
            path_params={'tourId': 'TOT-2026'},
            query_params={'expiresIn': '1800'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        payload = json.loads(response['body'])
        assert payload['success'] is True
        assert payload['data'][0]['expiresIn'] == 1800
        mock_s3.generate_presigned_url.assert_called_with(
            'get_object',
            Params={'Bucket': 'test-artifacts-bucket', 'Key': 'tours/TOT-2026/ride-plan.png'},
            ExpiresIn=1800,
        )

    @patch('get_tour_artifacts.s3_client')
    def test_get_tour_artifacts_invalid_expires_in(self, mock_s3, artifact_tables):
        from get_tour_artifacts import lambda_handler

        event = _event(
            'GET',
            '/tours/TOT-2026/artifacts?expiresIn=not-a-number',
            path_params={'tourId': 'TOT-2026'},
            query_params={'expiresIn': 'not-a-number'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 400

    @patch('get_tour_artifacts.s3_client')
    def test_get_tour_artifacts_tour_not_found(self, mock_s3, artifact_tables):
        from get_tour_artifacts import lambda_handler

        event = _event(
            'GET',
            '/tours/NONEXISTENT/artifacts',
            path_params={'tourId': 'NONEXISTENT'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404

    @patch('get_ride_artifacts.s3_client')
    def test_get_ride_artifacts_empty_ride(self, mock_s3, artifact_tables):
        from get_ride_artifacts import lambda_handler

        event = _event(
            'GET',
            '/tours/TOT-2026/rides/RIDE001/artifacts',
            path_params={'tourId': 'TOT-2026', 'rideId': 'RIDE001'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        payload = json.loads(response['body'])
        assert payload['success'] is True
        assert payload['data'] == []

    @patch('get_ride_artifacts.s3_client')
    def test_get_ride_artifacts_with_artifacts(self, mock_s3, artifact_tables):
        from get_ride_artifacts import lambda_handler

        # Add artifacts to the ride
        artifact_tables['artifacts_table'].put_item(Item={
            'artifactFor': 'TOT-2026#RIDE001',
            'artifactId': 'gpx-file',
            's3Key': 'tours/TOT-2026/rides/RIDE001/gpx-file.gpx',
            'contentType': 'application/gpx+xml',
            'version': 1,
            'title': 'Route GPX',
            'createdAt': '2026-08-01T09:12:00Z',
            'updatedAt': '2026-08-01T09:12:00Z',
        })
        artifact_tables['artifacts_table'].put_item(Item={
            'artifactFor': 'TOT-2026#RIDE001',
            'artifactId': 'ride-elevation',
            's3Key': 'tours/TOT-2026/rides/RIDE001/ride-elevation.png',
            'contentType': 'image/png',
            'version': 1,
            'title': 'Elevation profile',
            'createdAt': '2026-08-01T10:00:00Z',
            'updatedAt': '2026-08-01T10:00:00Z',
        })

        mock_s3.generate_presigned_url.return_value = 'https://s3.example.com/download-url'

        event = _event(
            'GET',
            '/tours/TOT-2026/rides/RIDE001/artifacts',
            path_params={'tourId': 'TOT-2026', 'rideId': 'RIDE001'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        payload = json.loads(response['body'])
        assert payload['success'] is True
        assert len(payload['data']) == 2
        assert payload['data'][0]['artifactId'] in ['gpx-file', 'ride-elevation']

    @patch('get_ride_artifacts.s3_client')
    def test_get_ride_artifacts_filter_by_id(self, mock_s3, artifact_tables):
        from get_ride_artifacts import lambda_handler

        artifact_tables['artifacts_table'].put_item(Item={
            'artifactFor': 'TOT-2026#RIDE001',
            'artifactId': 'gpx-file',
            's3Key': 'tours/TOT-2026/rides/RIDE001/gpx-file.gpx',
            'contentType': 'application/gpx+xml',
            'version': 1,
            'title': 'Route GPX',
            'createdAt': '2026-08-01T09:12:00Z',
            'updatedAt': '2026-08-01T09:12:00Z',
        })

        mock_s3.generate_presigned_url.return_value = 'https://s3.example.com/download-url'

        event = _event(
            'GET',
            '/tours/TOT-2026/rides/RIDE001/artifacts?artifactId=gpx-file',
            path_params={'tourId': 'TOT-2026', 'rideId': 'RIDE001'},
            query_params={'artifactId': 'gpx-file'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 200
        payload = json.loads(response['body'])
        assert payload['success'] is True
        assert len(payload['data']) == 1
        assert payload['data'][0]['artifactId'] == 'gpx-file'

    @patch('get_ride_artifacts.s3_client')
    def test_get_ride_artifacts_ride_not_found(self, mock_s3, artifact_tables):
        from get_ride_artifacts import lambda_handler

        event = _event(
            'GET',
            '/tours/TOT-2026/rides/RIDE999/artifacts',
            path_params={'tourId': 'TOT-2026', 'rideId': 'RIDE999'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404

    @patch('get_ride_artifacts.s3_client')
    def test_get_ride_artifacts_tour_not_found(self, mock_s3, artifact_tables):
        from get_ride_artifacts import lambda_handler

        event = _event(
            'GET',
            '/tours/NONEXISTENT/rides/RIDE001/artifacts',
            path_params={'tourId': 'NONEXISTENT', 'rideId': 'RIDE001'},
        )

        response = lambda_handler(event, None)
        assert response['statusCode'] == 404
