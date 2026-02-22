"""
Get tour by ID Lambda function
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger, log_event
from response import (
    success_response, not_found_response, error_response,
    bad_request_response, internal_error_response
)
from dynamodb_utils import get_item
from validation import validate_tour_id, ValidationError

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get tour by ID
    
    Path Parameters:
        tourId: Tour identifier (e.g., TOT-2026)
    """
    try:
        log_event(logger, event)
        
        # Extract tour ID from path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        
        if not tour_id:
            return bad_request_response("tourId is required in path")
        
        # Validate tour ID format
        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        logger.info(f"Getting tour: {tour_id}")
        
        # Get tour from DynamoDB (PK = TOUR#<tourId>)
        tour = get_item(
            table_name_env='TOUR_TABLE',
            key={'PK': f"TOUR#{tour_id}"}
        )
        
        if not tour:
            return not_found_response("Tour", tour_id)
        
        logger.info(f"Found tour: {tour_id}")
        return success_response(tour)
    
    except Exception as e:
        logger.error(f"Error getting tour: {str(e)}", exc_info=True)
        return internal_error_response("Failed to retrieve tour")
