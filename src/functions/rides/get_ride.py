"""
Lambda function to get a specific ride by ID
"""
import json
import os
import sys

# Add common layer to path
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, error_response, bad_request_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import get_item

logger = get_logger(__name__)

RIDE_TABLE = os.environ['RIDE_TABLE']


def lambda_handler(event, context):
    """
    Get a specific ride by ID
    
    Path parameters:
    - tourId (e.g., TOUR2026)
    - rideId (e.g., TOUR2026#2026-06-15#1)
    
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
        
        # Validate tour ID
        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            logger.warning(f"Invalid tour ID format: {tour_id}", exc_info=True)
            return bad_request_response(str(e))
        
        # Validate ride ID format (should be tourId#date#stageNumber)
        if not ride_id.startswith(f"{tour_id}#"):
            return bad_request_response(f"Invalid rideId format: must start with {tour_id}#")
        
        # Get ride from DynamoDB
        logger.info(f"Fetching ride: {ride_id}")
        ride = get_item(
            table_name=RIDE_TABLE,
            key={'tourId': tour_id, 'rideId': ride_id}
        )
        
        if not ride:
            logger.info(f"Ride not found: {ride_id}")
            return not_found_response(f"Ride {ride_id} not found")
        
        logger.info(f"Successfully retrieved ride: {ride_id}")
        return success_response(ride)
        
    except Exception as e:
        logger.error(f"Error getting ride: {str(e)}", exc_info=True)
        return error_response(f"Failed to get ride: {str(e)}")
