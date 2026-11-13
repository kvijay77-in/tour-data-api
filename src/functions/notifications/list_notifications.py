"""
List notifications Lambda function

Lists notifications for a tour, optionally filtered by type.
Accessible by any authenticated user (riders and staff).
Route: GET /v1/tours/{tourId}/notifications
"""

import sys

from logger import get_logger, log_event
from response import success_response, bad_request_response
from handler_utils import api_handler
from dynamodb_utils import scan_tour_items, query_tour_items
from validation import validate_tour_id, ValidationError
from models import NotificationType

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)


@api_handler("Failed to list notifications")
def lambda_handler(event, context):
    """
    List notifications for a tour

    Path Parameters:
        tourId: Tour identifier

    Query Parameters:
        type: Optional notification type filter
        riderId: Optional rider ID to include personal notifications

    Returns:
    - 200: List of notifications
    - 400: Invalid input
    - 500: Server error
    """
    log_event(logger, event)

    # Extract tour ID from path parameters
    tour_id = event.get("pathParameters", {}).get("tourId")

    if not tour_id:
        return bad_request_response("tourId is required in path")

    try:
        validate_tour_id(tour_id)
    except ValidationError as e:
        return bad_request_response(str(e))

    # Extract query parameters
    query_params = event.get("queryStringParameters") or {}
    notification_type = query_params.get("type")
    rider_id = query_params.get("riderId")

    logger.info("Listing notifications for tour: %s", tour_id)

    # Validate type filter if provided
    if notification_type:
        try:
            NotificationType(notification_type)
        except ValueError:
            valid_types = [t.value for t in NotificationType]
            return bad_request_response(
                f"Invalid notification type. Must be one of: {', '.join(valid_types)}"
            )

        # Use GSI for type-filtered query
        notifications = query_tour_items(
            table_type="Notification",
            tour_id=tour_id,
            key_condition_expression="#type = :type",
            expression_values={":type": notification_type},
            expression_names={"#type": "type"},
            index_name="TypeCreatedAtIndex",
        )
    else:
        # Scan all notifications
        notifications = scan_tour_items(table_type="Notification", tour_id=tour_id)

    # Filter: include broadcast notifications (no targetRiderId)
    # and personal notifications for the specified rider
    if rider_id:
        notifications = [
            n
            for n in notifications
            if not n.get("targetRiderId") or n.get("targetRiderId") == rider_id
        ]
    else:
        # If no riderId specified, only return broadcast notifications
        notifications = [n for n in notifications if not n.get("targetRiderId")]

    # Sort by createdAt descending (newest first)
    notifications.sort(key=lambda n: n.get("createdAt", ""), reverse=True)

    logger.info("Found %s notifications for tour %s", len(notifications), tour_id)

    return success_response(
        {"notifications": notifications, "count": len(notifications), "tourId": tour_id}
    )
