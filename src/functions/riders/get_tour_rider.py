"""
Lambda function to get tour rider details (rider's participation in a tour)

Uses tour-specific TourRider-{tourId} table (partition key: riderId)
and shared RiderProfile table for profile enrichment.
Route: GET /v1/tours/{tourId}/riders/{riderId}
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, bad_request_response, internal_error_response
from validation import validate_rider_id, validate_tour_id, ValidationError
from dynamodb_utils import get_tour_item, get_item

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get tour rider details (participation info)
    
    Path parameters:
    - tourId: Tour identifier (e.g., TOT-2026)
    - riderId: Rider ID (e.g., R42)
    
    Returns:
    - 200: Tour rider found (includes rider profile)
    - 400: Invalid input
    - 404: Tour rider not found
    - 500: Server error
    """
    try:
        # Extract path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        rider_id = event.get('pathParameters', {}).get('riderId')
        
        if not tour_id or not rider_id:
            return bad_request_response("tourId and riderId are required in path")
        
        # Validate IDs
        try:
            validate_tour_id(tour_id)
            validate_rider_id(rider_id)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Get tour rider record from tour-specific table
        logger.info(f"Fetching tour rider: {tour_id}/{rider_id}")
        tour_rider = get_tour_item(
            table_type='TourRider',
            tour_id=tour_id,
            key={'riderId': rider_id}
        )
        
        if not tour_rider:
            logger.info(f"Tour rider not found: {tour_id}/{rider_id}")
            return not_found_response("TourRider", rider_id)
        
        # Get rider profile for additional details
        profile_id = tour_rider.get('profileId')
        if profile_id:
            logger.info(f"Fetching rider profile: {profile_id}")
            rider_profile = get_item(
                table_name_env='RIDER_PROFILE_TABLE',
                key={'profileId': profile_id}
            )
            if rider_profile:
                tour_rider['profile'] = rider_profile
                tour_rider['personalCode'] = rider_profile.get('personalCode')
        
        logger.info(f"Successfully retrieved tour rider: {tour_id}/{rider_id}")
        return success_response(tour_rider)
        
    except Exception as e:
        logger.error(f"Error getting tour rider: {str(e)}", exc_info=True)
        return internal_error_response("Failed to get tour rider")
