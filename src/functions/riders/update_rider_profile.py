"""Update rider profile with configuration-driven merge semantics."""

import sys

import json
from botocore.exceptions import ClientError

from logger import get_logger, log_event
from response import success_response, not_found_response, bad_request_response, conflict_response, error_response
from handler_utils import api_handler
from validation import build_emergency_contact_from_profile, ValidationError
from dynamodb_utils import get_item, put_item, query_items
from models import utc_now_iso
from ownership import require_own_profile
from profile_schema import (
    ensure_definitions_version,
    merge_profile_values,
    filter_profile_for_response,
    ProfileSchemaError,
    get_user_role_flags,
)

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


@api_handler('Failed to update rider profile')
def lambda_handler(event, context):
    try:
        log_event(logger, event)

        profile_id = (event.get('pathParameters') or {}).get('profileId')
        if not profile_id:
            return bad_request_response('profileId is required in path')

        deny = require_own_profile(event, profile_id)
        role_flags = get_user_role_flags(event)
        if deny and not role_flags['is_admin']:
            return deny

        try:
            body = json.loads(event.get('body', '{}') or '{}')
        except json.JSONDecodeError:
            return bad_request_response('Invalid JSON in request body')
        if not isinstance(body, dict):
            return bad_request_response('Request body must be a JSON object')

        existing_rider = get_item('RIDER_PROFILE_TABLE', {'profileId': profile_id})
        if not existing_rider:
            return not_found_response('RiderProfile', profile_id)
        ensure_definitions_version(body.get('definitionsVersion'))

        legacy_contact_fields = {'emergencyContactName', 'emergencyContactPhone', 'emergencyContactRelationship', 'Relationship'}
        legacy_fields_present = any(field in body for field in legacy_contact_fields)
        if 'emergencyContact' in body and legacy_fields_present:
            return bad_request_response('Provide either emergencyContact object or legacy emergency contact fields, not both')

        if legacy_fields_present:
            base_contact = build_emergency_contact_from_profile(existing_rider) or {'name': None, 'phone': None, 'relation': None}
            if 'emergencyContactName' in body:
                base_contact['name'] = body.get('emergencyContactName')
            if 'emergencyContactPhone' in body:
                base_contact['phone'] = body.get('emergencyContactPhone')
            if 'emergencyContactRelationship' in body:
                base_contact['relation'] = body.get('emergencyContactRelationship')
            if 'Relationship' in body:
                base_contact['relation'] = body.get('Relationship')
            body['emergencyContact'] = base_contact

        merged_profile, definitions_version = merge_profile_values(
            existing_profile=existing_rider,
            submitted_payload=body,
            event=event,
            enforce_required=True,
            is_save=True,
        )

        merged_profile['updatedAt'] = utc_now_iso()
        merged_profile.pop('emergencyContactName', None)
        merged_profile.pop('emergencyContactPhone', None)
        merged_profile.pop('emergencyContactRelationship', None)
        merged_profile.pop('Relationship', None)

        email = merged_profile.get('email')
        if email:
            existing_email = query_items(
                table_name_env='RIDER_PROFILE_TABLE',
                key_condition_expression='email = :email',
                expression_values={':email': email},
                index_name='EmailIndex',
                limit=1,
            )
            if existing_email and existing_email[0].get('profileId') != profile_id:
                return conflict_response(
                    f"A rider profile with email '{email}' already exists",
                    error_code='EMAIL_ALREADY_EXISTS',
                )

        personal_code = merged_profile.get('personalCode')
        if personal_code:
            existing_code = query_items(
                table_name_env='RIDER_PROFILE_TABLE',
                key_condition_expression='personalCode = :personalCode',
                expression_values={':personalCode': personal_code},
                index_name='PersonalCodeIndex',
                limit=1,
            )
            if existing_code and existing_code[0].get('profileId') != profile_id:
                return conflict_response(
                    f"A rider profile with personalCode '{personal_code}' already exists",
                    error_code='PERSONAL_CODE_ALREADY_EXISTS',
                )

        try:
            put_item(
                table_name_env='RIDER_PROFILE_TABLE',
                item=merged_profile,
                condition_expression='attribute_exists(profileId)',
            )
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                return not_found_response('RiderProfile', profile_id)
            raise

        response_payload = filter_profile_for_response(merged_profile, event=event, staff_mode=False)
        response_payload['definitionsVersion'] = definitions_version
        return success_response(response_payload)

    except ProfileSchemaError as exc:
        return error_response(exc.code, exc.message, status_code=exc.status_code)
    except ValidationError as exc:
        return error_response('VALIDATION_ERROR', str(exc), status_code=422)
