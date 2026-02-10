"""
Lambda function to get all check-ins for a specific ride
"""
import json
import os
import sys

# Add common layer to path
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, error_response, bad_request_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import get_item, query_items

logger = get_logger(__name__)

CHECKIN_TABLE = os.environ['CHECKIN_TABLE']
RIDE_TABLE = os.environ['RIDE_TABLE']


def lambda_handler(event, context):
    """
    Get all check-ins for a specific ride
    
    Path parameters:
    - tourId (e.g., TOUR2026)
    - rideId (e.g., TOUR2026#2026-06-15#1)
    
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
        
        # Validate tour ID
        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            logger.warning(f"Invalid tour ID format: {tour_id}", exc_info=True)
            return bad_request_response(str(e))
        
        # Verify ride exists
        logger.info(f"Checking if ride exists: {ride_id}")
        ride = get_item(
            table_name=RIDE_TABLE,
            key={'tourId': tour_id, 'rideId': ride_id}
        )
        
        if not ride:
            logger.info(f"Ride not found: {ride_id}")
            return not_found_response(f"Ride {ride_id} not found")
        
        # Query all check-ins for this ride
        logger.info(f"Querying check-ins for ride: {ride_id}")
        checkins = query_items(
            table_name=CHECKIN_TABLE,
            key_condition_expression='rideId = :rideId',
            expression_attribute_values={
                ':rideId': ride_id
            }
        )
        
        # Sort check-ins by timestamp
        checkins.sort(key=lambda c: c.get('checkinTime', ''))
        
        logger.info(f"Successfully retrieved {len(checkins)} check-ins for ride {ride_id}")
        return success_response(checkins)
        
    except Exception as e:
        logger.error(f"Error getting ride check-ins: {str(e)}", exc_info=True)
        return error_response(f"Failed to get ride check-ins: {str(e)}")
