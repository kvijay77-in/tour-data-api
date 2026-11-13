"""
Create notification Lambda function

Creates a new notification for a tour. Only accessible by admins/organizers.
Route: POST /v1/tours/{tourId}/notifications
"""

import sys

import json
import uuid

from logger import get_logger, log_event
from response import (
    success_response, bad_request_response, internal_error_response
)
from dynamodb_utils import put_tour_item
from validation import (
    validate_tour_id, validate_required_fields, ValidationError
)
from models import NotificationType, utc_now_iso
from rbac import require_permission, Permission

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Create a notification for a tour

    Path Parameters:
        tourId: Tour identifier

    Body:
        type: Notification type (required)
        title: Notification title (required)
        message: Notification content (required)
        targetRiderId: Optional rider ID for personal notifications
        expiresAt: Optional expiry timestamp

    Returns:
    - 201: Notification created
    - 400: Invalid input
    - 403: Insufficient permissions
    - 500: Server error
    """
    try:
        log_event(logger, event)

        # Enforce RBAC — NOTIFICATION_MANAGE permission required
        deny = require_permission(event, Permission.NOTIFICATION_MANAGE)
        if deny:
            return deny

        # Extract tour ID from path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')

        if not tour_id:
            return bad_request_response("tourId is required in path")

        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        # Parse request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")

        # Validate required fields
        try:
            validate_required_fields(body, ['type', 'title', 'message'])
        except ValidationError as e:
            return bad_request_response(str(e))

        # Validate notification type
        notification_type = body['type']
        try:
            NotificationType(notification_type)
        except ValueError:
            valid_types = [t.value for t in NotificationType]
            return bad_request_response(
                f"Invalid notification type. Must be one of: {', '.join(valid_types)}"
            )

        # Get created-by from request context (JWT authorizer)
        created_by = event.get('requestContext', {}).get(
            'authorizer', {}
        ).get('jwt', {}).get('claims', {}).get('sub', 'system')

        notification_id = str(uuid.uuid4())
        now = utc_now_iso()

        item = {
            'notificationId': notification_id,
            'type': notification_type,
            'title': body['title'],
            'message': body['message'],
            'createdBy': created_by,
            'readBy': [],
            'createdAt': now
        }

        # Optional fields
        if body.get('targetRiderId'):
            item['targetRiderId'] = body['targetRiderId']
        if body.get('expiresAt'):
            item['expiresAt'] = body['expiresAt']

        logger.info("Creating notification %s for tour %s", notification_id, tour_id)
        put_tour_item(
            table_type='Notification',
            tour_id=tour_id,
            item=item
        )

        logger.info("Successfully created notification %s", notification_id)
        return success_response(item, status_code=201)

    except Exception as e:
        logger.error("Error creating notification: %s", e, exc_info=True)
        return internal_error_response("Failed to create notification")
