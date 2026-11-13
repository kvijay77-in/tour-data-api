"""
Get tour by ID Lambda function
"""

import sys

from logger import get_logger, log_event
from self_service_policy import apply_tour_defaults
from response import (
    success_response, not_found_response,
    bad_request_response, internal_error_response
)
from dynamodb_utils import get_item
from validation import validate_tour_id, ValidationError

sys.path.insert(0, '/opt/python')

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
        
        logger.info("Getting tour: %s", tour_id)
        
        # Get tour from DynamoDB
        tour = get_item(
            table_name_env='TOUR_MASTER_TABLE',
            key={'tourId': tour_id}
        )
        
        if not tour:
            return not_found_response("Tour", tour_id)
        
        logger.info("Found tour: %s", tour_id)
        return success_response(apply_tour_defaults(tour))
    
    except Exception as e:
        logger.error("Error getting tour: %s", e, exc_info=True)
        return internal_error_response("Failed to retrieve tour")
