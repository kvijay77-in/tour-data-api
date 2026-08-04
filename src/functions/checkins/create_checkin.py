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
Route: POST /v1/tours/{tourId}/checkins
"""

import sys
sys.path.insert(0, '/opt/python')

import json
import uuid

from logger import get_logger, log_event
from response import (
    success_response, error_response, conflict_response,
    bad_request_response, not_found_response, internal_error_response
)
from dynamodb_utils import get_tour_item, query_tour_items, put_tour_item
from validation import (
    validate_rider_id,
    validate_ride_id,
    validate_required_fields,
    validate_tour_id,
    validate_stage_number,
    validate_iso_datetime,
    ValidationError
)
from models import (
    CheckIn,
    CheckInMethod,
    RideStatus,
    StageType,
    is_cancelled_checkin_item,
    utc_now_iso,
)
from rbac import (
    Permission,
    get_user_pit_stop_stage_numbers,
    has_non_pit_stop_checkin_access,
    require_permission,
)

logger = get_logger(__name__)


def _read_value(item, camel_key, snake_key=None, default=None):
    """Read a value from an item with camelCase-first fallback to snake_case."""
    if camel_key in item:
        return item.get(camel_key)
    if snake_key and snake_key in item:
        return item.get(snake_key)
    return default


def _normalize_keys_to_camel_case(payload):
    """Normalize known legacy snake_case check-in keys to camelCase recursively."""
    key_map = {
        'check_in_id': 'checkInId',
        'rider_id': 'riderId',
        'ride_id': 'rideId',
        'checked_in_by': 'checkedInBy',
        'stage_number': 'stageNumber',
        'stage_id': 'stageId',
        'is_not_riding': 'isNotRiding',
        'is_float': 'isFloat',
        'float_no': 'floatNo',
        'is_quit_riding': 'isQuitRiding',
        'is_manual_entry': 'isManualEntry',
        'created_at': 'createdAt',
    }

    if isinstance(payload, list):
        return [_normalize_keys_to_camel_case(item) for item in payload]

    if isinstance(payload, dict):
        normalized = {}
        for key, value in payload.items():
            normalized_key = key_map.get(key, key)
            normalized[normalized_key] = _normalize_keys_to_camel_case(value)
        return normalized

    return payload


def _authorize_pit_stop_role_checkin(
    event,
    stage_number,
    stage_type,
    is_not_riding,
    is_quit_riding,
):
    """Enforce stage-aware check-in access for pit-stop-only users."""
    assigned_stage_numbers = get_user_pit_stop_stage_numbers(event)
    if not assigned_stage_numbers:
        return None

    if has_non_pit_stop_checkin_access(event):
        return None

    if is_quit_riding:
        return None

    if is_not_riding:
        return error_response(
            error_code="PIT_STOP_ROLE_STAGE_MISMATCH",
            message="Pit stop users may only perform Quit Riding or assigned PIT_STOP regular check-ins.",
            status_code=403
        )

    if stage_type != StageType.PIT_STOP.value:
        return error_response(
            error_code="PIT_STOP_ROLE_STAGE_MISMATCH",
            message="Pit stop users may only perform regular check-ins for PIT_STOP stages.",
            status_code=403
        )

    if stage_number not in assigned_stage_numbers:
        return error_response(
            error_code="PIT_STOP_ROLE_STAGE_MISMATCH",
            message=(
                f"Pit stop user is not authorized for stage {stage_number}. "
                f"Assigned stages: {sorted(assigned_stage_numbers)}"
            ),
            status_code=403
        )

    return None


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
            validate_required_fields(body, ['riderId', 'rideId', 'method'])
        except ValidationError as e:
            return bad_request_response(str(e))
        
        rider_id = body['riderId']
        ride_id = body['rideId']
        method = body['method']
        is_not_riding = body.get('isNotRiding', False)
        is_float = body.get('isFloat', False)
        float_no = body.get('floatNo')
        is_quit_riding = body.get('isQuitRiding', False)
        notes = body.get('notes')
        client_timestamp = body.get('timestamp')  # Optional: for offline-synced check-ins
        stage_number = None
        stage_type = None

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
                validate_iso_datetime(client_timestamp, 'timestamp')
            except ValidationError as e:
                return bad_request_response(str(e))
        
        # Validate inputs
        try:
            validate_rider_id(rider_id)
            validate_ride_id(ride_id)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Validate method
        try:
            CheckInMethod(method)
        except ValueError:
            valid_methods = [m.value for m in CheckInMethod]
            return bad_request_response(
                f"Invalid method. Must be one of: {', '.join(valid_methods)}"
            )
        
        # MANUAL check-ins require CHECKIN_MANUAL permission (elevated privilege)
        if method == CheckInMethod.MANUAL.value:
            deny = require_permission(
                event,
                Permission.CHECKIN_MANUAL,
                "Manual check-ins require elevated permissions"
            )
            if deny:
                return deny
        
        logger.info(
            f"Creating check-in: rider={rider_id}, ride={ride_id}, "
            f"isNotRiding={is_not_riding}, isFloat={is_float}, "
            f"isQuitRiding={is_quit_riding}"
        )
        
        # Step 1: Get ride details from tour-specific Ride table
        ride = get_tour_item(
            table_type='Ride',
            tour_id=tour_id,
            key={'rideId': ride_id}
        )
        
        if not ride:
            return not_found_response("Ride", ride_id)
        
        # Check if ride is closed
        if ride.get('status') == RideStatus.CLOSED.value:
            closed_at = ride.get('closedAt')
            # Allow late-sync: accept check-ins captured before ride was closed
            if client_timestamp and closed_at and client_timestamp < closed_at:
                logger.info(
                    f"Late-sync accepted: check-in timestamp {client_timestamp} "
                    f"predates ride closure {closed_at}"
                )
            else:
                return error_response(
                    error_code="RIDE_CLOSED",
                    message=f"Ride {ride_id} is closed. No further check-ins allowed.",
                    status_code=409
                )
        
        # Validate stage number only for normal check-ins.
        # Not Riding / Quit Riding entries do not require stage attributes.
        stages = ride.get('stages', [])
        total_stages = len(stages)
        stage_id = None
        requires_stage = not is_not_riding and not is_quit_riding

        if requires_stage:
            if 'stageNumber' not in body or body.get('stageNumber') is None:
                return bad_request_response(
                    "stageNumber is required for normal check-ins"
                )

            try:
                stage_number = int(body['stageNumber'])
            except (TypeError, ValueError):
                return bad_request_response(
                    f"Invalid stageNumber: {body.get('stageNumber')}. Must be a valid integer"
                )

            try:
                validate_stage_number(stage_number, total_stages)
            except ValidationError as e:
                return bad_request_response(str(e))

            stage = stages[stage_number]
            stage_id = stage.get('stageId')
            stage_type = stage.get('type')
        
        # Step 2: Verify rider is registered for this tour
        tour_rider = get_tour_item(
            table_type='TourRider',
            tour_id=tour_id,
            key={'riderId': rider_id}
        )
        
        if not tour_rider:
            return error_response(
                error_code="RIDER_NOT_IN_TOUR",
                message=f"Rider {rider_id} is not registered for this tour",
                status_code=400
            )

        deny = _authorize_pit_stop_role_checkin(
            event,
            stage_number=stage_number,
            stage_type=stage_type,
            is_not_riding=is_not_riding,
            is_quit_riding=is_quit_riding,
        )
        if deny:
            return deny
        
        # Step 3: Check for existing check-ins (business rules)
        existing_checkins = query_tour_items(
            table_type='CheckIn',
            tour_id=tour_id,
            key_condition_expression='rideId = :rid AND begins_with(checkInId, :prefix)',
            expression_values={
                ':rid': ride_id,
                ':prefix': f'{rider_id}#'
            }
        )
        active_checkins = [
            checkin for checkin in existing_checkins
            if not is_cancelled_checkin_item(checkin)
        ]
        
        # Check for Not Riding conflicts
        if is_not_riding:
            nr_checkins = [
                c for c in active_checkins
                if _read_value(c, 'isNotRiding', 'is_not_riding', False)
            ]
            if nr_checkins:
                return conflict_response(
                    f"Rider {rider_id} already marked as Not Riding for this ride",
                    error_code="DUPLICATE_NOT_RIDING"
                )
        
        # Check if rider already marked as Not Riding (can't check in normally)
        if not is_not_riding and not is_quit_riding:
            nr_checkins = [
                c for c in active_checkins
                if _read_value(c, 'isNotRiding', 'is_not_riding', False)
            ]
            if nr_checkins:
                return conflict_response(
                    f"Rider {rider_id} is marked as Not Riding. Cannot check in.",
                    error_code="RIDER_NOT_RIDING"
                )
        
        # Check if rider already quit (latest check-in has isQuitRiding=true)
        if active_checkins:
            sorted_checkins = sorted(
                active_checkins,
                key=lambda x: _read_value(x, 'timestamp', default=''),
                reverse=True
            )
            latest_qr = next(
                (
                    c for c in sorted_checkins
                    if _read_value(c, 'isQuitRiding', 'is_quit_riding', False)
                ),
                None
            )
            if latest_qr:
                qr_timestamp = _read_value(latest_qr, 'timestamp', default='')
                # Timestamp-based validation: accept if check-in was captured
                # before the rider quit (supports offline-synced check-ins)
                if client_timestamp and client_timestamp < qr_timestamp:
                    logger.info(
                        f"Timestamp-based acceptance: check-in at {client_timestamp} "
                        f"predates quit-riding at {qr_timestamp} for rider {rider_id}"
                    )
                else:
                    return conflict_response(
                        f"Rider {rider_id} has quit riding. No further check-ins allowed.",
                        error_code="RIDER_QUIT_RIDING"
                    )
        
        # Check for duplicate check-in (same rider + same stage, normal check-ins only)
        if not is_not_riding and not is_quit_riding:
            duplicate = next(
                (c for c in active_checkins
                 if _read_value(c, 'stageNumber', 'stage_number') == stage_number
                 and not _read_value(c, 'isNotRiding', 'is_not_riding', False)
                 and not _read_value(c, 'isQuitRiding', 'is_quit_riding', False)),
                None
            )
            if duplicate:
                return conflict_response(
                    f"Rider {rider_id} already checked in at stage {stage_number}",
                    error_code="DUPLICATE_CHECKIN"
                )
        
        # Step 4: Create check-in record
        # Use client-supplied timestamp for offline-synced check-ins, otherwise server time
        timestamp = client_timestamp if client_timestamp else utc_now_iso()
        check_in_id = str(uuid.uuid4())
        
        # Get checked-in-by from request context (JWT authorizer)
        checked_in_by = event.get('requestContext', {}).get(
            'authorizer', {}
        ).get('jwt', {}).get('claims', {}).get('sub', 'system')
        
        checkin = CheckIn(
            checkInId=check_in_id,
            riderId=rider_id,
            rideId=ride_id,
            timestamp=timestamp,
            checkedInBy=checked_in_by,
            method=CheckInMethod(method),
            stageNumber=stage_number,
            stageId=stage_id,
            isNotRiding=is_not_riding,
            isFloat=is_float,
            floatNo=float_no,
            isQuitRiding=is_quit_riding,
            isManualEntry=(method == CheckInMethod.MANUAL.value),
            notes=notes
        )

        # Enforce camelCase storage/response keys even if legacy serializers emit snake_case.
        checkin_item = _normalize_keys_to_camel_case(checkin.to_dynamodb_item())
        checkin_response = _normalize_keys_to_camel_case(checkin.to_dict())
        
        # Save to tour-specific CheckIn table
        put_tour_item(
            table_type='CheckIn',
            tour_id=tour_id,
            item=checkin_item
        )
        
        logger.info(f"Check-in created successfully: {check_in_id}")
        return success_response(checkin_response, status_code=201)
    
    except json.JSONDecodeError:
        return bad_request_response("Invalid JSON in request body")
    except Exception as e:
        logger.error(f"Error creating check-in: {str(e)}", exc_info=True)
        return internal_error_response("Failed to create check-in")
