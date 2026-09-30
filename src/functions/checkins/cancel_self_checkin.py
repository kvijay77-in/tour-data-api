"""
Rider self check-in cancel Lambda function (Rider API only).

Route: POST /v1/tours/{tourId}/rides/{rideId}/self-checkins/{checkInId}/cancel

The rider may cancel their own stage or Not Riding check-in (made by the rider
or by a Mgmt user) while self-service for it is allowed. Quit Riding check-ins
are never cancellable here (403 QUIT_RIDING_CANCEL_NOT_ALLOWED); only Mgmt users
can cancel them through the existing cancel endpoint.
"""

import sys
sys.path.insert(0, '/opt/python')

import json

from logger import get_logger, log_event
from response import (
    bad_request_response,
    error_response,
    internal_error_response,
    success_response,
    validation_error_response,
)
from validation import validate_ride_id, validate_tour_id, ValidationError
from checkin_service import cancel_checkin
from dynamodb_utils import get_tour_item
from rbac import Permission, require_permission
from rider_identity import reject_client_rider_id
from self_checkin_rules import check_self_cancel_allowed, derive_checkin_status, load_self_checkin_context

logger = get_logger(__name__)


def lambda_handler(event, context):
    """Cancel one of the calling rider's check-ins. Returns 200 with the cancelled record."""
    try:
        log_event(logger, event)

        deny = require_permission(event, Permission.SELF_CHECKIN)
        if deny:
            return deny

        path_params = event.get('pathParameters') or {}
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
            body = json.loads(event.get('body') or '{}')
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")
        if not isinstance(body, dict):
            return validation_error_response("Request body must be a JSON object")

        rejected = reject_client_rider_id(body, [event.get('queryStringParameters') or {}])
        if rejected:
            return rejected

        # Checks 1-4 from self check-in: tour ACTIVE, caller on tour, ride today and OPEN/STARTED
        self_context, error = load_self_checkin_context(event, tour_id, ride_id)
        if error:
            return error

        existing = get_tour_item(
            table_type='CheckIn',
            tour_id=tour_id,
            key={'rideId': ride_id, 'checkInId': checkin_id}
        )
        if not existing:
            return error_response('CHECKIN_NOT_FOUND', f"CheckIn '{checkin_id}' not found", 404)

        error = check_self_cancel_allowed(self_context, existing)
        if error:
            return error

        updated = cancel_checkin(
            tour_id=tour_id,
            ride_id=ride_id,
            existing={**existing, 'checkInId': checkin_id},
            prev_status=derive_checkin_status(existing),
            cancelled_by=self_context['identity']['profileId'],
        )
        return success_response(updated)

    except Exception as e:
        logger.error(f"Error cancelling self check-in: {str(e)}", exc_info=True)
        return internal_error_response("Failed to cancel self check-in")
