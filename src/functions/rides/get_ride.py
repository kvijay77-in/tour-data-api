"""
Lambda function to get a specific ride by ID

Uses tour-specific Ride-{tourId} table (partition key: rideId).
Route: GET /v1/tours/{tourId}/rides/{rideId}
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, bad_request_response, internal_error_response
from validation import validate_tour_id, validate_ride_id, ValidationError
from dynamodb_utils import get_tour_item

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get a specific ride by ID
    
    Path parameters:
    - tourId: Tour identifier (e.g., TOT-2026)
    - rideId: Ride identifier (e.g., RIDE001)
    
    Returns:
    - 200: Ride found
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
        logger.info(f"Fetching ride: {tour_id}/{ride_id}")
        ride = get_tour_item(
            table_type='Ride',
            tour_id=tour_id,
            key={'rideId': ride_id}
        )
        
        if not ride:
            logger.info(f"Ride not found: {ride_id}")
            return not_found_response("Ride", ride_id)
        
        logger.info(f"Successfully retrieved ride: {ride_id}")
        return success_response(ride)
        
    except Exception as e:
        logger.error(f"Error getting ride: {str(e)}", exc_info=True)
        return internal_error_response("Failed to get ride")
