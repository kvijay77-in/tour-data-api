"""
Get all tour riders Lambda function

Uses tour-specific TourRider-{tourId} table (scan all items)
and shared RiderProfile table for profile enrichment.
Route: GET /v1/tours/{tourId}/riders
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, bad_request_response, internal_error_response
from dynamodb_utils import scan_tour_items, get_item
from validation import validate_tour_id, ValidationError

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get all riders enrolled in a specific tour
    
    Path parameters:
    - tourId: Tour identifier (e.g., TOT-2026)
    
    Returns:
    - 200: List of tour riders with profile data
    - 400: Invalid tourId
    - 500: Server error
    """
    try:
        # Extract path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        
        if not tour_id:
            return bad_request_response("tourId is required in path")
        
        # Validate tour ID
        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        logger.info(f"Fetching all riders for tour: {tour_id}")
        
        # Scan all items from tour-specific TourRider table (table is tour-scoped, no filter needed)
        tour_riders = scan_tour_items(
            table_type='TourRider',
            tour_id=tour_id
        )
        
        logger.info(f"Found {len(tour_riders)} riders for tour {tour_id}")
        
        # Enrich with rider profile data
        enriched_riders = []
        for tour_rider in tour_riders:
            profile_id = tour_rider.get('profileId')
            
            if profile_id:
                profile = get_item(
                    table_name_env='RIDER_PROFILE_TABLE',
                    key={'profileId': profile_id}
                )
                if profile:
                    tour_rider['profile'] = profile
            
            enriched_riders.append(tour_rider)
        
        logger.info(f"Successfully retrieved {len(enriched_riders)} tour riders")
        
        return success_response({
            'riders': enriched_riders,
            'count': len(enriched_riders),
            'tourId': tour_id
        })
        
    except Exception as e:
        logger.error(f"Error getting tour riders: {str(e)}", exc_info=True)
        return internal_error_response("Failed to retrieve tour riders")
