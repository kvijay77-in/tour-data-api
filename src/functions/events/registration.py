"""Event occurrence registration for riders and management users."""

import json
import sys
from datetime import datetime, timezone
sys.path.insert(0, '/opt/python')

from dynamodb_utils import get_tour_item, put_tour_item, query_tour_items, get_tour_table
from ownership import resolve_profile_id_for_sub
from rbac import Permission, require_permission
from response import success_response, error_response, bad_request_response


def _rider_for_claims(event, tour_id):
    claims = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
    profile_id = resolve_profile_id_for_sub(claims.get('sub', ''))
    riders = query_tour_items(
        table_type='TourRider', tour_id=tour_id,
        key_condition_expression='profileId = :profileId',
        expression_values={':profileId': profile_id},
        index_name='ProfileIdIndex',
    ) if profile_id else []
    return riders[0].get('riderId') if riders else None


def lambda_handler(event, context):
    params = event.get('pathParameters') or {}
    tour_id = params.get('tourId')
    occurrence_id = params.get('occurrenceId')
    if not tour_id or not occurrence_id:
        return bad_request_response('tourId and occurrenceId are required in path')
    occurrence = get_tour_item('EventOccurrence', tour_id, {'eventId': params.get('eventId'), 'dateSeq': occurrence_id.rsplit('#', 2)[-2] + '#' + occurrence_id.rsplit('#', 1)[-1]})
    if not occurrence:
        return error_response('OCCURRENCE_NOT_FOUND', 'Occurrence not found.', status_code=404)
    event_definition = get_tour_item('Event', tour_id, {'eventId': params.get('eventId')})
    if not event_definition:
        return error_response('EVENT_NOT_FOUND', 'Event not found.', status_code=404)
    if occurrence.get('status') != 'PLANNED':
        return error_response('REGISTRATION_CLOSED', 'Registration is only available while the occurrence is planned.', status_code=409)

    method = (event.get('requestContext', {}).get('http', {}).get('method') or 'POST').upper()
    rider_id = params.get('riderId')
    if rider_id:
        deny = require_permission(event, Permission.EVENT_REGISTRATION_MANAGE)
        if deny:
            return deny
    else:
        deny = require_permission(event, Permission.READ)
        if deny:
            return deny
        rider_id = _rider_for_claims(event, tour_id)
    if not rider_id:
        return error_response('RIDER_NOT_IN_TOUR', 'Rider is not registered for this tour.', status_code=403)
    if not get_tour_item('TourRider', tour_id, {'riderId': rider_id}):
        return error_response('RIDER_NOT_IN_TOUR', 'Rider is not registered for this tour.', status_code=403)

    if method in {'POST', 'PUT'}:
        item = {
            'occurrenceId': occurrence_id,
            'riderId': rider_id,
            'eventId': params.get('eventId'),
            'registeredAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        }
        put_tour_item('EventRegistration', tour_id, item)
        return success_response(item, status_code=201 if method == 'POST' else 200)
    if method == 'DELETE':
        get_tour_table('EventRegistration', tour_id).delete_item(
            Key={'occurrenceId': occurrence_id, 'riderId': rider_id}
        )
        return success_response({'occurrenceId': occurrence_id, 'riderId': rider_id, 'registered': False})
    return bad_request_response('Unsupported registration method')
