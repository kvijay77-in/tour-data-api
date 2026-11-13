"""Delete a ride-level artifact from S3 and DynamoDB metadata."""

import os
import sys

import boto3

from dynamodb_utils import get_tour_item, get_tour_table
from logger import get_logger, log_event
from rbac import Permission, require_permission
from response import bad_request_response, internal_error_response, not_found_response, success_response


sys.path.insert(0, '/opt/python')
logger = get_logger(__name__)
s3_client = boto3.client('s3')


def lambda_handler(event, context):
    try:
        log_event(logger, event)

        deny = require_permission(event, Permission.ARTIFACT_MANAGE)
        if deny:
            return deny

        tour_id = (event.get('pathParameters') or {}).get('tourId')
        ride_id = (event.get('pathParameters') or {}).get('rideId')
        artifact_id = (event.get('pathParameters') or {}).get('artifactId')

        if not tour_id:
            return bad_request_response('tourId is required in path')
        if not ride_id:
            return bad_request_response('rideId is required in path')
        if not artifact_id:
            return bad_request_response('artifactId is required in path')

        artifact_for = f'{tour_id}#{ride_id}'
        existing = get_tour_item(
            table_type='Artifacts',
            tour_id=tour_id,
            key={'artifactFor': artifact_for, 'artifactId': artifact_id},
        )
        if not existing:
            return not_found_response('Artifact', f'{artifact_for}/{artifact_id}')

        bucket_name = os.environ.get('ARTIFACTS_BUCKET')
        if not bucket_name:
            return internal_error_response('Artifacts bucket not configured')

        s3_key = existing.get('s3Key')
        if s3_key:
            s3_client.delete_object(Bucket=bucket_name, Key=s3_key)

        get_tour_table('Artifacts', tour_id).delete_item(
            Key={'artifactFor': artifact_for, 'artifactId': artifact_id}
        )

        return success_response({
            'artifactFor': artifact_for,
            'artifactId': artifact_id,
            'deleted': True,
            's3Key': s3_key,
        })
    except Exception as exc:
        logger.error("Error deleting ride artifact: %s", exc, exc_info=True)
        return internal_error_response('Failed to delete artifact')
