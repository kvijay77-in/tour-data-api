"""
Shared ride check-in create and cancel logic.

Used by the Mgmt API handlers (``create_checkin.py`` / ``cancel_checkin.py``) and
by the Rider API self check-in handlers so that every check-in, whoever makes
it, goes through the same validation, storage format and notifications.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from dynamodb_utils import get_tour_item, put_tour_item, query_tour_items, update_tour_item
from logger import get_logger
from models import (
    CheckIn,
    CheckInMethod,
    CheckInStatus,
    RideStatus,
    StageType,
    is_cancelled_checkin_item,
    utc_now_iso,
)
from notification_service import notify
from rbac import get_user_pit_stop_stage_numbers, has_non_pit_stop_checkin_access
from response import (
    bad_request_response,
    conflict_response,
    error_response,
    not_found_response,
    success_response,
)
from validation import ValidationError, validate_stage_number


logger = get_logger(__name__)


def read_value(item, camel_key, snake_key=None, default=None):
    """Read a value from an item with camelCase-first fallback to snake_case."""
    if camel_key in item:
        return item.get(camel_key)
    if snake_key and snake_key in item:
        return item.get(snake_key)
    return default


def normalize_keys_to_camel_case(payload):
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
        return [normalize_keys_to_camel_case(item) for item in payload]

    if isinstance(payload, dict):
        normalized = {}
        for key, value in payload.items():
            normalized_key = key_map.get(key, key)
            normalized[normalized_key] = normalize_keys_to_camel_case(value)
        return normalized

    return payload


def authorize_pit_stop_role_checkin(event, stage_number, stage_type, is_not_riding, is_quit_riding):
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


def list_rider_ride_checkins(tour_id: str, ride_id: str, rider_id: str, include_cancelled: bool = False) -> List[Dict[str, Any]]:
    """Return the rider's check-ins for one ride (cancelled ones excluded by default)."""
    items = query_tour_items(
        table_type='CheckIn',
        tour_id=tour_id,
        key_condition_expression='riderId = :riderId',
        expression_values={':riderId': rider_id},
        index_name='RiderIdIndex',
    )
    items = [item for item in items if read_value(item, 'rideId', 'ride_id') == ride_id]
    if include_cancelled:
        return items
    return [item for item in items if not is_cancelled_checkin_item(item)]


