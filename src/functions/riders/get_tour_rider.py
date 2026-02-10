"""
Lambda function to get tour rider details (rider's participation in a tour)
"""
import json
import os
import sys

# Add common layer to path
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, error_response, bad_request_response
from validation import validate_rider_id, validate_tour_id, ValidationError
from dynamodb_utils import get_item

logger = get_logger(__name__)

TOUR_RIDER_TABLE = os.environ['TOUR_RIDER_TABLE']
RIDER_PROFILE_TABLE = os.environ['RIDER_PROFILE_TABLE']


def lambda_handler(event, context):
    """
    Get tour rider details (participation info)
    
    Path parameters:
    - tourId (e.g., TOUR2026)
    - riderId (e.g., R42)
    
    Returns:
    - 200: Tour rider found (includes rider profile)
    - 400: Invalid input
    - 404: Tour rider not found
    - 500: Server error
    """
    try:
        # Extract path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        rider_id = event.get('pathParameters', {}).get('riderId')
        
        if not tour_id or not rider_id:
            return bad_request_response("tourId and riderId are required in path")
        
        # Validate IDs
        try:
            validate_tour_id(tour_id)
            validate_rider_id(rider_id)
        except ValidationError as e:
            logger.warning(f"Invalid ID format - tour: {tour_id}, rider: {rider_id}", exc_info=True)
            return bad_request_response(str(e))
        
        # Get tour rider record
        logger.info(f"Fetching tour rider: {tour_id}#{rider_id}")
        tour_rider = get_item(
            table_name=TOUR_RIDER_TABLE,
            key={'tourId': tour_id, 'riderId': rider_id}
        )
        
        if not tour_rider:
            logger.info(f"Tour rider not found: {tour_id}#{rider_id}")
            return not_found_response(f"Rider {rider_id} not found in tour {tour_id}")
        
        # Get rider profile for additional details
        logger.info(f"Fetching rider profile: {rider_id}")
        rider_profile = get_item(
            table_name=RIDER_PROFILE_TABLE,
            key={'riderId': rider_id}
        )
        
        # Merge profile data with tour rider data
        result = {**tour_rider}
        if rider_profile:
            result['profile'] = rider_profile
        
        logger.info(f"Successfully retrieved tour rider: {tour_id}#{rider_id}")
        return success_response(result)
        
    except Exception as e:
        logger.error(f"Error getting tour rider: {str(e)}", exc_info=True)
        return error_response(f"Failed to get tour rider: {str(e)}")
