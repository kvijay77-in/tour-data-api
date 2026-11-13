"""
Create check-in Lambda function

Handles creating new check-in records including:
- Normal check-ins at stages
- Not Riding (NR) status
- Quit Riding (QR) status
- Manual entry support
- Timestamp-based validation for offline-synced check-ins
- Late-sync support for closed rides
- Duplicate check-in detection

Uses tour-specific tables: CheckIn-{tourId}, Ride-{tourId}, TourRider-{tourId}.
Validation and storage are shared with rider self check-in (checkin_service.create_checkin).
Route: POST /v1/tours/{tourId}/checkins
"""

import sys

import json

from logger import get_logger, log_event
from response import bad_request_response, validation_error_response
from handler_utils import api_handler
from validation import (
    validate_rider_id,
    validate_ride_id,
    validate_required_fields,
    validate_tour_id,
    validate_iso_datetime,
    ValidationError,
)
from models import CheckInMethod, SELF_SERVICE_METHOD
from checkin_service import create_checkin
from rbac import Permission, require_permission

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)


@api_handler("Failed to create check-in")
def lambda_handler(event, context):
    """
    Create a check-in record

    Path Parameters:
        tourId: Tour identifier

    Body:
        riderId: Rider ID (required)
        rideId: Ride ID (required)
        method: Check-in method (QR_SCAN, MANUAL, FALLBACK)
        stageNumber: Stage number (required for normal check-ins; optional for Not Riding/Quit Riding)
        isNotRiding: Not Riding flag (default: false)
        isFloat: Float status flag (default: false)
        floatNo: Float number (required when isFloat=true)
        isQuitRiding: Quit Riding flag (default: false)
        timestamp: Optional ISO 8601 timestamp for offline-synced check-ins
        notes: Optional notes
    """
    try:
        log_event(logger, event)

        # Enforce RBAC — CHECKIN permission required; GUEST may not create check-ins
        deny = require_permission(event, Permission.CHECKIN)
        if deny:
            return deny

        # Extract tour ID from path parameters
        tour_id = event.get("pathParameters", {}).get("tourId")

        if not tour_id:
            return bad_request_response("tourId is required in path")

        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        # Parse request body
        try:
            body = json.loads(event.get("body", "{}"))
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")

        # Validate required fields
        try:
            validate_required_fields(body, ["riderId", "rideId", "method"])
        except ValidationError as e:
            return bad_request_response(str(e))

        rider_id = body["riderId"]
        ride_id = body["rideId"]
        method = body["method"]
        is_not_riding = body.get("isNotRiding", False)
        is_float = body.get("isFloat", False)
        float_no = body.get("floatNo")
        is_quit_riding = body.get("isQuitRiding", False)
        notes = body.get("notes")
        client_timestamp = body.get(
            "timestamp"
        )  # Optional: for offline-synced check-ins

        if not isinstance(is_float, bool):
            return bad_request_response("isFloat must be a boolean")

        status_flags = [is_not_riding, is_float, is_quit_riding]
        if sum(1 for flag in status_flags if bool(flag)) > 1:
            return bad_request_response(
                "isNotRiding, isFloat and isQuitRiding are mutually exclusive"
            )

        if is_float:
            if float_no is None:
                return bad_request_response("floatNo is required when isFloat is true")

            try:
                float_no = int(float_no)
            except (TypeError, ValueError):
                return bad_request_response(
                    f"Invalid floatNo: {body.get('floatNo')}. Must be a valid integer"
                )

            if float_no <= 0:
                return bad_request_response("floatNo must be a positive integer")
        elif float_no is not None:
            return bad_request_response("floatNo is only allowed when isFloat is true")

        # Validate client-supplied timestamp if provided
        if client_timestamp:
            try:
                validate_iso_datetime(client_timestamp, "timestamp")
            except ValidationError as e:
                return bad_request_response(str(e))

        # Validate inputs
        try:
            validate_rider_id(rider_id)
            validate_ride_id(ride_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        # Validate method. SELF_SERVICE is reserved for Rider API self check-ins.
        if method == SELF_SERVICE_METHOD:
            return validation_error_response(
                "method SELF_SERVICE is reserved for rider self check-ins "
                "(POST /v1/tours/{tourId}/rides/{rideId}/self-checkins)"
            )
        try:
            CheckInMethod(method)
        except ValueError:
            valid_methods = [
                m.value for m in CheckInMethod if m.value != SELF_SERVICE_METHOD
            ]
            return bad_request_response(
                f"Invalid method. Must be one of: {', '.join(valid_methods)}"
            )

        # MANUAL check-ins require CHECKIN_MANUAL permission (elevated privilege)
        if method == CheckInMethod.MANUAL.value:
            deny = require_permission(
                event,
                Permission.CHECKIN_MANUAL,
                "Manual check-ins require elevated permissions",
            )
            if deny:
                return deny

        logger.info(
            "Creating check-in: rider=%s, ride=%s, isNotRiding=%s, isFloat=%s, isQuitRiding=%s",
            rider_id,
            ride_id,
            is_not_riding,
            is_float,
            is_quit_riding,
        )

        # Get checked-in-by from request context (JWT authorizer)
        checked_in_by = (
            event.get("requestContext", {})
            .get("authorizer", {})
            .get("jwt", {})
            .get("claims", {})
            .get("sub", "system")
        )

        # Shared validation and write (also used by rider self check-in)
        return create_checkin(
            event,
            tour_id=tour_id,
            ride_id=ride_id,
            rider_id=rider_id,
            method=method,
            checked_in_by=checked_in_by,
            stage_number_input=body.get("stageNumber"),
            is_not_riding=is_not_riding,
            is_float=is_float,
            float_no=float_no,
            is_quit_riding=is_quit_riding,
            client_timestamp=client_timestamp,
            notes=notes,
        )

    except json.JSONDecodeError:
        return bad_request_response("Invalid JSON in request body")
