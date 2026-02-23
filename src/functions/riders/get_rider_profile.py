"""
Lambda function to get a rider profile by profile ID

Shared RiderProfile table (partition key: profileId).
Route: GET /v1/riders/profile/{profileId}
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, bad_request_response, internal_error_response
from dynamodb_utils import get_item

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get a rider profile by profile ID
    
    Path parameter: profileId (UUID)
    
    Returns:
    - 200: Rider profile found
    - 400: Missing profileId
    - 404: Profile not found
    - 500: Server error
    """
    try:
        # Extract profile ID from path parameters
        profile_id = event.get('pathParameters', {}).get('profileId')
        
        if not profile_id:
            return bad_request_response("profileId is required in path")
        
        # Get rider profile from DynamoDB
        logger.info(f"Fetching rider profile: {profile_id}")
        rider = get_item(
            table_name_env='RIDER_PROFILE_TABLE',
            key={'profileId': profile_id}
        )
        
        if not rider:
            logger.info(f"Rider profile not found: {profile_id}")
            return not_found_response("RiderProfile", profile_id)
        
        logger.info(f"Successfully retrieved rider profile: {profile_id}")
        return success_response(rider)
        
    except Exception as e:
        logger.error(f"Error getting rider profile: {str(e)}", exc_info=True)
        return internal_error_response("Failed to get rider profile")
