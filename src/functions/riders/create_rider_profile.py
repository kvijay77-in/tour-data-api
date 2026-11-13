"""Create rider profile using configuration-driven schema definitions."""

import sys

import json
import uuid
from botocore.exceptions import ClientError

from logger import get_logger, log_event
from response import success_response, bad_request_response, conflict_response, internal_error_response, error_response
from dynamodb_utils import put_item, query_items, get_item
from validation import build_emergency_contact_from_profile, ValidationError
from models import utc_now_iso
from ownership import require_own_profile, resolve_profile_id_for_sub, is_rider_api_request
from profile_schema import (
    ensure_definitions_version,
    merge_profile_values,
    filter_profile_for_response,
    ProfileSchemaError,
    get_user_role_flags,
)

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def _claims(event):
    return (
        event.get('requestContext', {})
        .get('authorizer', {})
        .get('jwt', {})
        .get('claims', {})
    )


def lambda_handler(event, context):
    try:
        log_event(logger, event)

        try:
            body = json.loads(event.get('body', '{}') or '{}')
        except json.JSONDecodeError:
            return bad_request_response('Invalid JSON in request body')
        if not isinstance(body, dict):
            return bad_request_response('Request body must be a JSON object')

        claims = _claims(event)
        rider_api_call = is_rider_api_request(event)
        linked_profile_id = resolve_profile_id_for_sub(claims.get('sub') or '') if rider_api_call else None
        path_profile_id = (event.get('pathParameters') or {}).get('profileId')

        if rider_api_call and path_profile_id and not linked_profile_id:
            return error_response('PROFILE_ACCESS_DENIED', 'Profile ID cannot be supplied before rider link is established', status_code=403)

        profile_id = path_profile_id or linked_profile_id or str(uuid.uuid4())

        role_flags = get_user_role_flags(event)
        explicit_profile_id = path_profile_id
        deny = require_own_profile(event, profile_id)
        if deny and not role_flags['is_admin']:
            rider_api_create_without_link = rider_api_call and not linked_profile_id and not explicit_profile_id
            if not rider_api_create_without_link:
                return deny

        ensure_definitions_version(body.get('definitionsVersion'))

        if 'emergencyContact' not in body:
            derived = build_emergency_contact_from_profile(body)
            if derived is not None:
                body['emergencyContact'] = derived

        now = utc_now_iso()
        draft_profile = {'profileId': profile_id, 'createdAt': now, 'updatedAt': now, 'attributes': {}}

        # COGNITO_EMAIL is system-controlled; prefill from token claim when available.
        if claims.get('email') and 'email' not in body:
            draft_profile['email'] = claims.get('email')

        merged_profile, definitions_version = merge_profile_values(
            existing_profile=draft_profile,
            submitted_payload=body,
            event=event,
            enforce_required=True,
            is_save=True,
        )

        email = merged_profile.get('email')
        if email:
            existing = query_items(
                table_name_env='RIDER_PROFILE_TABLE',
                key_condition_expression='email = :email',
                expression_values={':email': email},
                index_name='EmailIndex',
                limit=1,
            )
            if existing:
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
            if existing_code:
                return conflict_response(
                    f"A rider profile with personalCode '{personal_code}' already exists",
                    error_code='PERSONAL_CODE_ALREADY_EXISTS',
                )

        try:
            put_item(
                table_name_env='RIDER_PROFILE_TABLE',
                item=merged_profile,
                condition_expression='attribute_not_exists(profileId)',
            )
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                return conflict_response(
                    f"Rider profile '{profile_id}' already exists",
                    error_code='PROFILE_ALREADY_EXISTS',
                )
            raise

        response_payload = filter_profile_for_response(merged_profile, event=event, staff_mode=False)
        response_payload['definitionsVersion'] = definitions_version
        return success_response(response_payload, status_code=201)

    except ProfileSchemaError as exc:
        return error_response(exc.code, exc.message, status_code=exc.status_code)
    except ValidationError as exc:
        return error_response('VALIDATION_ERROR', str(exc), status_code=422)
    except Exception as exc:
        logger.error("Error creating rider profile: %s", exc, exc_info=True)
        return internal_error_response('Failed to create rider profile')
