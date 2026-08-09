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
from response import (
    success_response, not_found_response, 
    bad_request_response, internal_error_response, 
    conflict_response, unprocessable_content_response
)
from validation import (
    validate_email,
    validate_required_fields,
    validate_rider_profile_optional_fields,
    validate_emergency_contact,
    build_emergency_contact_from_profile,
    ValidationError,
    normalize_personal_code,
)
from dynamodb_utils import get_item, put_item, query_items
from models import utc_now_iso

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Update a rider profile
    
    Path parameter: profileId (UUID)
        Body: JSON with fields to update (name, email, phone, emergencyContact,
            dateOfBirth, gender, address are mandatory; photoS3Key and personalCode are optional)
    
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

        legacy_contact_fields = {'emergencyContactName', 'emergencyContactPhone', 'emergencyContactRelationship', 'Relationship'}
        legacy_fields_present = any(field in body for field in legacy_contact_fields)
        if 'emergencyContact' in body and legacy_fields_present:
            return bad_request_response(
                "Provide either emergencyContact object or legacy emergency contact fields, not both"
            )

        if legacy_fields_present:
            base_contact = build_emergency_contact_from_profile(existing_rider) or {
                'name': None,
                'phone': None,
                'relation': None,
            }
            if 'emergencyContactName' in body:
                base_contact['name'] = body.get('emergencyContactName')
            if 'emergencyContactPhone' in body:
                base_contact['phone'] = body.get('emergencyContactPhone')
            if 'emergencyContactRelationship' in body:
                base_contact['relation'] = body.get('emergencyContactRelationship')
            if 'Relationship' in body:
                base_contact['relation'] = body.get('Relationship')
            body['emergencyContact'] = base_contact
        
        # Validate updatable fields
        updatable_fields = [
            'name',
            'email',
            'phone',
            'emergencyContact',
            'photoS3Key',
            'personalCode',
            'dateOfBirth',
            'gender',
            'address',
        ]
        updates = {k: v for k, v in body.items() if k in updatable_fields}
        
        if not updates:
            return bad_request_response("No valid fields to update")

        # Validate mandatory fields if they are being updated to ensure they are not set to None or empty.
        mandatory_profile_fields = [k for k in updatable_fields if k in updates]
        try:
            validate_required_fields(updates, mandatory_profile_fields)
        except ValidationError as e:
            return unprocessable_content_response(str(e))

        # Validate optional rider profile fields
        try:
            validate_rider_profile_optional_fields(updates, require_mandatory_fields=FalseuP)
        except ValidationError as e:
            return unprocessable_content_response(str(e))

        if 'emergencyContact' in updates:
            try:
                validate_emergency_contact(updates['emergencyContact'])
            except ValidationError as e:
                return unprocessable_content_response(str(e))
        
        # Validate email if provided
        if 'email' in updates:
            try:
                validate_email(updates['email'])
            except ValidationError as e:
                return unprocessable_content_response(f"Invalid email: {str(e)}")

        if 'personalCode' in updates:
            try:
                normalized_personal_code = normalize_personal_code(updates.get('personalCode'))
            except ValidationError as e:
                return unprocessable_content_response(str(e))

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
        if 'dateOfBirth' in updates and updates['dateOfBirth'] is None:
            updated_rider.pop('dateOfBirth', None)
        if 'gender' in updates and updates['gender'] is None:
            updated_rider.pop('gender', None)
        if 'address' in updates and updates['address'] is None:
            updated_rider.pop('address', None)
        # Canonicalize to grouped emergencyContact map in storage.
        updated_rider.pop('emergencyContactName', None)
        updated_rider.pop('emergencyContactPhone', None)
        updated_rider.pop('emergencyContactRelationship', None)
        updated_rider.pop('Relationship', None)
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
