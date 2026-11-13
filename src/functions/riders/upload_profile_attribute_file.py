"""Generate presigned upload URL for rider profile FILE/IMAGE attributes."""

import sys

import json
import os
import uuid

import boto3

from logger import get_logger, log_event
from response import success_response, bad_request_response, not_found_response, error_response, internal_error_response
from handler_utils import api_handler
from dynamodb_utils import get_item
from ownership import require_own_profile
from profile_schema import validate_attribute_upload_request, ProfileSchemaError, get_user_role_flags

sys.path.insert(0, '/opt/python')


logger = get_logger(__name__)
s3_client = boto3.client('s3')


def _ext_from_content_type(content_type: str) -> str:
    if '/' not in content_type:
        return 'bin'
    suffix = content_type.split('/')[-1].lower()
    return {'jpeg': 'jpg'}.get(suffix, suffix)


@api_handler('Failed to generate attribute upload URL')
def lambda_handler(event, context):
    try:
        log_event(logger, event)
        path_params = event.get('pathParameters') or {}
        profile_id = (path_params.get('profileId') or '').strip()
        attr_key = (path_params.get('key') or '').strip()
        if not profile_id or not attr_key:
            return bad_request_response('profileId and key are required in path')

        role_flags = get_user_role_flags(event)
        deny = require_own_profile(event, profile_id)
        if deny and not role_flags['is_admin']:
            return deny

        rider = get_item('RIDER_PROFILE_TABLE', {'profileId': profile_id})
        if not rider:
            return not_found_response('RiderProfile', profile_id)

        try:
            body = json.loads(event.get('body') or '{}')
        except json.JSONDecodeError:
            return bad_request_response('Invalid JSON in request body')

        content_type = body.get('contentType')
        size_bytes = body.get('sizeBytes')
        if not content_type or size_bytes is None:
            return bad_request_response('contentType and sizeBytes are required')

        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError, OverflowError):
            return bad_request_response('sizeBytes must be an integer')

        validate_attribute_upload_request(attr_key, content_type, size_bytes)

        bucket_name = os.environ.get('PHOTOS_BUCKET')
        if not bucket_name:
            return internal_error_response('Photos bucket not configured')

        ext = _ext_from_content_type(content_type)
        key_uuid = str(uuid.uuid4())
        s3_key = f'riders/{profile_id}/attributes/{attr_key}/{key_uuid}.{ext}'

        upload_url = s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': bucket_name, 'Key': s3_key, 'ContentType': content_type},
            ExpiresIn=300,
        )

        return success_response({
            'uploadUrl': upload_url,
            's3Key': s3_key,
            'expiresIn': 300,
            'profileId': profile_id,
            'attributeKey': attr_key,
        })

    except ProfileSchemaError as exc:
        return error_response(exc.code, exc.message, status_code=exc.status_code)
