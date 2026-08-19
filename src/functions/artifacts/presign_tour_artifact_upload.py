"""Generate a presigned S3 URL for a tour-level artifact upload."""

import json
import os
import sys

import boto3

sys.path.insert(0, '/opt/python')

from dynamodb_utils import get_item, get_tour_item, put_tour_item, query_items
from logger import get_logger, log_event
from models import utc_now_iso
from rbac import Permission, require_permission
from response import bad_request_response, internal_error_response, not_found_response, success_response
from validation import ValidationError, validate_artifact_content_type, validate_artifact_id, validate_tour_id

logger = get_logger(__name__)
s3_client = boto3.client('s3')

CONTENT_TYPE_TO_EXTENSION = {
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
    'application/pdf': 'pdf',
    'application/gpx+xml': 'gpx',
    'application/xml': 'xml',
    'text/xml': 'xml',
    'text/plain': 'txt',
    'application/octet-stream': 'bin',
}


def _parse_body(event):
    raw_body = event.get('body') or '{}'
    if isinstance(raw_body, str):
        try:
            return json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            return {}
    return raw_body if isinstance(raw_body, dict) else {}


def _get_artifact_config(artifact_id):
    items = query_items(
        table_name_env='APP_CONFIG_TABLE',
        key_condition_expression='configType = :configType',
        expression_values={':configType': 'ARTIFACTS'},
    )
    for item in items:
        if item.get('configId') == artifact_id and item.get('enabled') is True:
            return item
    return None


def _build_s3_key(tour_id, artifact_id, content_type):
    extension = CONTENT_TYPE_TO_EXTENSION.get(content_type.lower())
    if not extension:
        raise ValidationError(f"Unsupported artifact contentType: '{content_type}'")
    return f'tours/{tour_id}/{artifact_id}.{extension}'


def lambda_handler(event, context):
    try:
        log_event(logger, event)

        deny = require_permission(event, Permission.ARTIFACT_MANAGE)
        if deny:
            return deny

        body = _parse_body(event)
        tour_id = (body.get('tourId') or '').strip()
        artifact_id = (body.get('artifactId') or '').strip()
        content_type = (body.get('contentType') or 'application/pdf').strip()

        if not tour_id:
            return bad_request_response('tourId is required')
        if not artifact_id:
            return bad_request_response('artifactId is required')

        try:
            validate_tour_id(tour_id)
            validate_artifact_id(artifact_id)
            validate_artifact_content_type(content_type)
        except ValidationError as exc:
            return bad_request_response(exc.message, exc.details)

        if not get_item(table_name_env='TOUR_MASTER_TABLE', key={'tourId': tour_id}):
            return not_found_response('Tour', tour_id)

        config_item = _get_artifact_config(artifact_id)
        if not config_item:
            return bad_request_response(f"Artifact type '{artifact_id}' is not configured")

        category = (config_item.get('config', {}) or {}).get('category', '').lower()
        if category != 'tour':
            return bad_request_response(
                f"Artifact type '{artifact_id}' is configured for the ride category, not tour uploads"
            )

        normalized_content_type = content_type.strip().lower()
        s3_key = _build_s3_key(tour_id, artifact_id, normalized_content_type)
        bucket_name = os.environ.get('ARTIFACTS_BUCKET')
        if not bucket_name:
            return internal_error_response('Artifacts bucket not configured')

        existing = get_tour_item(
            table_type='Artifacts',
            tour_id=tour_id,
            key={'artifactFor': tour_id, 'artifactId': artifact_id},
        )
        version = int(existing.get('version', 0)) + 1 if existing else 1
        created_at = existing.get('createdAt', utc_now_iso()) if existing else utc_now_iso()
        updated_at = utc_now_iso()

        metadata = {
            'artifactFor': tour_id,
            'artifactId': artifact_id,
            's3Key': s3_key,
            'contentType': normalized_content_type,
            'category': 'tour',
            'title': config_item.get('description') or artifact_id,
            'version': version,
            'createdAt': created_at,
            'updatedAt': updated_at,
        }

        put_tour_item('Artifacts', tour_id, item=metadata)

        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': bucket_name, 'Key': s3_key, 'ContentType': normalized_content_type},
            ExpiresIn=300,
        )

        return success_response({
            'artifactFor': tour_id,
            'artifactId': artifact_id,
            's3Key': s3_key,
            'contentType': normalized_content_type,
            'uploadUrl': presigned_url,
            'expiresIn': 300,
            'version': version,
            'title': metadata['title'],
        })
    except Exception as exc:
        logger.error(f'Error generating tour artifact upload URL: {str(exc)}', exc_info=True)
        return internal_error_response('Failed to generate upload URL')
