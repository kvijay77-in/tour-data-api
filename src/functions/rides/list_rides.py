"""
Lambda function to list all rides for a tour
"""
import json
import os
import sys

# Add common layer to path
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, error_response, bad_request_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import query_items

logger = get_logger(__name__)

RIDE_TABLE = os.environ['RIDE_TABLE']


def lambda_handler(event, context):
    """
    List all rides for a tour (optionally filtered by status)
    
    Path parameter: tourId (e.g., TOUR2026)
    Query parameter: status (optional - SCHEDULED, ACTIVE, CLOSED)
    
    Returns:
    - 200: List of rides (may be empty)
    - 400: Invalid tour ID
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
        
        # Get optional status filter from query parameters
        status_filter = event.get('queryStringParameters', {}).get('status') if event.get('queryStringParameters') else None
        
        # Validate status if provided
        if status_filter and status_filter not in ['SCHEDULED', 'ACTIVE', 'CLOSED']:
            return bad_request_response("Invalid status. Must be SCHEDULED, ACTIVE, or CLOSED")
        
        # Query all rides for this tour
        logger.info(f"Querying rides for tour: {tour_id}")
        rides = query_items(
            table_name=RIDE_TABLE,
            key_condition_expression='tourId = :tourId',
            expression_attribute_values={
                ':tourId': tour_id
            }
        )
        
        # Filter by status if specified
        if status_filter:
            rides = [ride for ride in rides if ride.get('status') == status_filter]
            logger.info(f"Filtered to {len(rides)} rides with status {status_filter}")
        
        # Sort rides by date (rideDate field)
        rides.sort(key=lambda r: r.get('rideDate', ''))
        
        logger.info(f"Successfully retrieved {len(rides)} rides for tour {tour_id}")
        return success_response(rides)
        
    except Exception as e:
        logger.error(f"Error listing rides: {str(e)}", exc_info=True)
        return error_response(f"Failed to list rides: {str(e)}")
