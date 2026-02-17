"""
List tours Lambda function
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
    List all tours with optional status filter
    
    Query parameters (optional):
    - status: Filter by tour status (PLANNING, ACTIVE, COMPLETED, ARCHIVED)
    
    Returns:
    - 200: List of tours (may be empty)
    - 400: Invalid status value
    - 500: Server error
    """
    try:
        # Extract query parameters
        query_params = event.get('queryStringParameters') or {}
        status_filter = query_params.get('status')
        
        # Validate status if provided
        if status_filter:
            try:
                # Validate against TourStatus enum
                TourStatus(status_filter.upper())
                status_filter = status_filter.upper()
            except ValueError:
                valid_statuses = [s.value for s in TourStatus]
                return error_response(
                    error_code="INVALID_STATUS",
                    message=f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
                    status_code=400
                )
        
        logger.info(f"Listing tours with status filter: {status_filter or 'all'}")
        
        # Scan/query tours
        if status_filter:
            # Filter by status
            items = scan_items(
                table_name_env='TOUR_TABLE',
                filter_expression='#status = :status',
                expression_values={':status': status_filter},
                expression_names={'#status': 'status'}
            )
        else:
            # Get all tours
            items = scan_items(
                table_name_env='TOUR_TABLE'
            )
        
        logger.info(f"Found {len(items)} tour(s)")
        
        # Return tours (empty list if none found)
        return success_response({
            'tours': items,
            'count': len(items)
        })
    
    except Exception as e:
        logger.error(f"Error listing tours: {str(e)}", exc_info=True)
        return internal_error_response("Failed to list tours")
