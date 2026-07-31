"""
Get lightweight rider list for a tour.

Returns only riderId and rider name to reduce payload size for
name-selection use cases in frontend flows.
Route: GET /v1/tours/{tourId}/riders/names
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, bad_request_response, internal_error_response
from dynamodb_utils import scan_tour_items, get_item
from validation import validate_tour_id, ValidationError
from rbac import Permission, require_permission

logger = get_logger(__name__)


def _rider_sort_key(rider: dict):
    """Sort riders by numeric part when riderId follows R<number>."""
    rider_id = (rider.get('riderId') or '').strip()
    if rider_id.startswith('R') and rider_id[1:].isdigit():
        return (0, int(rider_id[1:]))
    return (1, rider_id)


def lambda_handler(event, context):
    """
    Get all riders enrolled in a specific tour with names only.

    Path parameters:
    - tourId: Tour identifier (e.g., TOT-2026)

    Returns:
    - 200: List of riders with riderId and name
    - 400: Invalid tourId
    - 403: Missing READ permission
    - 500: Server error
    """
    try:
        deny = require_permission(event, Permission.READ)
        if deny:
            return deny

        tour_id = event.get('pathParameters', {}).get('tourId')
        if not tour_id:
            return bad_request_response("tourId is required in path")

        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        logger.info(f"Fetching lightweight rider names for tour: {tour_id}")

        tour_riders = scan_tour_items(
            table_type='TourRider',
            tour_id=tour_id
        )

        riders = []
        for tour_rider in tour_riders:
            rider_id = tour_rider.get('riderId')
            profile_id = tour_rider.get('profileId')
            if not rider_id or not profile_id:
                continue

            profile = get_item(
                table_name_env='RIDER_PROFILE_TABLE',
                key={'profileId': profile_id}
            )

            riders.append({
                'riderId': rider_id,
                'name': profile.get('name') if profile else None
            })

        riders.sort(key=_rider_sort_key)

        logger.info(f"Returning {len(riders)} lightweight rider records for tour {tour_id}")
        return success_response({
            'riders': riders,
            'count': len(riders),
            'tourId': tour_id
        })

    except Exception as e:
        logger.error(f"Error getting lightweight rider names: {str(e)}", exc_info=True)
        return internal_error_response("Failed to retrieve rider names")
