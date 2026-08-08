"""
Create rider profile Lambda function

Creates a new rider profile in the shared RiderProfile table.
Used during rider sign-up in the Tour Rider App.
Routes: POST /v1/riders/profile and POST /v1/riders/profile/{profileId}
"""

import sys
sys.path.insert(0, '/opt/python')

import json
import uuid
from botocore.exceptions import ClientError

from logger import get_logger, log_event
from response import (
    success_response, bad_request_response, conflict_response,
    internal_error_response, unprocessable_content_response
)
from dynamodb_utils import put_item, query_items
from validation import (
    validate_email,
    validate_required_fields,
    validate_rider_profile_optional_fields,
    validate_emergency_contact,
    ValidationError,
    build_emergency_contact_from_profile,
    normalize_personal_code,
)
from models import utc_now_iso

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Create a new rider profile

    Path parameter (optional):
        profileId: Profile ID to use for creation

    Body:
        name: Full name (required)
        email: Email address (required)
        phone: Phone number (required)
        emergencyContact: Map with fields name, phone, relation (required)
        personalCode: Rider personal code (optional, normalized to uppercase)
        address: Map with fields line1, line2, city, state, country, postalCode (optional)
        dateOfBirth: ISO date string YYYY-MM-DD (optional)
        gender: Male|Female|Other|Prefer not to say (optional)

    Returns:
    - 201: Rider profile created
    - 400: Invalid input
    - 409: Email already exists
    - 500: Server error
    """
    try:
        log_event(logger, event)

        # Parse request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")

        # Optional path override for profileId: use provided value when present.
        profile_id = (event.get('pathParameters') or {}).get('profileId')

        # Backward compatibility: map legacy emergency contact attributes to emergencyContact.
        if 'emergencyContact' not in body:
            derived_emergency_contact = build_emergency_contact_from_profile(body)
            if derived_emergency_contact is not None:
                body['emergencyContact'] = derived_emergency_contact

        # Validate required fields
        try:
            validate_required_fields(body, [
                'name', 'email', 'phone',
                'emergencyContact'
            ])
        except ValidationError as e:
            return unprocessable_content_response(str(e))

        try:
            validate_emergency_contact(body.get('emergencyContact'))
        except ValidationError as e:
            return unprocessable_content_response(str(e))

        # Validate optional rider profile fields
        try:
            validate_rider_profile_optional_fields(body)
        except ValidationError as e:
            return unprocessable_content_response(str(e))

        # Validate email
        try:
            validate_email(body['email'])
        except ValidationError as e:
            return unprocessable_content_response(str(e))

        # Normalize optional personal code
        try:
            normalized_personal_code = normalize_personal_code(body.get('personalCode'))
        except ValidationError as e:
            return unprocessable_content_response(str(e))

        # Check for duplicate email
        existing = query_items(
            table_name_env='RIDER_PROFILE_TABLE',
            key_condition_expression='email = :email',
            expression_values={':email': body['email']},
            index_name='EmailIndex',
            limit=1
        )

        if existing:
            return conflict_response(
                f"A rider profile with email '{body['email']}' already exists",
                error_code="EMAIL_ALREADY_EXISTS"
            )

        if normalized_personal_code:
            existing_code = query_items(
                table_name_env='RIDER_PROFILE_TABLE',
                key_condition_expression='personalCode = :personalCode',
                expression_values={':personalCode': normalized_personal_code},
                index_name='PersonalCodeIndex',
                limit=1
            )
            if existing_code:
                return conflict_response(
                    f"A rider profile with personalCode '{normalized_personal_code}' already exists",
                    error_code="PERSONAL_CODE_ALREADY_EXISTS"
                )

        # Create profile
        if not profile_id:
            profile_id = str(uuid.uuid4())
        now = utc_now_iso()

        item = {
            'profileId': profile_id,
            'name': body['name'],
            'email': body['email'],
            'phone': body['phone'],
            'emergencyContact': body['emergencyContact'],
            'createdAt': now,
            'updatedAt': now
        }

        # Optional fields
        if body.get('dateOfBirth') is not None:
            item['dateOfBirth'] = body['dateOfBirth']
        if body.get('gender') is not None:
            item['gender'] = body['gender']
        if body.get('address') is not None:
            item['address'] = body['address']
        if normalized_personal_code:
            item['personalCode'] = normalized_personal_code

        logger.info(f"Creating rider profile: {profile_id}")
        try:
            put_item(
                table_name_env='RIDER_PROFILE_TABLE',
                item=item,
                condition_expression='attribute_not_exists(profileId)'
            )
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'ConditionalCheckFailedException':
                return conflict_response(
                    f"Rider profile '{profile_id}' already exists",
                    error_code="PROFILE_ALREADY_EXISTS"
                )
            raise

        logger.info(f"Successfully created rider profile: {profile_id}")
        return success_response(item, status_code=201)

    except Exception as e:
        logger.error(f"Error creating rider profile: {str(e)}", exc_info=True)
        return internal_error_response("Failed to create rider profile")
