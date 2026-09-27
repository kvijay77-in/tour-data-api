"""Generate presigned URL for rider profile photo download."""

import sys
sys.path.insert(0, '/opt/python')

import os

import boto3

from logger import get_logger, log_event
from rbac import Permission, require_permission
from response import success_response, bad_request_response, not_found_response, internal_error_response
from dynamodb_utils import get_item
from ownership import require_own_profile, is_rider_api_request

logger = get_logger(__name__)
s3_client = boto3.client('s3')

DEFAULT_EXPIRY_SECONDS = 300
MAX_EXPIRY_SECONDS = 3600


def lambda_handler(event, context):
    try:
        log_event(logger, event)

        profile_id = (event.get('pathParameters') or {}).get('profileId')
        if not profile_id:
            return bad_request_response('profileId is required in path')

        api_id = (event.get('requestContext', {}) or {}).get('apiId')
        if is_rider_api_request(event):
            deny = require_own_profile(event, profile_id)
            if deny:
                return deny
        elif api_id:
            rbac_deny = require_permission(event, Permission.READ)
            if rbac_deny:
                return rbac_deny

        existing_rider = get_item('RIDER_PROFILE_TABLE', {'profileId': profile_id})
        if not existing_rider:
            return not_found_response('RiderProfile', profile_id)

        s3_key = existing_rider.get('photoS3Key')
        if not s3_key:
            return not_found_response('ProfilePicture', profile_id)

        expires_in = DEFAULT_EXPIRY_SECONDS
        expires_param = (event.get('queryStringParameters') or {}).get('expiresIn')
        if expires_param:
            try:
                expires_in = int(expires_param)
            except (TypeError, ValueError):
                return bad_request_response('expiresIn must be an integer')
            if expires_in < 60 or expires_in > MAX_EXPIRY_SECONDS:
                return bad_request_response(f'expiresIn must be between 60 and {MAX_EXPIRY_SECONDS} seconds')

        bucket_name = os.environ.get('PHOTOS_BUCKET')
        if not bucket_name:
            return internal_error_response('Photos bucket not configured')

        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=expires_in,
        )

        return success_response({
            'downloadUrl': presigned_url,
            'photoS3Key': s3_key,
            'expiresIn': expires_in,
            'profileId': profile_id,
        })

    except Exception as exc:
        logger.error(f'Error generating download URL: {str(exc)}', exc_info=True)
        return internal_error_response('Failed to generate download URL')
