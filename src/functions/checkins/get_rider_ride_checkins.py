"""
Lambda function to get all check-ins for a rider and ride number.

Uses tour-specific tables: CheckIn-{tourId}, TourRider-{tourId}, Ride-{tourId}.
Route: GET /v1/tours/{tourId}/riders/{riderId}/rides/{rideNo}/checkins
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import (
    success_response,
    bad_request_response,
    error_response,
    internal_error_response,
)
from models import is_cancelled_checkin_item
from validation import validate_tour_id, validate_rider_id, ValidationError
from dynamodb_utils import get_tour_item, query_tour_items, scan_tour_items
from rbac import Permission, require_permission

logger = get_logger(__name__)


def lambda_handler(event, context):
    """Get all check-ins for a rider filtered by rideNo within a tour."""
    try:
        deny = require_permission(event, Permission.READ)
        if deny:
            return deny

        path_params = event.get('pathParameters', {})
        tour_id = path_params.get('tourId')
        rider_id = path_params.get('riderId')
        ride_no_raw = path_params.get('rideNo')

        if not tour_id or not rider_id or ride_no_raw is None:
            return bad_request_response("tourId, riderId and rideNo are required in path")

        try:
            validate_tour_id(tour_id)
            validate_rider_id(rider_id)
            ride_no = int(ride_no_raw)
        except ValidationError as e:
            return bad_request_response(str(e))
        except ValueError:
            return bad_request_response("rideNo must be a valid integer")

        if ride_no <= 0:
            return bad_request_response("rideNo must be a positive integer")

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

        rides = scan_tour_items(
            table_type='Ride',
            tour_id=tour_id,
            filter_expression='rideNo = :rideNo',
            expression_values={':rideNo': ride_no},
        )
        ride_ids = {ride.get('rideId') for ride in rides if ride.get('rideId')}

        rider_checkins = query_tour_items(
            table_type='CheckIn',
            tour_id=tour_id,
            key_condition_expression='riderId = :rid',
            expression_values={':rid': rider_id},
            index_name='RiderIdIndex'
        )

        checkins = [
            checkin for checkin in rider_checkins
            if checkin.get('rideId') in ride_ids
            and not is_cancelled_checkin_item(checkin)
        ]
        checkins.sort(key=lambda c: c.get('timestamp', ''))

        return success_response({
            'tourId': tour_id,
            'riderId': rider_id,
            'rideNo': ride_no,
            'checkIns': checkins,
            'count': len(checkins),
        })

    except Exception as e:
        logger.error(f"Error getting rider ride check-ins: {str(e)}", exc_info=True)
        return internal_error_response("Failed to get rider ride check-ins")
