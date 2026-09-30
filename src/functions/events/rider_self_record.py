"""Rider self-service event activity record endpoint."""

import json
import sys
sys.path.insert(0, '/opt/python')

from dynamodb_utils import query_tour_items
from ownership import resolve_profile_id_for_sub
from rbac import Permission, require_permission
from response import error_response, bad_request_response
from create_activity_record import lambda_handler as create_activity_record


def lambda_handler(event, context):
    deny = require_permission(event, Permission.SELF_CHECKIN)
    if deny:
        return deny
    params = event.get('pathParameters') or {}
    claims = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
    profile_id = resolve_profile_id_for_sub(claims.get('sub', ''))
    riders = query_tour_items(
        table_type='TourRider', tour_id=params.get('tourId'),
        key_condition_expression='profileId = :profileId',
        expression_values={':profileId': profile_id},
        index_name='ProfileIdIndex',
    ) if profile_id else []
    if not riders:
        return error_response('RIDER_NOT_IN_TOUR', 'Rider is not registered for this tour.', status_code=403)
    try:
        body = json.loads(event.get('body') or '{}')
    except json.JSONDecodeError:
        return bad_request_response('Invalid JSON in request body')
    body['riderId'] = riders[0]['riderId']
    body['method'] = 'SELF_SERVICE'
    request = dict(event)
    request['body'] = json.dumps(body)
    request['_self_service'] = True
    return create_activity_record(request, context)
