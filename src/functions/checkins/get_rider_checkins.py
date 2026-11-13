"""
Lambda function to get all check-ins for a rider in a tour.

Uses tour-specific tables: CheckIn-{tourId}, TourRider-{tourId}.
Route: GET /v1/tours/{tourId}/riders/{riderId}/checkins
"""

import sys

from logger import get_logger
from response import (
    success_response,
    bad_request_response,
    error_response,
    internal_error_response,
)
from handler_utils import api_handler
from models import is_cancelled_checkin_item
from validation import validate_tour_id, validate_rider_id, ValidationError
from dynamodb_utils import get_tour_item, query_tour_items
from rbac import Permission, require_permission
from rider_identity import require_own_rider_data
from botocore.exceptions import ClientError

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


@api_handler('Failed to get rider check-ins')
def lambda_handler(event, context):
    """Get all check-ins for a rider within a tour."""
    try:
        deny = require_permission(event, Permission.READ)
        if deny:
            return deny

        path_params = event.get('pathParameters', {})
        tour_id = path_params.get('tourId')
        rider_id = path_params.get('riderId')

        if not tour_id or not rider_id:
            return bad_request_response("tourId and riderId are required in path")

        try:
            validate_tour_id(tour_id)
            validate_rider_id(rider_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        # Rider API: a rider may only read their own check-ins (403 NOT_OWN_DATA)
        deny = require_own_rider_data(event, tour_id, rider_id)
        if deny:
            return deny

        tour_rider = get_tour_item(
            table_type='TourRider',
            tour_id=tour_id,
            key={'riderId': rider_id}
        )
        if not tour_rider:
            return error_response(
                error_code='RIDER_NOT_IN_TOUR',
                message=f"Rider {rider_id} is not registered for this tour",
                status_code=400,
            )

        checkins = query_tour_items(
            table_type='CheckIn',
            tour_id=tour_id,
            key_condition_expression='riderId = :rid',
            expression_values={':rid': rider_id},
            index_name='RiderIdIndex'
        )
        checkins = [checkin for checkin in checkins if not is_cancelled_checkin_item(checkin)]

        checkins.sort(key=lambda c: c.get('timestamp', ''))

        return success_response({
            'tourId': tour_id,
            'riderId': rider_id,
            'checkIns': checkins,
            'count': len(checkins),
        })

    except ClientError as e:
        if e.response.get('Error', {}).get('Code') == 'ResourceNotFoundException':
            # No check-in data exists for this tour yet: return an empty list, not an error.
            path_params = event.get('pathParameters') or {}
            empty = {
                'tourId': path_params.get('tourId'),
                'riderId': path_params.get('riderId'),
                'checkIns': [],
                'count': 0,
            }
            if 'rideNo' in path_params:
                empty['rideNo'] = int(path_params['rideNo'])
            return success_response(empty)
        logger.error("Error getting rider check-ins: %s", e, exc_info=True)
        return internal_error_response("Failed to get rider check-ins")
