"""
Lambda function to get all check-ins for a specific ride

Uses tour-specific tables: CheckIn-{tourId}, Ride-{tourId}.
Route: GET /v1/tours/{tourId}/rides/{rideId}/checkins
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, bad_request_response, internal_error_response
from validation import validate_tour_id, validate_ride_id, ValidationError
from dynamodb_utils import get_tour_item, query_tour_items
from models import is_cancelled_checkin_item

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get all check-ins for a specific ride
    
    Path parameters:
    - tourId: Tour identifier (e.g., TOT-2026)
    - rideId: Ride identifier (e.g., RIDE001)
    
    Returns:
    - 200: List of check-ins (may be empty)
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
        
        # Verify ride exists in tour-specific Ride table
        logger.info(f"Checking if ride exists: {tour_id}/{ride_id}")
        ride = get_tour_item(
            table_type='Ride',
            tour_id=tour_id,
            key={'rideId': ride_id}
        )
        
        if not ride:
            return not_found_response("Ride", ride_id)
        
        # Query all check-ins for this ride from tour-specific CheckIn table
        logger.info(f"Querying check-ins for ride: {ride_id}")
        checkins = query_tour_items(
            table_type='CheckIn',
            tour_id=tour_id,
            key_condition_expression='rideId = :rid',
            expression_values={':rid': ride_id}
        )
        checkins = [checkin for checkin in checkins if not is_cancelled_checkin_item(checkin)]
        
        # Sort check-ins by timestamp
        checkins.sort(key=lambda c: c.get('timestamp', ''))
        
        logger.info(f"Successfully retrieved {len(checkins)} check-ins for ride {ride_id}")
        return success_response({
            'checkIns': checkins,
            'count': len(checkins),
            'rideId': ride_id,
            'tourId': tour_id
        })
        
    except Exception as e:
        logger.error(f"Error getting ride check-ins: {str(e)}", exc_info=True)
        return internal_error_response("Failed to get ride check-ins")
