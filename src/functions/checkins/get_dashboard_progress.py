"""
Get dashboard progress Lambda function.

Returns lightweight dashboard refresh payload:
- rideId
- checkIns
- cancelled
- summary
- dataVersion

Uses tour-specific tables: Ride-{tourId}, TourRider-{tourId}, CheckIn-{tourId}
Route: GET /v1/tours/{tourId}/rides/{rideId}/dashboard/progress
"""

import sys

import hashlib
import json

from logger import get_logger, log_event
from response import (
    success_response,
    not_found_response,
    bad_request_response,
    not_modified_response,
    DecimalEncoder,
)
from handler_utils import api_handler
from dynamodb_utils import get_tour_item, query_tour_items, scan_tour_items
from validation import validate_tour_id, validate_ride_id, ValidationError
from rbac import require_permission, Permission
from models import is_cancelled_checkin_item

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)


def _build_summary(tour_riders, check_ins):
    rider_ids = {rider.get("riderId") for rider in tour_riders if rider.get("riderId")}
    checked_in_riders = set()
    not_riding_riders = set()
    quit_riding_riders = set()

    for checkin in check_ins:
        rider_id = checkin.get("riderId")
        if not rider_id:
            continue

        if checkin.get("isNotRiding"):
            not_riding_riders.add(rider_id)
        elif checkin.get("isQuitRiding"):
            quit_riding_riders.add(rider_id)
        else:
            checked_in_riders.add(rider_id)

    return {
        "totalRiders": len(rider_ids),
        "checkedIn": len(checked_in_riders),
        "notRiding": len(not_riding_riders),
        "quitRiding": len(quit_riding_riders),
        "notCheckedIn": (
            len(rider_ids)
            - len(checked_in_riders)
            - len(not_riding_riders)
            - len(quit_riding_riders)
        ),
    }


def _compute_data_version(ride, tour_riders, check_ins):
    candidates = []

    for value in (ride.get("updatedAt"), ride.get("createdAt")):
        if value:
            candidates.append(value)

    for rider in tour_riders:
        for field_name in ("updatedAt", "createdAt", "registeredAt"):
            value = rider.get(field_name)
            if value:
                candidates.append(value)

    for checkin in check_ins:
        for field_name in ("timestamp", "updatedAt", "createdAt", "cancelledAt"):
            value = checkin.get(field_name)
            if value:
                candidates.append(value)

    if not candidates:
        return "1970-01-01T00:00:00Z"

    return max(candidates)


@api_handler("Failed to retrieve dashboard progress")
def lambda_handler(event, context):
    """Get lightweight dashboard progress for a ride."""
    log_event(logger, event)

    tour_id = event.get("pathParameters", {}).get("tourId")
    ride_id = event.get("pathParameters", {}).get("rideId")

    deny = require_permission(event, Permission.DASHBOARD)
    if deny:
        return deny

    if not tour_id or not ride_id:
        return bad_request_response("tourId and rideId are required in path")

    try:
        validate_tour_id(tour_id)
        validate_ride_id(ride_id)
    except ValidationError as e:
        return bad_request_response(str(e))

    ride = get_tour_item(
        table_type="Ride",
        tour_id=tour_id,
        key={"rideId": ride_id},
    )
    if not ride:
        return not_found_response("Ride", ride_id)

    tour_riders = scan_tour_items(
        table_type="TourRider",
        tour_id=tour_id,
    )

    all_check_ins = query_tour_items(
        table_type="CheckIn",
        tour_id=tour_id,
        key_condition_expression="rideId = :rid",
        expression_values={":rid": ride_id},
    )

    cancelled = [
        checkin for checkin in all_check_ins if is_cancelled_checkin_item(checkin)
    ]
    check_ins = [
        checkin for checkin in all_check_ins if not is_cancelled_checkin_item(checkin)
    ]

    summary = _build_summary(tour_riders, check_ins)
    data_version = _compute_data_version(ride, tour_riders, all_check_ins)

    payload = {
        "rideId": ride_id,
        "checkIns": check_ins,
        "cancelled": cancelled,
        "summary": summary,
        "dataVersion": data_version,
    }

    payload_json = json.dumps(payload, sort_keys=True, cls=DecimalEncoder)
    etag = f'"{hashlib.md5(payload_json.encode()).hexdigest()}"'

    request_headers = event.get("headers", {}) or {}
    if_none_match = request_headers.get("if-none-match") or request_headers.get(
        "If-None-Match"
    )
    if if_none_match and if_none_match == etag:
        response = not_modified_response()
        response["headers"]["ETag"] = etag
        return response

    response = success_response(payload)
    response["headers"]["ETag"] = etag
    return response
