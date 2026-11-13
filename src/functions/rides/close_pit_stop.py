"""
Lambda function to close a PIT_STOP stage for a started ride.

Uses tour-specific Ride-{tourId} table.
Route: POST /v1/tours/{tourId}/rides/{rideId}/stages/{stageNumber}/pitstop/close
"""

import sys

from logger import get_logger
from response import success_response, error_response, bad_request_response
from handler_utils import api_handler
from validation import validate_tour_id, validate_ride_id, ValidationError
from dynamodb_utils import get_tour_item, put_tour_item
from models import RideStatus, StageType, PitStopStatus, utc_now_iso
from notification_service import notify
from rbac import require_permission, require_pit_stop_stage_access, Permission

sys.path.insert(0, "/opt/python")
logger = get_logger(__name__)


def _parse_stage_number(stage_number_raw):
    """Parse and validate stageNumber path parameter."""
    try:
        stage_number = int(stage_number_raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Invalid stage number: {stage_number_raw}. Must be a non-negative integer",
            {"field": "stageNumber", "value": stage_number_raw},
        ) from exc

    if stage_number < 0:
        raise ValidationError(
            f"Invalid stage number: {stage_number}. Must be a non-negative integer",
            {"field": "stageNumber", "value": stage_number},
        )
    return stage_number


@api_handler("Failed to close pit stop")
def lambda_handler(event, context):
    """Close a pit stop stage for a started ride."""
    deny = require_permission(event, Permission.PIT_STOP_MANAGE)
    if deny:
        return deny

    path_params = event.get("pathParameters", {})
    tour_id = path_params.get("tourId")
    ride_id = path_params.get("rideId")
    stage_number_raw = path_params.get("stageNumber")

    if not tour_id or not ride_id or stage_number_raw is None:
        return bad_request_response(
            "tourId, rideId, and stageNumber are required in path"
        )

    try:
        validate_tour_id(tour_id)
        validate_ride_id(ride_id)
        stage_number = _parse_stage_number(stage_number_raw)
    except ValidationError as e:
        return bad_request_response(str(e))

    ride = get_tour_item(table_type="Ride", tour_id=tour_id, key={"rideId": ride_id})
    if not ride:
        return error_response(
            "RIDE_NOT_FOUND", f"Ride '{ride_id}' not found", status_code=404
        )

    if ride.get("status") != RideStatus.STARTED.value:
        return bad_request_response(
            "Pit stop can be closed only when ride status is STARTED"
        )

    stage = next(
        (
            item
            for item in ride.get("stages", [])
            if item.get("stageNumber") == stage_number
        ),
        None,
    )
    if not stage:
        return error_response(
            "STAGE_NOT_FOUND",
            f"Stage '{stage_number}' not found in ride '{ride_id}'",
            status_code=404,
        )

    if stage.get("type") != StageType.PIT_STOP.value:
        return bad_request_response(
            "Pit stop close is applicable only to PIT_STOP stages"
        )

    deny = require_pit_stop_stage_access(event, stage_number)
    if deny:
        return deny

    if stage.get("pitStopStatus") == PitStopStatus.CLOSED.value:
        return bad_request_response("Pit stop is already CLOSED")

    if stage.get("pitStopStatus") != PitStopStatus.OPEN.value:
        return bad_request_response("Pit stop must be OPEN before it can be closed")

    now = utc_now_iso()
    stage["pitStopStatus"] = PitStopStatus.CLOSED.value
    stage["closedAt"] = now
    ride["updatedAt"] = now

    put_tour_item(table_type="Ride", tour_id=tour_id, item=ride)
    notify(
        rule_id="PIT_STOP_CLOSED",
        tour_id=tour_id,
        context={"rideId": ride_id, "stageNumber": stage_number},
        actor=event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
        .get("sub"),
    )
    return success_response(ride)
