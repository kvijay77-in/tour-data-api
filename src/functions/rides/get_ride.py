"""
Lambda function to get a specific ride by ID

Uses tour-specific Ride-{tourId} table (partition key: rideId).
Route: GET /v1/tours/{tourId}/rides/{rideId}
"""

import sys

from logger import get_logger
from response import success_response, not_found_response, bad_request_response, internal_error_response
from validation import validate_tour_id, validate_ride_id, ValidationError
from dynamodb_utils import get_item, get_tour_item
from self_service_policy import build_ride_self_service

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get a specific ride by ID
    
    Path parameters:
    - tourId: Tour identifier (e.g., TOT-2026)
    - rideId: Ride identifier (e.g., RIDE001)
    
    Returns:
    - 200: Ride found, with the calculated read-only ``selfService`` permissions
    - 400: Invalid input
    - 404: Ride not found
    - 500: Server error
    """
    try:
        # Extract path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        ride_id = event.get('pathParameters', {}).get('rideId')
        
        if not tour_id or not ride_id:
            return bad_request_response("tourId and rideId are required in path")
        
        # Validate IDs
        try:
            validate_tour_id(tour_id)
            validate_ride_id(ride_id)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Get ride from tour-specific Ride table
        logger.info("Fetching ride: %s/%s", tour_id, ride_id)
        ride = get_tour_item(
            table_type='Ride',
            tour_id=tour_id,
            key={'rideId': ride_id}
        )
        
        if not ride:
            logger.info("Ride not found: %s", ride_id)
            return not_found_response("Ride", ride_id)
        
        tour = get_item(table_name_env='TOUR_MASTER_TABLE', key={'tourId': tour_id})
        ride['selfService'] = build_ride_self_service(ride, tour)

        logger.info("Successfully retrieved ride: %s", ride_id)
        return success_response(ride)
        
    except Exception as e:
        logger.error("Error getting ride: %s", e, exc_info=True)
        return internal_error_response("Failed to get ride")
