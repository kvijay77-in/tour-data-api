"""
Get active tour Lambda function

Returns the currently active tour using the StatusIndex GSI.
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, error_response, internal_error_response
from dynamodb_utils import query_items
from models import TourStatus

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get the currently active tour
    
    Uses StatusIndex GSI to efficiently query by status.
    
    Returns:
        200: Active tour data
        404: No active tour found
        500: Server error
    """
    try:
        logger.info("Getting active tour")
        
        # Use StatusIndex GSI to query for ACTIVE tours
        items = query_items(
            table_name_env='TOUR_TABLE',
            key_condition_expression='#status = :status',
            expression_values={':status': TourStatus.ACTIVE.value},
            expression_names={'#status': 'status'},
            index_name='StatusIndex'
        )
        
        if not items:
            return error_response(
                error_code="NO_ACTIVE_TOUR",
                message="No active tour found",
                status_code=404
            )
        
        # Return first active tour (should be only one)
        tour = items[0]
        
        logger.info(f"Found active tour: {tour.get('tourId')}")
        return success_response(tour)
    
    except Exception as e:
        logger.error(f"Error getting active tour: {str(e)}", exc_info=True)
        return internal_error_response("Failed to retrieve active tour")
