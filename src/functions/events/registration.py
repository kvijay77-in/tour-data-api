"""Event occurrence registration for riders and management users."""

import json
import sys
sys.path.insert(0, '/opt/python')

from dynamodb_utils import get_item, get_tour_item, put_tour_item, query_tour_items, get_tour_table
from models import utc_now_iso
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
    event_id = params.get('eventId')
    occurrence_id = params.get('occurrenceId')
    if not tour_id or not event_id or not occurrence_id:
        return bad_request_response('tourId, eventId and occurrenceId are required in path')

    method = (event.get('requestContext', {}).get('http', {}).get('method') or 'POST').upper()
    rider_id = params.get('riderId')
    if method == 'GET' or rider_id:
        deny = require_permission(event, Permission.EVENT_REGISTRATION_MANAGE)
        if deny:
            return deny
    else:
        deny = require_permission(event, Permission.READ)
        if deny:
            return deny

    occurrence_parts = occurrence_id.split('#', 1)
    if len(occurrence_parts) != 2 or occurrence_parts[0] != event_id:
        return bad_request_response('occurrenceId must belong to eventId')
    occurrence = get_tour_item(
        'EventOccurrence',
        tour_id,
        {'eventId': event_id, 'dateSeq': occurrence_parts[1]},
    )
    if not occurrence:
        return error_response('OCCURRENCE_NOT_FOUND', 'Occurrence not found.', status_code=404)
    event_definition = get_tour_item('Event', tour_id, {'eventId': event_id})
    if not event_definition:
        return error_response('EVENT_NOT_FOUND', 'Event not found.', status_code=404)
    if not event_definition.get('registrationEnabled', False):
        return error_response(
            'REGISTRATION_NOT_ENABLED',
            'Registration is not enabled for this event.',
            status_code=409,
        )
    if occurrence.get('status') != 'PLANNED':
        return error_response('REGISTRATION_CLOSED', 'Registration is only available while the occurrence is planned.', status_code=409)

    if method == 'GET':
        registrations = query_tour_items(
            table_type='EventRegistration',
            tour_id=tour_id,
            key_condition_expression='occurrenceId = :occurrenceId',
            expression_values={':occurrenceId': occurrence_id},
        )
        riders = []
        for registration in registrations:
            tour_rider = get_tour_item(
                'TourRider', tour_id, {'riderId': registration.get('riderId')}
            )
            profile = get_item(
                'RIDER_PROFILE_TABLE',
                {'profileId': (tour_rider or {}).get('profileId')},
            ) if tour_rider and tour_rider.get('profileId') else None
            riders.append({
                'riderId': registration.get('riderId'),
                'name': (profile or {}).get('name'),
                'registeredAt': registration.get('registeredAt'),
                'registeredBy': registration.get('registeredBy'),
                'source': registration.get('source', 'staff'),
            })
        riders.sort(key=lambda rider: rider.get('riderId') or '')
        return success_response({
            'eventId': event_id,
            'occurrenceId': occurrence_id,
            'registrations': riders,
            'count': len(riders),
        })

    if rider_id:
        source = 'staff'
    else:
        rider_id = _rider_for_claims(event, tour_id)
        source = 'rider'
    if not rider_id:
        return error_response('RIDER_NOT_IN_TOUR', 'Rider is not registered for this tour.', status_code=403)
    tour_rider = get_tour_item('TourRider', tour_id, {'riderId': rider_id})
    if not tour_rider:
        return error_response('RIDER_NOT_IN_TOUR', 'Rider is not registered for this tour.', status_code=403)
    if tour_rider.get('status') == 'EXITED':
        return error_response('RIDER_EXITED', 'Exited riders cannot register for an event.', status_code=403)

    if method in {'POST', 'PUT'}:
        item = {
            'occurrenceId': occurrence_id,
            'riderId': rider_id,
            'eventId': event_id,
            'registeredAt': utc_now_iso(),
            'registeredBy': event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {}).get('sub', 'system'),
            'source': source,
        }
        put_tour_item('EventRegistration', tour_id, item)
        return success_response(item, status_code=201 if method == 'POST' else 200)
    if method == 'DELETE':
        get_tour_table('EventRegistration', tour_id).delete_item(
            Key={'occurrenceId': occurrence_id, 'riderId': rider_id}
        )
        return success_response({'occurrenceId': occurrence_id, 'riderId': rider_id, 'registered': False})
    return bad_request_response('Unsupported registration method')
