"""Get rider details for dashboard popup with profile attribute filtering."""

import sys

import hashlib
import json

from logger import get_logger, log_event
from response import success_response, not_found_response, bad_request_response, internal_error_response, not_modified_response, DecimalEncoder
from dynamodb_utils import get_tour_item, get_item, query_tour_items
from validation import validate_tour_id, validate_ride_id, validate_rider_id, ValidationError
from rbac import require_permission, Permission
from models import is_cancelled_checkin_item
from profile_schema import filter_profile_for_response

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def _timeline_entry(checkin):
    return {
        'checkInId': checkin.get('checkInId'),
        'stageNumber': checkin.get('stageNumber'),
        'stageId': checkin.get('stageId'),
        'isNotRiding': bool(checkin.get('isNotRiding', False)),
        'isFloat': bool(checkin.get('isFloat', False)),
        'floatNo': checkin.get('floatNo'),
        'isQuitRiding': bool(checkin.get('isQuitRiding', False)),
        'timestamp': checkin.get('timestamp'),
    }


def _derive_latest_status(checkin_timeline):
    if not checkin_timeline:
        return 'NOT_CHECKED_IN'

    latest = checkin_timeline[-1]
    if latest.get('isQuitRiding'):
        return 'QUIT_RIDING'
    if latest.get('isNotRiding'):
        return 'NOT_RIDING'
    if latest.get('isFloat'):
        return 'FLOAT'
    return 'CHECKED_IN'


def lambda_handler(event, context):
    try:
        log_event(logger, event)

        path_params = event.get('pathParameters', {})
        tour_id = path_params.get('tourId')
        ride_id = path_params.get('rideId')
        rider_id = path_params.get('riderId')

        deny = require_permission(event, Permission.DASHBOARD)
        if deny:
            return deny

        if not tour_id or not ride_id or not rider_id:
            return bad_request_response('tourId, rideId and riderId are required in path')

        try:
            validate_tour_id(tour_id)
            validate_ride_id(ride_id)
            validate_rider_id(rider_id)
        except ValidationError as exc:
            return bad_request_response(str(exc))

        ride = get_tour_item(table_type='Ride', tour_id=tour_id, key={'rideId': ride_id})
        if not ride:
            return not_found_response('Ride', ride_id)

        tour_rider = get_tour_item(table_type='TourRider', tour_id=tour_id, key={'riderId': rider_id})
        if not tour_rider:
            return not_found_response('Rider', rider_id)

        profile = {}
        profile_id = tour_rider.get('profileId')
        if profile_id:
            profile = get_item('RIDER_PROFILE_TABLE', {'profileId': profile_id}) or {}
            profile = filter_profile_for_response(profile, event=event, staff_mode=True)

        rider_checkins = query_tour_items(
            table_type='CheckIn',
            tour_id=tour_id,
            key_condition_expression='riderId = :rid',
            expression_values={':rid': rider_id},
            index_name='RiderIdIndex',
        )

        ride_timeline_raw = [checkin for checkin in rider_checkins if checkin.get('rideId') == ride_id and not is_cancelled_checkin_item(checkin)]
        ride_timeline_raw.sort(key=lambda item: (item.get('timestamp', ''), item.get('checkInId', '')))
        checkin_timeline = [_timeline_entry(checkin) for checkin in ride_timeline_raw]

        payload = {
            'rider': {
                'riderId': rider_id,
                'profileId': profile_id,
                'name': profile.get('name'),
                'phone': profile.get('phone'),
                'personalCode': profile.get('personalCode'),
                'photoS3Key': profile.get('photoS3Key'),
            },
            'checkInTimeline': checkin_timeline,
            'latestStatus': _derive_latest_status(checkin_timeline),
            'profileAttributes': profile.get('attributes', {}),
            'sensitiveKeys': profile.get('sensitiveKeys', []),
        }

        payload_json = json.dumps(payload, sort_keys=True, cls=DecimalEncoder)
        etag = f'"{hashlib.md5(payload_json.encode()).hexdigest()}"'

        request_headers = event.get('headers', {}) or {}
        if_none_match = request_headers.get('if-none-match') or request_headers.get('If-None-Match')
        if if_none_match and if_none_match == etag:
            response = not_modified_response()
            response['headers']['ETag'] = etag
            return response

        response = success_response(payload)
        response['headers']['ETag'] = etag
        return response

    except Exception as exc:
        logger.error("Error getting rider details: %s", exc, exc_info=True)
        return internal_error_response('Failed to retrieve rider details')
