"""
Lambda function to get a rider profile by rider ID
"""
import json
import os
import sys

# Add common layer to path
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, error_response, bad_request_response
from validation import validate_rider_id, ValidationError
from dynamodb_utils import get_item

logger = get_logger(__name__)

RIDER_PROFILE_TABLE = os.environ['RIDER_PROFILE_TABLE']


def lambda_handler(event, context):
    """
    Get a rider profile by rider ID
    
    Path parameter: riderId (e.g., R1, R42)
    
    Returns:
    - 200: Rider profile found
    - 400: Invalid rider ID format
    - 404: Rider not found
    - 500: Server error
    """
    try:
        # Extract rider ID from path parameters
        rider_id = event.get('pathParameters', {}).get('riderId')
        
        if not rider_id:
            return bad_request_response("riderId is required in path")
        
        # Validate rider ID format
        try:
            validate_rider_id(rider_id)
        except ValidationError as e:
            logger.warning(f"Invalid rider ID format: {rider_id}", exc_info=True)
            return bad_request_response(str(e))
        
        # Get rider profile from DynamoDB
        logger.info(f"Fetching rider profile: {rider_id}")
        rider = get_item(
            table_name=RIDER_PROFILE_TABLE,
            key={'riderId': rider_id}
        )
        
        if not rider:
            logger.info(f"Rider not found: {rider_id}")
            return not_found_response(f"Rider {rider_id} not found")
        
        logger.info(f"Successfully retrieved rider profile: {rider_id}")
        return success_response(rider)
        
    except Exception as e:
        logger.error(f"Error getting rider profile: {str(e)}", exc_info=True)
        return error_response(f"Failed to get rider profile: {str(e)}")
