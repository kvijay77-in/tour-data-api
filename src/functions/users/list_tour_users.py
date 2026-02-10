"""
Lambda function to list all users (admin/staff) for a tour
"""
import json
import os
import sys

# Add common layer to path
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, error_response, bad_request_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import query_items

logger = get_logger(__name__)

USER_TABLE = os.environ['USER_TABLE']


def lambda_handler(event, context):
    """
    List all users (admin/staff) for a tour
    
    Path parameter: tourId (e.g., TOUR2026)
    Query parameter: role (optional - ADMIN, STAFF)
    
    Returns:
    - 200: List of users (may be empty)
    - 400: Invalid tour ID
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
            logger.warning(f"Invalid tour ID format: {tour_id}", exc_info=True)
            return bad_request_response(str(e))
        
        # Get optional role filter from query parameters
        role_filter = event.get('queryStringParameters', {}).get('role') if event.get('queryStringParameters') else None
        
        # Validate role if provided
        if role_filter and role_filter not in ['ADMIN', 'STAFF']:
            return bad_request_response("Invalid role. Must be ADMIN or STAFF")
        
        # Query all users for this tour
        logger.info(f"Querying users for tour: {tour_id}")
        users = query_items(
            table_name=USER_TABLE,
            key_condition_expression='tourId = :tourId',
            expression_attribute_values={
                ':tourId': tour_id
            }
        )
        
        # Filter by role if specified
        if role_filter:
            users = [user for user in users if user.get('role') == role_filter]
            logger.info(f"Filtered to {len(users)} users with role {role_filter}")
        
        # Remove sensitive fields before returning
        for user in users:
            # Don't expose password hashes or sensitive data
            user.pop('passwordHash', None)
        
        logger.info(f"Successfully retrieved {len(users)} users for tour {tour_id}")
        return success_response(users)
        
    except Exception as e:
        logger.error(f"Error listing users: {str(e)}", exc_info=True)
        return error_response(f"Failed to list users: {str(e)}")
