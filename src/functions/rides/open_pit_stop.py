"""
Lambda function to open a PIT_STOP stage for a started ride.

Uses tour-specific Ride-{tourId} table.
Route: POST /v1/tours/{tourId}/rides/{rideId}/stages/{stageNumber}/pitstop/open
"""

import sys

sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, error_response, bad_request_response, internal_error_response
from validation import validate_tour_id, validate_ride_id, ValidationError
from dynamodb_utils import get_tour_item, put_tour_item
from models import RideStatus, StageType, PitStopStatus, utc_now_iso
from rbac import require_permission, require_pit_stop_stage_access, Permission

logger = get_logger(__name__)


def _parse_stage_number(stage_number_raw):
    """Parse and validate stageNumber path parameter."""
    try:
        stage_number = int(stage_number_raw)
    except (TypeError, ValueError):
        raise ValidationError(
            f"Invalid stage number: {stage_number_raw}. Must be a non-negative integer",
            {"field": "stageNumber", "value": stage_number_raw}
        )

    if stage_number < 0:
        raise ValidationError(
            f"Invalid stage number: {stage_number}. Must be a non-negative integer",
            {"field": "stageNumber", "value": stage_number}
        )
    return stage_number


def lambda_handler(event, context):
    """Open a pit stop stage for a started ride."""
    try:
        deny = require_permission(event, Permission.PIT_STOP_MANAGE)
        if deny:
            return deny

        path_params = event.get('pathParameters', {})
        tour_id = path_params.get('tourId')
        ride_id = path_params.get('rideId')
        stage_number_raw = path_params.get('stageNumber')

        if not tour_id or not ride_id or stage_number_raw is None:
            return bad_request_response("tourId, rideId, and stageNumber are required in path")

        try:
            validate_tour_id(tour_id)
            validate_ride_id(ride_id)
            stage_number = _parse_stage_number(stage_number_raw)
        except ValidationError as e:
            return bad_request_response(str(e))

        ride = get_tour_item(
            table_type='Ride',
            tour_id=tour_id,
            key={'rideId': ride_id}
        )
        if not ride:
            return error_response('RIDE_NOT_FOUND', f"Ride '{ride_id}' not found", status_code=404)

        if ride.get('status') != RideStatus.STARTED.value:
            return bad_request_response("Pit stop can be opened only when ride status is STARTED")

        stage = next((item for item in ride.get('stages', []) if item.get('stageNumber') == stage_number), None)
        if not stage:
            return error_response(
                'STAGE_NOT_FOUND',
                f"Stage '{stage_number}' not found in ride '{ride_id}'",
                status_code=404
            )

        if stage.get('type') != StageType.PIT_STOP.value:
            return bad_request_response("Pit stop open is applicable only to PIT_STOP stages")

        deny = require_pit_stop_stage_access(event, stage_number)
        if deny:
            return deny

        if stage.get('pitStopStatus') == PitStopStatus.OPEN.value:
            return bad_request_response("Pit stop is already OPEN")

        if stage.get('pitStopStatus') == PitStopStatus.CLOSED.value:
            return bad_request_response("Pit stop is already CLOSED")

        now = utc_now_iso()
        stage['pitStopStatus'] = PitStopStatus.OPEN.value
        stage['openedAt'] = now
        ride['updatedAt'] = now

        put_tour_item(table_type='Ride', tour_id=tour_id, item=ride)
        return success_response(ride)

    except Exception as e:
        logger.error(f"Error opening pit stop: {str(e)}", exc_info=True)
        return internal_error_response("Failed to open pit stop")