"""Get rider tour participation details by profile ID and tour ID."""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, bad_request_response, internal_error_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import get_item
from ownership import require_own_profile

logger = get_logger(__name__)

TABLE_ENV = 'RIDER_TOURS_TABLE'


def lambda_handler(event, context):
    try:
        path_params = event.get('pathParameters', {})
        profile_id = (path_params.get('profileId') or '').strip()
        tour_id = (path_params.get('tourId') or '').strip()

        if not profile_id or not tour_id:
            return bad_request_response('profileId and tourId are required in path')

        deny = require_own_profile(event, profile_id)
        if deny:
            return deny

        try:
            validate_tour_id(tour_id)
        except ValidationError as exc:
            return bad_request_response(str(exc))

        participation = get_item(table_name_env=TABLE_ENV, key={'profileId': profile_id, 'tourId': tour_id})
        if not participation:
            return not_found_response('RiderTours', f'{profile_id}/{tour_id}')

        return success_response(participation)

    except Exception as exc:
        logger.error(f'Error getting rider tour participation: {str(exc)}', exc_info=True)
        return internal_error_response('Failed to get rider tour participation')
