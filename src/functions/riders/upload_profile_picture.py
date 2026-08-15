"""
Upload profile picture Lambda function

Generates a presigned S3 URL for the rider to upload their profile picture.
After upload, the rider should update their profile with the S3 key via
PUT /v1/riders/profile/{profileId}.
Route: POST /v1/riders/profile/{profileId}/picture
"""

import sys
sys.path.insert(0, '/opt/python')

import json
import os
import uuid

import boto3

from logger import get_logger, log_event
from rbac import require_permission, Permission
from response import (
    success_response, bad_request_response, not_found_response,
    internal_error_response
)
from dynamodb_utils import get_item
from models import utc_now_iso

logger = get_logger(__name__)

s3_client = boto3.client('s3')


def lambda_handler(event, context):
    """
    Generate a presigned URL for profile picture upload

    Path Parameters:
        profileId: Rider profile ID

    Body (optional):
        contentType: Image content type (default: image/jpeg)

    Returns:
    - 200: Presigned URL and S3 key
    - 400: Invalid input
    - 404: Profile not found
    - 500: Server error
    """
    try:
        log_event(logger, event)

        deny = require_permission(event, Permission.RIDER_SELF_UPDATE)
        if deny:
            return deny

        # Extract profile ID from path parameters
        profile_id = event.get('pathParameters', {}).get('profileId')

        if not profile_id:
            return bad_request_response("profileId is required in path")

        # Verify rider profile exists
        existing_rider = get_item(
            table_name_env='RIDER_PROFILE_TABLE',
            key={'profileId': profile_id}
        )

        if not existing_rider:
            return not_found_response("RiderProfile", profile_id)

        # Parse optional body
        content_type = 'image/jpeg'
        try:
            body = json.loads(event.get('body', '{}') or '{}')
            if body.get('contentType'):
                content_type = body['contentType']
        except json.JSONDecodeError:
            pass

        # Validate content type
        allowed_types = ['image/jpeg', 'image/png']
        if content_type not in allowed_types:
            return bad_request_response(
                f"Invalid content type: {content_type}. Allowed: {', '.join(allowed_types)}"
            )

        # Determine file extension
        ext = 'jpg' if content_type == 'image/jpeg' else 'png'

        # Generate S3 key
        file_id = str(uuid.uuid4())
        s3_key = f"profiles/{profile_id}/{file_id}.{ext}"

        # Get bucket name
        bucket_name = os.environ.get('PHOTOS_BUCKET')
        if not bucket_name:
            return internal_error_response("Photos bucket not configured")

        # Generate presigned URL (valid for 5 minutes)
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': bucket_name,
                'Key': s3_key,
                'ContentType': content_type
            },
            ExpiresIn=300
        )

        logger.info(f"Generated presigned URL for profile {profile_id}")

        return success_response({
            'uploadUrl': presigned_url,
            'photoS3Key': s3_key,
            'contentType': content_type,
            'expiresIn': 300,
            'profileId': profile_id
        })

    except Exception as e:
        logger.error(f"Error generating upload URL: {str(e)}", exc_info=True)
        return internal_error_response("Failed to generate upload URL")
