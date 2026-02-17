"""
Get all tour riders Lambda function

NOTE: This implementation uses the current single TourRider table structure.
When TODO #26-30 (hybrid table strategy) is implemented, this function will need
refactoring to use the tour-specific TourRider-{tourId} table with dynamic table
name resolution.
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, error_response, internal_error_response
from dynamodb_utils import scan_items, get_item
from validation import validate_tour_id, ValidationError

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get all riders enrolled in a specific tour
    
    Path parameters:
    - tourId: Tour identifier (e.g., TOUR2026)
    
    Returns:
    - 200: List of tour riders with profile data
    - 400: Invalid tourId
    - 500: Server error
    """
    try:
        # Extract path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        
        if not tour_id:
            return error_response(
                error_code="MISSING_PARAMETER",
                message="tourId is required in path",
                status_code=400
            )
        
        # Validate tour ID
        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            logger.warning(f"Invalid tour ID format: {tour_id}")
            return error_response(
                error_code="INVALID_TOUR_ID",
                message=str(e),
                status_code=400
            )
        
        logger.info(f"Fetching all riders for tour: {tour_id}")
        
        # Query tour riders
        # Current implementation uses scan with filter (works with current table structure)
        # TODO: When hybrid table strategy is implemented (TODO #28), use:
        #   - Dynamic table name: TourRider-{tourId}
        #   - Query all items (no filter needed as table is tour-scoped)
        tour_riders = scan_items(
            table_name_env='TOUR_RIDER_TABLE',
            filter_expression='begins_with(PK, :pk)',
            expression_values={':pk': f'TOUR#{tour_id}'}
        )
        
        logger.info(f"Found {len(tour_riders)} riders for tour {tour_id}")
        
        # Enrich with rider profile data
        enriched_riders = []
        for tour_rider in tour_riders:
            profile_id = tour_rider.get('profileId')
            
            if profile_id:
                # Fetch rider profile
                profile = get_item(
                    table_name_env='RIDER_PROFILE_TABLE',
                    key={'PK': f'PROFILE#{profile_id}'}
                )
                
                if profile:
                    tour_rider['profile'] = profile
            
            enriched_riders.append(tour_rider)
        
        logger.info(f"Successfully retrieved {len(enriched_riders)} tour riders")
        
        # Return riders (empty list if none found)
        return success_response({
            'riders': enriched_riders,
            'count': len(enriched_riders),
            'tourId': tour_id
        })
        
    except Exception as e:
        logger.error(f"Error getting tour riders: {str(e)}", exc_info=True)
        return internal_error_response("Failed to retrieve tour riders")
