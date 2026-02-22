"""
Lambda function to list all rides for a tour

Uses tour-specific Ride-{tourId} table (scan + optional status filter via StatusIndex GSI).
Route: GET /v1/tours/{tourId}/rides
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, bad_request_response, internal_error_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import scan_tour_items, query_tour_items
from models import RideStatus

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    List all rides for a tour (optionally filtered by status)
    
    Path parameter: tourId (e.g., TOT-2026)
    Query parameter: status (optional - PLANNED, ACTIVE, COMPLETED, CLOSED)
    
    Returns:
    - 200: List of rides (may be empty)
    - 400: Invalid tour ID or status
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
            return bad_request_response(str(e))
        
        # Get optional status filter from query parameters
        query_params = event.get('queryStringParameters') or {}
        status_filter = query_params.get('status')
        
        # Validate status if provided
        if status_filter:
            valid_statuses = [s.value for s in RideStatus]
            if status_filter not in valid_statuses:
                return bad_request_response(
                    f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                )
        
        logger.info(f"Listing rides for tour: {tour_id}, status filter: {status_filter or 'all'}")
        
        if status_filter:
            # Use StatusIndex GSI for efficient status filtering
            rides = query_tour_items(
                table_type='Ride',
                tour_id=tour_id,
                key_condition_expression='#status = :status',
                expression_values={':status': status_filter},
                expression_names={'#status': 'status'},
                index_name='StatusIndex'
            )
        else:
            # Scan all rides (table is tour-scoped, so this is bounded)
            rides = scan_tour_items(
                table_type='Ride',
                tour_id=tour_id
            )
        
        # Sort rides by date
        rides.sort(key=lambda r: r.get('date', ''))
        
        logger.info(f"Successfully retrieved {len(rides)} rides for tour {tour_id}")
        return success_response({
            'rides': rides,
            'count': len(rides),
            'tourId': tour_id
        })
        
    except Exception as e:
        logger.error(f"Error listing rides: {str(e)}", exc_info=True)
        return internal_error_response("Failed to list rides")
