"""Get specific tour rider details with filtered profile attributes."""

import sys

from logger import get_logger
from response import success_response, not_found_response, bad_request_response
from handler_utils import api_handler
from validation import validate_rider_id, validate_tour_id, ValidationError
from dynamodb_utils import get_tour_item, get_item
from profile_schema import filter_profile_for_response

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


@api_handler('Failed to get tour rider')
def lambda_handler(event, context):
    tour_id = event.get('pathParameters', {}).get('tourId')
    rider_id = event.get('pathParameters', {}).get('riderId')
    if not tour_id or not rider_id:
        return bad_request_response('tourId and riderId are required in path')

    try:
        validate_tour_id(tour_id)
        validate_rider_id(rider_id)
    except ValidationError as exc:
        return bad_request_response(str(exc))

    tour_rider = get_tour_item(table_type='TourRider', tour_id=tour_id, key={'riderId': rider_id})
    if not tour_rider:
        return not_found_response('TourRider', rider_id)

    profile_id = tour_rider.get('profileId')
    if profile_id:
        rider_profile = get_item('RIDER_PROFILE_TABLE', {'profileId': profile_id})
        if rider_profile:
            filtered = filter_profile_for_response(rider_profile, event=event, staff_mode=True)
            tour_rider['profile'] = filtered
            tour_rider['personalCode'] = filtered.get('personalCode')

    return success_response(tour_rider)
