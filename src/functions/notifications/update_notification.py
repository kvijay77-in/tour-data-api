"""
Update notification Lambda function

Marks a notification as read for a specific rider.
Accessible by any authenticated user.
Route: PUT /v1/tours/{tourId}/notifications/{notificationId}
"""

import sys

import json

from logger import get_logger, log_event
from response import (
    success_response, bad_request_response, not_found_response,
    internal_error_response
)
from dynamodb_utils import get_tour_item, put_tour_item
from validation import validate_tour_id, ValidationError

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Update a notification (mark as read)

    Path Parameters:
        tourId: Tour identifier
        notificationId: Notification identifier

    Body:
        profileId: Profile ID of the reader (required)

    Returns:
    - 200: Notification updated
    - 400: Invalid input
    - 404: Notification not found
    - 500: Server error
    """
    try:
        log_event(logger, event)

        # Extract path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        notification_id = event.get('pathParameters', {}).get('notificationId')

        if not tour_id:
            return bad_request_response("tourId is required in path")
        if not notification_id:
            return bad_request_response("notificationId is required in path")

        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        # Parse request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")

        profile_id = body.get('profileId')
        if not profile_id:
            return bad_request_response("profileId is required in body")

        # Get existing notification
        notification = get_tour_item(
            table_type='Notification',
            tour_id=tour_id,
            key={'notificationId': notification_id}
        )

        if not notification:
            return not_found_response("Notification", notification_id)

        # Add profileId to readBy list if not already present
        read_by = notification.get('readBy', [])
        if not isinstance(read_by, list):
            read_by = []

        if profile_id not in read_by:
            read_by.append(profile_id)
            notification['readBy'] = read_by

            logger.info(
                "Marking notification %s as read by %s", notification_id, profile_id
            )
            put_tour_item(
                table_type='Notification',
                tour_id=tour_id,
                item=notification
            )

        logger.info("Successfully updated notification %s", notification_id)
        return success_response(notification)

    except Exception as e:
        logger.error("Error updating notification: %s", e, exc_info=True)
        return internal_error_response("Failed to update notification")
