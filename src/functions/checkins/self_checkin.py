"""
Rider self check-in Lambda function (Rider API only).

Route: POST /v1/tours/{tourId}/rides/{rideId}/self-checkins

The rider ID always comes from the caller's login (Cognito user -> rider link ->
profileId -> TourRider row). The check-in is stored through the shared
check-in function with method SELF_SERVICE and checkedInBy = rider profileId.
"""

import sys

import json

from logger import get_logger, log_event
from response import bad_request_response, validation_error_response
from handler_utils import api_handler
from validation import validate_iso_datetime, validate_ride_id, validate_tour_id, ValidationError
from models import SELF_SERVICE_METHOD
from checkin_service import create_checkin
from rbac import Permission, require_permission
from rider_identity import reject_client_rider_id
from self_checkin_rules import check_self_checkin_request, load_self_checkin_context

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)

ALLOWED_BODY_FIELDS = {'stageNumber', 'isNotRiding', 'isQuitRiding', 'timestamp', 'notes'}


def _parse_request(body):
    """Validate the body. Returns (stage_number, is_not_riding, is_quit_riding, timestamp, notes)."""
    unknown = sorted(set(body) - ALLOWED_BODY_FIELDS)
    if unknown:
        raise ValidationError(
            f"Unsupported field(s): {', '.join(unknown)}. Allowed: stageNumber, isNotRiding, isQuitRiding, timestamp, notes",
            {'fields': unknown},
        )

    stage_number = body.get('stageNumber')
    if 'stageNumber' in body and (isinstance(stage_number, bool) or not isinstance(stage_number, int)):
        raise ValidationError('stageNumber must be an integer', {'field': 'stageNumber'})

    for flag in ('isNotRiding', 'isQuitRiding'):
        if flag in body and body[flag] is not True:
            raise ValidationError(f"{flag} may only be sent as true", {'field': flag})

    choices = [name for name in ('stageNumber', 'isNotRiding', 'isQuitRiding') if name in body]
    if len(choices) != 1:
        raise ValidationError(
            'Send exactly one of stageNumber, isNotRiding: true or isQuitRiding: true',
            {'fields': choices},
        )

    timestamp = body.get('timestamp')
    if timestamp is not None:
        if not isinstance(timestamp, str):
            raise ValidationError('timestamp must be an ISO 8601 UTC string', {'field': 'timestamp'})
        validate_iso_datetime(timestamp, 'timestamp')

    notes = body.get('notes')
    if notes is not None and not isinstance(notes, str):
        raise ValidationError('notes must be a string', {'field': 'notes'})

    return stage_number, body.get('isNotRiding') is True, body.get('isQuitRiding') is True, timestamp, notes


@api_handler('Failed to create self check-in')
def lambda_handler(event, context):
    """
    Create a check-in for the calling rider.

    Body (exactly one of stageNumber / isNotRiding / isQuitRiding):
        stageNumber: Stage number to check in at (integer)
        isNotRiding: true to self-report Not Riding
        isQuitRiding: true to self-report Quit Riding
        timestamp: Optional ISO 8601 UTC timestamp (default: server time)
        notes: Optional notes

    Returns 201 with the created check-in (same shape as the Mgmt create check-in).
    """
    log_event(logger, event)

    deny = require_permission(event, Permission.SELF_CHECKIN)
    if deny:
        return deny

    path_params = event.get('pathParameters') or {}
    tour_id = path_params.get('tourId')
    ride_id = path_params.get('rideId')
    if not tour_id or not ride_id:
        return bad_request_response("tourId and rideId are required in path")
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

    try:
        stage_number, is_not_riding, is_quit_riding, timestamp, notes = _parse_request(body)
    except ValidationError as e:
        return validation_error_response(str(e), e.details)

    # Checks 1-4: tour ACTIVE, caller on the tour, ride is today's and OPEN/STARTED
    self_context, error = load_self_checkin_context(event, tour_id, ride_id)
    if error:
        return error

    # Checks 5-8: quit, stage permission / pit stop open, Not Riding, Quit Riding
    error = check_self_checkin_request(self_context, tour_id, stage_number, is_not_riding, is_quit_riding)
    if error:
        return error

    identity = self_context['identity']
    # Check 9: all existing check-in rules through the shared create function
    return create_checkin(
        event,
        tour_id=tour_id,
        ride_id=ride_id,
        rider_id=identity['riderId'],
        method=SELF_SERVICE_METHOD,
        checked_in_by=identity['profileId'],
        stage_number_input=stage_number,
        is_not_riding=is_not_riding,
        is_quit_riding=is_quit_riding,
        client_timestamp=timestamp,
        notes=notes,
        ride=self_context['ride'],
    )
