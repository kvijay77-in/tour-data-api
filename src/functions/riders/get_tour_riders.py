"""Get all tour riders with role-filtered profile attributes."""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, bad_request_response, internal_error_response
from dynamodb_utils import scan_tour_items, get_item
from validation import validate_tour_id, ValidationError
from profile_schema import filter_profile_for_response

logger = get_logger(__name__)


def lambda_handler(event, context):
    try:
        tour_id = event.get('pathParameters', {}).get('tourId')
        if not tour_id:
            return bad_request_response('tourId is required in path')

        try:
            validate_tour_id(tour_id)
        except ValidationError as exc:
            return bad_request_response(str(exc))

        tour_riders = scan_tour_items(table_type='TourRider', tour_id=tour_id)

        enriched_riders = []
        for tour_rider in tour_riders:
            profile_id = tour_rider.get('profileId')
            if profile_id:
                profile = get_item('RIDER_PROFILE_TABLE', {'profileId': profile_id})
                if profile:
                    filtered = filter_profile_for_response(profile, event=event, staff_mode=True)
                    tour_rider['profile'] = filtered
                    tour_rider['personalCode'] = filtered.get('personalCode')
            enriched_riders.append(tour_rider)

        return success_response({'riders': enriched_riders, 'count': len(enriched_riders), 'tourId': tour_id})

    except Exception as exc:
        logger.error(f'Error getting tour riders: {str(exc)}', exc_info=True)
        return internal_error_response('Failed to retrieve tour riders')
