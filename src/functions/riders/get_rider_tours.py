"""
Lambda function to list rider tour participation records by profile ID.

Shared RiderTours table (partition key: profileId, sort key: tourId).
Route: GET /v1/profile/{profileId}/tours
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, bad_request_response, internal_error_response
from dynamodb_utils import query_items

logger = get_logger(__name__)


TABLE_ENV = 'RIDER_TOURS_TABLE'


def lambda_handler(event, context):
    """
    List rider tour participation details for a profile.

    Path parameters:
    - profileId: Rider profile identifier

    Returns:
    - 200: List of participation records for the profile
    - 400: Missing path parameter
    - 500: Server error
    """
    try:
        path_params = event.get('pathParameters', {})
        profile_id = (path_params.get('profileId') or '').strip()

        if not profile_id:
            return bad_request_response('profileId is required in path')

        logger.info(f"Fetching rider tour participations: profileId={profile_id}")

        participations = query_items(
            table_name_env=TABLE_ENV,
            key_condition_expression='profileId = :profileId',
            expression_values={':profileId': profile_id}
        )

        logger.info(
            "Rider tour participations fetched: "
            f"profileId={profile_id}, count={len(participations)}"
        )

        return success_response({
            'profileId': profile_id,
            'count': len(participations),
            'tours': participations,
        })

    except Exception as e:
        logger.error(f"Error listing rider tour participations: {str(e)}", exc_info=True)
        return internal_error_response('Failed to list rider tour participations')