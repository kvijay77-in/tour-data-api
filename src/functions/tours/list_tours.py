"""
List tours Lambda function

Lists all tours, optionally filtered by status using StatusIndex GSI.
"""

import sys

from logger import get_logger
from self_service_policy import apply_tour_defaults
from response import success_response, error_response, internal_error_response
from dynamodb_utils import scan_items, query_items
from models import TourStatus

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    List all tours with optional status filter
    
    Query parameters (optional):
    - status: Filter by tour status (PLANNING, PROVISIONING, ACTIVE, COMPLETED, ARCHIVED)
    
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
                TourStatus(status_filter.upper())
                status_filter = status_filter.upper()
            except ValueError:
                valid_statuses = [s.value for s in TourStatus]
                return error_response(
                    error_code="INVALID_STATUS",
                    message=f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
                    status_code=400
                )
        
        logger.info("Listing tours with status filter: %s", status_filter or 'all')
        
        if status_filter:
            # Use StatusIndex GSI for efficient filtering
            items = query_items(
                table_name_env='TOUR_MASTER_TABLE',
                key_condition_expression='#status = :status',
                expression_values={':status': status_filter},
                expression_names={'#status': 'status'},
                index_name='StatusIndex'
            )
        else:
            # Get all tours via scan
            items = scan_items(
                table_name_env='TOUR_MASTER_TABLE'
            )
        
        logger.info("Found %s tour(s)", len(items))
        
        return success_response({
            'tours': [apply_tour_defaults(item) for item in items],
            'count': len(items)
        })
    
    except Exception as e:
        logger.error("Error listing tours: %s", e, exc_info=True)
        return internal_error_response("Failed to list tours")
