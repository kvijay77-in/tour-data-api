"""
Get active tour Lambda function
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, error_response, internal_error_response
from dynamodb_utils import scan_items
from models import TourStatus

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get the currently active tour
    
    Returns the tour with status ACTIVE
    """
    try:
        logger.info("Getting active tour")
        
        # Query for active tour
        items = scan_items(
            table_name_env='TOUR_TABLE',
            filter_expression='#status = :status',
            expression_values={':status': TourStatus.ACTIVE.value},
            expression_names={'#status': 'status'}
        )
        
        if not items:
            return error_response(
                error_code="NO_ACTIVE_TOUR",
                message="No active tour found",
                status_code=404
            )
        
        # Return first active tour
        tour = items[0]
        
        logger.info(f"Found active tour: {tour.get('tourId')}")
        return success_response(tour)
    
    except Exception as e:
        logger.error(f"Error getting active tour: {str(e)}", exc_info=True)
        return internal_error_response("Failed to retrieve active tour")
