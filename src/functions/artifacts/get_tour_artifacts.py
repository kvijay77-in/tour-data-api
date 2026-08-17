"""
Get tour artifacts manifest Lambda function.

Queries the Artifacts table for a tour and returns presigned download URLs.
Route: GET /v1/tours/{tourId}/artifacts
"""

import json
import os
import sys

import boto3

sys.path.insert(0, '/opt/python')

from dynamodb_utils import get_item, query_items
from logger import get_logger, log_event
from rbac import Permission, require_permission
from response import bad_request_response, internal_error_response, not_found_response, success_response
from validation import ValidationError, validate_tour_id

logger = get_logger(__name__)
s3_client = boto3.client('s3')

DEFAULT_EXPIRY_SECONDS = 900
MAX_EXPIRY_SECONDS = 3600


def lambda_handler(event, context):
    """
    Get artifacts manifest for a tour.

    Path Parameters:
        tourId: Tour identifier (e.g., TOT-2026)

    Query Parameters:
        artifactId (optional): Filter to a single artifact
        expiresIn (optional): Download URL validity in seconds (60-3600, default 900)

    Returns:
    - 200: List of artifacts with presigned download URLs
    - 400: Invalid input
    - 404: Tour not found
    - 500: Server error
    """
    try:
        log_event(logger, event)

        deny = require_permission(event, Permission.READ)
        if deny:
            return deny

        # Extract path and query parameters
        tour_id = (event.get('pathParameters') or {}).get('tourId')

        if not tour_id:
            return bad_request_response("tourId is required in path")

        try:
            validate_tour_id(tour_id)
        except ValidationError as exc:
            return bad_request_response(exc.message, exc.details)

        # Verify tour exists
        tour = get_item(table_name_env='TOUR_MASTER_TABLE', key={'tourId': tour_id})
        if not tour:
            return not_found_response('Tour', tour_id)

        # Parse expiry
        expires_in = DEFAULT_EXPIRY_SECONDS
        expires_in_param = (event.get('queryStringParameters') or {}).get('expiresIn')
        if expires_in_param:
            try:
                expires_in = int(expires_in_param)
            except (TypeError, ValueError):
                return bad_request_response("expiresIn must be an integer")
            if expires_in < 60 or expires_in > MAX_EXPIRY_SECONDS:
                return bad_request_response(
                    f"expiresIn must be between 60 and {MAX_EXPIRY_SECONDS} seconds"
                )

        # Query artifacts for this tour
        artifacts = query_items(
            table_name_env='ARTIFACTS_TABLE',
            key_condition_expression='artifactFor = :artifactFor',
            expression_values={':artifactFor': tour_id},
        )

        # Filter by artifactId if provided
        artifact_id_filter = (event.get('queryStringParameters') or {}).get('artifactId')
        if artifact_id_filter:
            artifacts = [a for a in artifacts if a.get('artifactId') == artifact_id_filter]
            if not artifacts:
                return success_response([])

        # Build response with presigned URLs
        bucket_name = os.environ.get('ARTIFACTS_BUCKET')
        if not bucket_name:
            return internal_error_response('Artifacts bucket not configured')

        manifest = []
        for artifact in artifacts:
            s3_key = artifact.get('s3Key')
            if not s3_key:
                logger.warning(f"Artifact missing s3Key: {artifact.get('artifactId')}")
                continue

            try:
                download_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': bucket_name, 'Key': s3_key},
                    ExpiresIn=expires_in,
                )

                manifest.append({
                    'artifactId': artifact.get('artifactId'),
                    's3Key': s3_key,
                    'contentType': artifact.get('contentType'),
                    'version': artifact.get('version'),
                    'title': artifact.get('title'),
                    'downloadUrl': download_url,
                    'expiresIn': expires_in,
                    'createdAt': artifact.get('createdAt'),
                    'updatedAt': artifact.get('updatedAt'),
                })
            except Exception as exc:
                logger.error(f"Error generating presigned URL for {s3_key}: {str(exc)}", exc_info=True)
                continue

        return success_response(manifest)

    except Exception as exc:
        logger.error(f'Error fetching tour artifacts: {str(exc)}', exc_info=True)
        return internal_error_response('Failed to fetch artifacts')
