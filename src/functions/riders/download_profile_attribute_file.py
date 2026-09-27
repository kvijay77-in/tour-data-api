"""Generate presigned download URL for rider profile FILE/IMAGE attributes."""

import sys
sys.path.insert(0, '/opt/python')

import os

import boto3

from logger import get_logger, log_event
from response import success_response, bad_request_response, not_found_response, error_response, internal_error_response
from dynamodb_utils import get_item
from ownership import require_own_profile, is_rider_api_request
from profile_schema import (
    ProfileSchemaError,
    get_user_role_flags,
    get_attribute_flags,
    require_file_attribute_definition,
)


logger = get_logger(__name__)
s3_client = boto3.client('s3')


def lambda_handler(event, context):
    try:
        log_event(logger, event)
        path_params = event.get('pathParameters') or {}
        profile_id = (path_params.get('profileId') or '').strip()
        attr_key = (path_params.get('key') or '').strip()
        if not profile_id or not attr_key:
            return bad_request_response('profileId and key are required in path')

        role_flags = get_user_role_flags(event)
        rider_api_call = is_rider_api_request(event)
        deny = require_own_profile(event, profile_id)
        if deny and not role_flags['is_admin']:
            return deny

        rider = get_item('RIDER_PROFILE_TABLE', {'profileId': profile_id})
        if not rider:
            return not_found_response('RiderProfile', profile_id)

        require_file_attribute_definition(attr_key)

        attr_flags = get_attribute_flags(attr_key)
        enforce_staff_visibility = not rider_api_call
        if enforce_staff_visibility:
            if attr_flags.get('sensitive') and not (role_flags['is_admin'] or role_flags['is_super_user']):
                return error_response('PROFILE_ACCESS_DENIED', 'Sensitive attribute download requires elevated role', status_code=403)
            if not role_flags['is_admin'] and not role_flags['is_super_user'] and not attr_flags['visibleToAllMgmtUsers']:
                return error_response('PROFILE_ACCESS_DENIED', 'Attribute is not visible for this role', status_code=403)

        attr_val = (rider.get('attributes') or {}).get(attr_key)
        if not isinstance(attr_val, dict) or not attr_val.get('s3Key'):
            return not_found_response('ProfileAttributeFile', attr_key)

        bucket_name = os.environ.get('PHOTOS_BUCKET')
        if not bucket_name:
            return internal_error_response('Photos bucket not configured')

        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': attr_val['s3Key']},
            ExpiresIn=300,
        )

        return success_response({
            'downloadUrl': download_url,
            's3Key': attr_val['s3Key'],
            'expiresIn': 300,
            'profileId': profile_id,
            'attributeKey': attr_key,
        })

    except ProfileSchemaError as exc:
        return error_response(exc.code, exc.message, status_code=exc.status_code)
    except Exception as exc:
        logger.error(f'Error generating attribute download URL: {str(exc)}', exc_info=True)
        return internal_error_response('Failed to generate attribute download URL')
