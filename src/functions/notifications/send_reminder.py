import sys

from notification_common import get_jwt_claim, parse_json_body
from dynamodb_utils import get_tour_item, query_tour_items, scan_tour_items
from logger import get_logger, log_event
from models import TourRiderStatus, is_cancelled_checkin_item
from notification_service import notify
from rbac import Permission, require_permission
from response import bad_request_response, error_response, internal_error_response, success_response

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)

RIDE_REMINDER = 'RIDE_CHECKIN_NOT_STARTED'
EVENT_REMINDER = 'EVENT_CHECKIN_NOT_STARTED'


def _eligible_rider_ids(tour_id):
    rows = scan_tour_items('TourRider', tour_id)
    eligible = []
    for row in rows:
        if row.get('status') in {TourRiderStatus.REGISTERED.value, TourRiderStatus.ACTIVE.value}:
            rider_id = row.get('riderId')
            if rider_id:
                eligible.append(rider_id)
    return eligible


def _ride_not_started_riders(tour_id, ride_id):
    checkins = query_tour_items(
        table_type='CheckIn',
        tour_id=tour_id,
        key_condition_expression='rideId = :rid',
        expression_values={':rid': ride_id},
    )
    started = set()
    for row in checkins:
        if is_cancelled_checkin_item(row):
            continue
        if bool(row.get('isNotRiding')) or bool(row.get('isQuitRiding')):
            continue
        if row.get('stageNumber') == 0:
            rider_id = row.get('riderId')
            if rider_id:
                started.add(rider_id)
    return [rider_id for rider_id in _eligible_rider_ids(tour_id) if rider_id not in started]


def _event_not_started_riders(tour_id, event_id, occurrence_id):
    event_definition = get_tour_item('Event', tour_id, {'eventId': event_id})
    if not event_definition:
        raise ValueError('Event not found')
    notification_cfg = event_definition.get('notificationConfig') or {}
    if not notification_cfg.get('reminderEnabled'):
        raise RuntimeError('Event definition does not allow reminders for this event')

    records = scan_tour_items('EventActivityLogs', tour_id)
    started = {
        row.get('riderId')
        for row in records
        if row.get('occurrenceId') == occurrence_id and not row.get('cancelledAt') and row.get('riderId')
    }
    return (
        [rider_id for rider_id in _eligible_rider_ids(tour_id) if rider_id not in started],
        notification_cfg.get('reminderRuleId'),
    )


def lambda_handler(event, context):
    try:
        log_event(logger, event)
        deny = require_permission(event, Permission.NOTIFICATION_MANAGE)
        if deny:
            return deny

        body = parse_json_body(event)
        reminder_type = body.get('reminderType')
        tour_id = body.get('tourId')
        if reminder_type not in {RIDE_REMINDER, EVENT_REMINDER}:
            return bad_request_response(f'reminderType must be one of: {RIDE_REMINDER}, {EVENT_REMINDER}')
        if not isinstance(tour_id, str) or not tour_id:
            return bad_request_response('tourId is required')

        actor = get_jwt_claim(event, 'sub', 'system')
        reminder_rule_id = body.get('ruleId')

        if reminder_type == RIDE_REMINDER:
            ride_id = body.get('rideId')
            if not isinstance(ride_id, str) or not ride_id:
                return bad_request_response('rideId is required for RIDE_CHECKIN_NOT_STARTED')
            target_riders = _ride_not_started_riders(tour_id, ride_id)
            rule_id = reminder_rule_id or 'RIDE_CHECKIN_REMINDER'
            context_payload = {'tourId': tour_id, 'rideId': ride_id}
        else:
            event_id = body.get('eventId')
            occurrence_id = body.get('occurrenceId')
            if not isinstance(event_id, str) or not event_id:
                return bad_request_response('eventId is required for EVENT_CHECKIN_NOT_STARTED')
            if not isinstance(occurrence_id, str) or not occurrence_id:
                return bad_request_response('occurrenceId is required for EVENT_CHECKIN_NOT_STARTED')
            try:
                target_riders, configured_rule = _event_not_started_riders(tour_id, event_id, occurrence_id)
            except ValueError:
                return error_response('EVENT_NOT_FOUND', 'Event not found.', status_code=404)
            except RuntimeError as exc:
                return error_response('REMINDER_NOT_ALLOWED', str(exc), status_code=409)
            rule_id = reminder_rule_id or configured_rule or 'EVENT_CHECKIN_REMINDER'
            context_payload = {'tourId': tour_id, 'eventId': event_id, 'occurrenceId': occurrence_id}

        if not target_riders:
            return success_response({'notificationId': None, 'targetCount': 0})

        audiences = [f'TOUR#{tour_id}#RIDER#{rider_id}' for rider_id in target_riders]
        notification_id = notify(
            rule_id=rule_id,
            tour_id=tour_id,
            context=context_payload,
            audience_override=audiences,
            actor=actor,
        )
        return success_response(
            {
                'notificationId': notification_id,
                'targetCount': len(target_riders),
                'riderIds': target_riders,
            }
        )
    except ValueError as exc:
        return bad_request_response(str(exc))
    except Exception as exc:
        logger.error('send reminder failed: %s', str(exc), exc_info=True)
        return internal_error_response('Failed to send reminder')
