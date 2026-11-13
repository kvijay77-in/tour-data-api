"""Generate presigned URL for rider profile photo upload."""

import sys

import json
import os
import uuid

import boto3

from logger import get_logger, log_event
from rbac import Permission, require_permission
from response import (
    success_response,
    bad_request_response,
    not_found_response,
    internal_error_response,
)
from handler_utils import api_handler
from dynamodb_utils import get_item
from ownership import require_own_profile, is_rider_api_request
from profile_schema import get_user_role_flags

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)
s3_client = boto3.client("s3")


@api_handler("Failed to generate upload URL")
def lambda_handler(event, context):
    log_event(logger, event)

    profile_id = (event.get("pathParameters") or {}).get("profileId")
    if not profile_id:
        return bad_request_response("profileId is required in path")

    role_flags = get_user_role_flags(event)
    api_id = (event.get("requestContext", {}) or {}).get("apiId")
    if is_rider_api_request(event):
        deny = require_own_profile(event, profile_id)
        if deny and not role_flags["is_admin"]:
            return deny
    elif api_id and not role_flags["is_admin"]:
        deny = require_permission(event, Permission.RIDER_SELF_UPDATE)
        if deny:
            return deny

    existing_rider = get_item("RIDER_PROFILE_TABLE", {"profileId": profile_id})
    if not existing_rider:
        return not_found_response("RiderProfile", profile_id)

    content_type = "image/jpeg"
    try:
        body = json.loads(event.get("body", "{}") or "{}")
        if isinstance(body, dict) and body.get("contentType"):
            content_type = body["contentType"]
    except json.JSONDecodeError:
        return bad_request_response("Invalid JSON in request body")

    allowed_types = ["image/jpeg", "image/png"]
    if content_type not in allowed_types:
        return bad_request_response(
            f"Invalid content type: {content_type}. Allowed: {', '.join(allowed_types)}"
        )

    ext = "jpg" if content_type == "image/jpeg" else "png"
    file_id = str(uuid.uuid4())
    s3_key = f"riders/{profile_id}/photo/{file_id}.{ext}"

    bucket_name = os.environ.get("PHOTOS_BUCKET")
    if not bucket_name:
        return internal_error_response("Photos bucket not configured")

    presigned_url = s3_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket_name, "Key": s3_key, "ContentType": content_type},
        ExpiresIn=300,
    )

    return success_response(
        {
            "uploadUrl": presigned_url,
            "photoS3Key": s3_key,
            "contentType": content_type,
            "expiresIn": 300,
            "profileId": profile_id,
        }
    )
