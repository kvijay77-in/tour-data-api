"""
Lambda function to cancel an existing check-in.

This API performs a special update flow:
- request body must include status containing CANCELLED
- request body must include prevStatus
- only status, prevStatus, cancelledBy and cancelledAt are updated
- no other attributes are modified

Uses tour-specific table: CheckIn-{tourId}.
Route: POST /v1/tours/{tourId}/rides/{rideId}/checkins/{checkInId}/cancel
"""

import sys

import json

from logger import get_logger
from response import (
    success_response,
    bad_request_response,
    not_found_response,
    internal_error_response,
    error_response,
)
from validation import validate_tour_id, validate_ride_id, ValidationError
from checkin_service import cancel_checkin
from dynamodb_utils import get_tour_item
from rbac import Permission, require_permission

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def lambda_handler(event, context):
    """Cancel an existing check-in record using special status-driven behavior."""
    try:
        deny = require_permission(event, Permission.CHECKIN)
        if deny:
            return deny

        path_params = event.get('pathParameters', {})
        tour_id = path_params.get('tourId')
        ride_id = path_params.get('rideId')
        checkin_id = path_params.get('checkInId')

        if not tour_id or not ride_id or not checkin_id:
            return bad_request_response("tourId, rideId and checkInId are required in path")

        try:
            validate_tour_id(tour_id)
            validate_ride_id(ride_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")

        status = str(body.get('status', ''))
        if 'CANCELLED' not in status.upper():
            return error_response(
                error_code='INVALID_CANCEL_INVOCATION',
                message="Cancellation requires status containing 'CANCELLED'",
                status_code=400,
            )

        prev_status = body.get('prevStatus')
        if prev_status is None or str(prev_status).strip() == '':
            return bad_request_response("prevStatus is required for cancellation")

        existing = get_tour_item(
            table_type='CheckIn',
            tour_id=tour_id,
            key={'rideId': ride_id, 'checkInId': checkin_id}
        )
        if not existing:
            return not_found_response('CheckIn', checkin_id)

        cancelled_by = event.get('requestContext', {}).get(
            'authorizer', {}
        ).get('jwt', {}).get('claims', {}).get('sub', 'system')

        # Shared cancel (also used by rider self check-in cancel)
        updated = cancel_checkin(
            tour_id=tour_id,
            ride_id=ride_id,
            existing={**existing, 'checkInId': checkin_id},
            prev_status=prev_status,
            cancelled_by=cancelled_by,
        )

        return success_response(updated)

    except Exception as e:
        logger.error("Error cancelling check-in: %s", e, exc_info=True)
        return internal_error_response("Failed to cancel check-in")
