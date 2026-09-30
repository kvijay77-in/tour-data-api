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
sys.path.insert(0, '/opt/python')

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
from models import CheckInStatus, utc_now_iso
from notification_service import notify
from dynamodb_utils import get_tour_item, update_tour_item, query_tour_items, get_item
from rbac import Permission, require_permission
from ownership import resolve_profile_id_for_sub
from self_checkin import effective_self_checkin_allowed, effective_not_riding_allowed

logger = get_logger(__name__)


def lambda_handler(event, context):
    """Cancel an existing check-in record using special status-driven behavior."""
    try:
        self_service = bool(event.get('_self_service'))
        deny = require_permission(
            event,
            Permission.SELF_CHECKIN if self_service else Permission.CHECKIN,
        )
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

        if self_service:
            if existing.get('isQuitRiding'):
                return error_response(
                    'QUIT_RIDING_CANCEL_NOT_ALLOWED',
                    'Quit Riding check-ins can only be cancelled by management users.',
                    status_code=403,
                )
            claims = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
            profile_id = resolve_profile_id_for_sub(claims.get('sub', ''))
            linked = query_tour_items(
                table_type='TourRider', tour_id=tour_id,
                key_condition_expression='profileId = :profileId',
                expression_values={':profileId': profile_id},
                index_name='ProfileIdIndex',
            ) if profile_id else []
            if not linked or linked[0].get('riderId') != existing.get('riderId'):
                return error_response('FORBIDDEN', 'Riders may only cancel their own check-ins.', status_code=403)
            ride = get_tour_item('Ride', tour_id, {'rideId': ride_id}) or {}
            tour = get_item('TOUR_MASTER_TABLE', {'tourId': tour_id}) or {}
            if existing.get('isNotRiding'):
                stage = next((s for s in ride.get('stages', []) if s.get('type') == 'START'), None)
                allowed = bool(stage and effective_not_riding_allowed(stage))
            elif existing.get('stageNumber') is not None:
                stage = next(
                    (s for s in ride.get('stages', []) if s.get('stageNumber') == existing.get('stageNumber')),
                    None,
                )
                allowed = bool(stage and effective_self_checkin_allowed(tour, ride, stage))
            else:
                allowed = False
            if not allowed:
                return error_response('SELF_CHECKIN_NOT_ALLOWED', 'Self check-in cancellation is not allowed for this record.', status_code=403)
            body = {
                'status': CheckInStatus.CANCELLED.value,
                'prevStatus': existing.get('status', 'CHECKED_IN'),
            }

        cancelled_by = event.get('requestContext', {}).get(
            'authorizer', {}
        ).get('jwt', {}).get('claims', {}).get('sub', 'system')
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
            }
            ,
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

        return success_response(updated)

    except Exception as e:
        logger.error(f"Error cancelling check-in: {str(e)}", exc_info=True)
        return internal_error_response("Failed to cancel check-in")