def create_checkin(
    event: Dict[str, Any],
    tour_id: str,
    ride_id: str,
    rider_id: str,
    method: str,
    checked_in_by: str,
    stage_number_input: Any = None,
    is_not_riding: bool = False,
    is_float: bool = False,
    float_no: Optional[int] = None,
    is_quit_riding: bool = False,
    client_timestamp: Optional[str] = None,
    notes: Optional[str] = None,
    ride: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate and store one check-in, then send the CHECKIN_CREATED notification.

    Inputs must already be type-checked by the caller (flags, floatNo,
    timestamp format, IDs, method). Applies the ride-closed, stage, tour rider,
    pit-stop role, Not Riding, Quit Riding and duplicate rules and returns the
    API Gateway response (201 with the stored check-in on success).
    """
    stage_number = None
    stage_type = None

    if ride is None:
        ride = get_tour_item(table_type='Ride', tour_id=tour_id, key={'rideId': ride_id})
    if not ride:
        return not_found_response("Ride", ride_id)

    # Check if ride is closed
    if ride.get('status') == RideStatus.CLOSED.value:
        closed_at = ride.get('closedAt')
        # Allow late-sync: accept check-ins captured before ride was closed
        if client_timestamp and closed_at and client_timestamp < closed_at:
            logger.info(
                "Late-sync accepted: check-in timestamp %s predates ride closure %s", client_timestamp, closed_at
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
        if stage_number_input is None:
            return bad_request_response("stageNumber is required for normal check-ins")

        try:
            stage_number = int(stage_number_input)
        except (TypeError, ValueError):
            return bad_request_response(
                f"Invalid stageNumber: {stage_number_input}. Must be a valid integer"
            )

        try:
            validate_stage_number(stage_number, total_stages)
        except ValidationError as e:
            return bad_request_response(str(e))

        stage = stages[stage_number]
        stage_id = stage.get('stageId')
        stage_type = stage.get('type')

    # Verify rider is registered for this tour
    tour_rider = get_tour_item(table_type='TourRider', tour_id=tour_id, key={'riderId': rider_id})
    if not tour_rider:
        return error_response(
            error_code="RIDER_NOT_IN_TOUR",
            message=f"Rider {rider_id} is not registered for this tour",
            status_code=400
        )

    deny = authorize_pit_stop_role_checkin(
        event,
        stage_number=stage_number,
        stage_type=stage_type,
        is_not_riding=is_not_riding,
        is_quit_riding=is_quit_riding,
    )
    if deny:
        return deny

    # Check for existing check-ins (business rules)
    active_checkins = list_rider_ride_checkins(tour_id, ride_id, rider_id)

    # Check for Not Riding conflicts
    if is_not_riding:
        nr_checkins = [c for c in active_checkins if read_value(c, 'isNotRiding', 'is_not_riding', False)]
        if nr_checkins:
            return conflict_response(
                f"Rider {rider_id} already marked as Not Riding for this ride",
                error_code="DUPLICATE_NOT_RIDING"
            )

    # Check if rider already marked as Not Riding (can't check in normally)
    if not is_not_riding and not is_quit_riding:
        nr_checkins = [c for c in active_checkins if read_value(c, 'isNotRiding', 'is_not_riding', False)]
        if nr_checkins:
            return conflict_response(
                f"Rider {rider_id} is marked as Not Riding. Cannot check in.",
                error_code="RIDER_NOT_RIDING"
            )

    # Check if rider already quit (latest check-in has isQuitRiding=true)
    if active_checkins:
        sorted_checkins = sorted(
            active_checkins,
            key=lambda x: read_value(x, 'timestamp', default=''),
            reverse=True
        )
        latest_qr = next(
            (c for c in sorted_checkins if read_value(c, 'isQuitRiding', 'is_quit_riding', False)),
            None
        )
        if latest_qr:
            qr_timestamp = read_value(latest_qr, 'timestamp', default='')
            # Timestamp-based validation: accept if check-in was captured
            # before the rider quit (supports offline-synced check-ins)
            if client_timestamp and client_timestamp < qr_timestamp:
                logger.info(
                    "Timestamp-based acceptance: check-in at %s predates quit-riding at %s for rider %s", client_timestamp, qr_timestamp, rider_id
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
             if read_value(c, 'stageNumber', 'stage_number') == stage_number
             and not read_value(c, 'isNotRiding', 'is_not_riding', False)
             and not read_value(c, 'isQuitRiding', 'is_quit_riding', False)),
            None
        )
        if duplicate:
            return conflict_response(
                f"Rider {rider_id} already checked in at stage {stage_number}",
                error_code="DUPLICATE_CHECKIN"
            )

    # Use client-supplied timestamp for offline-synced check-ins, otherwise server time
    timestamp = client_timestamp if client_timestamp else utc_now_iso()
    check_in_id = str(uuid.uuid4())

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
    checkin_item = normalize_keys_to_camel_case(checkin.to_dynamodb_item())
    checkin_response = normalize_keys_to_camel_case(checkin.to_dict())

    put_tour_item(table_type='CheckIn', tour_id=tour_id, item=checkin_item)

    try:
        notify(
            rule_id='CHECKIN_CREATED',
            tour_id=tour_id,
            context={
                'tourId': tour_id,
                'riderId': rider_id,
                'rideId': ride_id,
                'stageNumber': stage_number,
                'checkInId': check_in_id,
                'status': checkin_response.get('status'),
                'timestamp': timestamp,
            },
            actor=checked_in_by,
        )
    except Exception as notify_exc:  # pragma: no cover - safeguard only
        logger.warning('check-in notification trigger failed: %s', str(notify_exc))

    logger.info("Check-in created successfully: %s", check_in_id)
    return success_response(checkin_response, status_code=201)


def cancel_checkin(
    tour_id: str,
    ride_id: str,
    existing: Dict[str, Any],
    prev_status: str,
    cancelled_by: str,
) -> Dict[str, Any]:
    """Mark a check-in cancelled (record kept) and send CHECKIN_CANCELLED.

    Only ``status``, ``prevStatus``, ``cancelledBy`` and ``cancelledAt`` change.
    Returns the full updated record.
    """
    checkin_id = existing.get('checkInId')
    cancelled_at = utc_now_iso()

    updated = update_tour_item(
        table_type='CheckIn',
        tour_id=tour_id,
        key={'rideId': ride_id, 'checkInId': checkin_id},
        update_expression=(
            'SET prevStatus = :prevStatus, '
            'cancelledBy = :cancelledBy, '
            'cancelledAt = :cancelledAt, '
            '#status = :status'
        ),
        expression_values={
            ':prevStatus': prev_status,
            ':cancelledBy': cancelled_by,
            ':cancelledAt': cancelled_at,
            ':status': CheckInStatus.CANCELLED.value,
        },
        expression_names={'#status': 'status'}
    )

    try:
        notify(
            rule_id='CHECKIN_CANCELLED',
            tour_id=tour_id,
            context={
                'tourId': tour_id,
                'riderId': existing.get('riderId'),
                'rideId': ride_id,
                'stageNumber': existing.get('stageNumber'),
                'checkInId': checkin_id,
                'status': CheckInStatus.CANCELLED.value,
                'cancelledAt': cancelled_at,
            },
            actor=cancelled_by,
        )
    except Exception as notify_exc:  # pragma: no cover - safeguard only
        logger.warning('cancel check-in notification trigger failed: %s', str(notify_exc))

    return updated
