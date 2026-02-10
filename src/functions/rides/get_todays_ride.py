"""
Lambda function to get today's ride for a tour
"""
import json
import os
import sys
from datetime import datetime, date

# Add common layer to path
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, error_response, bad_request_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import query_items

logger = get_logger(__name__)

RIDE_TABLE = os.environ['RIDE_TABLE']


def lambda_handler(event, context):
    """
    Get today's ride for a tour
    
    Path parameter: tourId (e.g., TOUR2026)
    
    Returns:
    - 200: Today's ride found
    - 400: Invalid tour ID
    - 404: No ride scheduled for today
    - 500: Server error
    """
    try:
        # Extract tour ID from path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        
        if not tour_id:
            return bad_request_response("tourId is required in path")
        
        # Validate tour ID
        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            logger.warning(f"Invalid tour ID format: {tour_id}", exc_info=True)
            return bad_request_response(str(e))
        
        # Get today's date in ISO format
        today = date.today().isoformat()
        
        # Query rides for this tour and date
        logger.info(f"Querying rides for tour {tour_id} on {today}")
        rides = query_items(
            table_name=RIDE_TABLE,
            key_condition_expression='tourId = :tourId AND begins_with(rideId, :ridePrefix)',
            expression_attribute_values={
                ':tourId': tour_id,
                ':ridePrefix': f"{tour_id}#"
            }
        )
        
        # Filter for today's ride
        todays_ride = None
        for ride in rides:
            if ride.get('rideDate') == today:
                todays_ride = ride
                break
        
        if not todays_ride:
            logger.info(f"No ride found for tour {tour_id} on {today}")
            return not_found_response(f"No ride scheduled for {today}")
        
        logger.info(f"Successfully retrieved today's ride: {todays_ride['rideId']}")
        return success_response(todays_ride)
        
    except Exception as e:
        logger.error(f"Error getting today's ride: {str(e)}", exc_info=True)
        return error_response(f"Failed to get today's ride: {str(e)}")
