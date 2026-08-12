"""
Lambda function to get rider tour participation details by profile ID and tour ID

Shared RiderTours table (partition key: profileId, sort key: tourId).
Route: GET /v1/profile/{profileId}/tours/{tourId}
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, bad_request_response, internal_error_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import get_item

logger = get_logger(__name__)


TABLE_ENV = 'RIDER_TOURS_TABLE'


def lambda_handler(event, context):
    """
    Get rider tour participation details.

    Path parameters:
    - profileId: Rider profile identifier
    - tourId: Tour identifier (e.g., TOT-2026)

    Returns:
    - 200: Participation record found
    - 400: Missing or invalid path parameters
    - 404: Participation record not found
    - 500: Server error
    """
    try:
        path_params = event.get('pathParameters', {})
        profile_id = (path_params.get('profileId') or '').strip()
        tour_id = (path_params.get('tourId') or '').strip()

        if not profile_id or not tour_id:
            return bad_request_response('profileId and tourId are required in path')

        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        logger.info(f"Fetching rider tour participation: profileId={profile_id}, tourId={tour_id}")
        participation = get_item(
            table_name_env=TABLE_ENV,
            key={
                'profileId': profile_id,
                'tourId': tour_id,
            }
        )

        if not participation:
            logger.info(
                "Rider tour participation not found: "
                f"profileId={profile_id}, tourId={tour_id}"
            )
            return not_found_response('RiderTours', f'{profile_id}/{tour_id}')

        return success_response(participation)

    except Exception as e:
        logger.error(f"Error getting rider tour participation: {str(e)}", exc_info=True)
        return internal_error_response('Failed to get rider tour participation')
