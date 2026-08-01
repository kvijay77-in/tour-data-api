"""
Lambda function to update a rider profile

Shared RiderProfile table (partition key: profileId).
Route: PUT /v1/riders/profile/{profileId}
"""

import json
import sys
from botocore.exceptions import ClientError

sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, bad_request_response, internal_error_response, conflict_response
from validation import validate_email, validate_required_fields, ValidationError, normalize_personal_code
from dynamodb_utils import get_item, put_item, query_items
from models import utc_now_iso

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Update a rider profile
    
    Path parameter: profileId (UUID)
    Body: JSON with fields to update (name, email, phone, emergencyContactName, emergencyContactPhone)
    
    Returns:
    - 200: Rider profile updated
    - 400: Invalid input
    - 404: Profile not found
    - 500: Server error
    """
    try:
        # Extract profile ID from path parameters
        profile_id = event.get('pathParameters', {}).get('profileId')
        
        if not profile_id:
            return bad_request_response("profileId is required in path")
        
        # Parse request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")
        
        # Get existing rider profile
        logger.info(f"Fetching existing rider profile: {profile_id}")
        existing_rider = get_item(
            table_name_env='RIDER_PROFILE_TABLE',
            key={'profileId': profile_id}
        )
        
        if not existing_rider:
            logger.info(f"Rider profile not found: {profile_id}")
            return not_found_response("RiderProfile", profile_id)
        
        # Validate updatable fields
        updatable_fields = ['name', 'email', 'phone', 'emergencyContactName', 'emergencyContactPhone', 'photoS3Key', 'personalCode']
        updates = {k: v for k, v in body.items() if k in updatable_fields}
        
        if not updates:
            return bad_request_response("No valid fields to update")
        
        # Validate email if provided
        if 'email' in updates:
            try:
                validate_email(updates['email'])
            except ValidationError as e:
                return bad_request_response(f"Invalid email: {str(e)}")

        if 'personalCode' in updates:
            try:
                normalized_personal_code = normalize_personal_code(updates.get('personalCode'))
            except ValidationError as e:
                return bad_request_response(str(e))

            if normalized_personal_code:
                existing_code = query_items(
                    table_name_env='RIDER_PROFILE_TABLE',
                    key_condition_expression='personalCode = :personalCode',
                    expression_values={':personalCode': normalized_personal_code},
                    index_name='PersonalCodeIndex',
                    limit=1
                )
                if existing_code and existing_code[0].get('profileId') != profile_id:
                    return conflict_response(
                        f"A rider profile with personalCode '{normalized_personal_code}' already exists",
                        error_code="PERSONAL_CODE_ALREADY_EXISTS"
                    )

            updates['personalCode'] = normalized_personal_code
        
        # Update rider profile
        updated_rider = {**existing_rider, **updates}
        if 'personalCode' in updates and updates['personalCode'] is None:
            updated_rider.pop('personalCode', None)
        updated_rider['updatedAt'] = utc_now_iso()
        
        logger.info(f"Updating rider profile: {profile_id}")
        try:
            put_item(
                table_name_env='RIDER_PROFILE_TABLE',
                item=updated_rider,
                condition_expression='attribute_exists(profileId)'
            )
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'ConditionalCheckFailedException':
                return not_found_response("RiderProfile", profile_id)
            raise
        
        logger.info(f"Successfully updated rider profile: {profile_id}")
        return success_response(updated_rider)
        
    except Exception as e:
        logger.error(f"Error updating rider profile: {str(e)}", exc_info=True)
        return internal_error_response("Failed to update rider profile")
