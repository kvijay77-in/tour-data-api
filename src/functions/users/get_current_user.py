"""
Lambda function to get current user details from JWT token

Route: GET /v1/users/me
No DynamoDB access needed - returns JWT claims only.
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, unauthorized_response, internal_error_response

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get current authenticated user details from JWT token
    
    Authorization: Bearer <JWT token>
    
    Returns:
    - 200: Current user details
    - 401: Unauthorized (no valid token)
    - 500: Server error
    """
    try:
        # Extract user info from authorizer context
        # API Gateway HTTP API with JWT authorizer populates requestContext.authorizer.jwt.claims
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        jwt_claims = authorizer.get('jwt', {}).get('claims', {})
        
        if not jwt_claims:
            logger.warning("No JWT claims found in request context")
            return unauthorized_response("No valid authentication token")
        
        # Extract user information from JWT claims
        user_id = jwt_claims.get('sub')
        email = jwt_claims.get('email')
        username = jwt_claims.get('cognito:username') or jwt_claims.get('username')
        
        if not user_id:
            logger.warning("No user ID (sub) in JWT claims")
            return unauthorized_response("Invalid authentication token")
        
        # Build user response from JWT claims only
        user = {
            'userId': user_id,
            'email': email,
            'username': username,
            'emailVerified': jwt_claims.get('email_verified', False)
        }
        
        logger.info(f"Successfully retrieved current user: {user_id}")
        return success_response(user)
        
    except Exception as e:
        logger.error(f"Error getting current user: {str(e)}", exc_info=True)
        return internal_error_response("Failed to get current user")
