"""
Lambda function to list all users (admin/staff) for a tour

Uses tour-specific User-{tourId} table.
Route: GET /v1/tours/{tourId}/users
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, bad_request_response, internal_error_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import scan_tour_items
from models import UserRole

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    List all users (admin/staff) for a tour
    
    Path parameter: tourId (e.g., TOT-2026)
    Query parameter: role (optional - ADMINISTRATOR, SUPER_USER, PIT_STOP_CREW, HOTEL_STAFF, GUEST)
    
    Returns:
    - 200: List of users (may be empty)
    - 400: Invalid tour ID or role
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
        
        # Get optional role filter from query parameters
        query_params = event.get('queryStringParameters') or {}
        role_filter = query_params.get('role')
        
        # Validate role if provided
        if role_filter:
            valid_roles = [r.value for r in UserRole]
            if role_filter not in valid_roles:
                return bad_request_response(
                    f"Invalid role. Must be one of: {', '.join(valid_roles)}"
                )
        
        # Scan all users from tour-specific User table
        logger.info(f"Querying users for tour: {tour_id}")
        
        if role_filter:
            users = scan_tour_items(
                table_type='User',
                tour_id=tour_id,
                filter_expression='#role = :role',
                expression_values={':role': role_filter},
                expression_names={'#role': 'role'}
            )
        else:
            users = scan_tour_items(
                table_type='User',
                tour_id=tour_id
            )
        
        logger.info(f"Successfully retrieved {len(users)} users for tour {tour_id}")
        return success_response({
            'users': users,
            'count': len(users),
            'tourId': tour_id
        })
        
    except Exception as e:
        logger.error(f"Error listing users: {str(e)}", exc_info=True)
        return internal_error_response("Failed to list users")
