"""Admin-only AppConfig writer for rider profile configuration."""

import sys

import json

from botocore.exceptions import ClientError

from logger import get_logger, log_event
from response import success_response, error_response, bad_request_response, conflict_response
from handler_utils import api_handler
from dynamodb_utils import get_item, put_item
from models import utc_now_iso
from rbac import get_user_groups
from profile_schema import validate_attribute_definitions_entry, get_definitions, ProfileSchemaError

sys.path.insert(0, '/opt/python')


logger = get_logger(__name__)

_ALLOWED_TYPES = {'RIDER_PROFILE_ATTRIBUTE', 'RIDER_PROFILE_SECTION', 'LOV'}


def _jwt_sub(event):
    return (
        event.get('requestContext', {})
        .get('authorizer', {})
        .get('jwt', {})
        .get('claims', {})
        .get('sub')
    )


def _is_admin(event):
    return 'ADMINISTRATOR' in set(get_user_groups(event))


def _validate_section(entry):
    cfg = entry.get('config') or {}
    if not isinstance(cfg, dict):
        raise ProfileSchemaError('config must be an object', 'VALIDATION_ERROR')
    if not cfg.get('label'):
        raise ProfileSchemaError('section label is required', 'VALIDATION_ERROR')
    if cfg.get('order') is None:
        raise ProfileSchemaError('section order is required', 'VALIDATION_ERROR')


def _validate_lov(entry):
    cfg = entry.get('config') or {}
    if not isinstance(cfg, dict):
        raise ProfileSchemaError('config must be an object', 'VALIDATION_ERROR')
    if not cfg.get('label'):
        raise ProfileSchemaError('lov label is required', 'VALIDATION_ERROR')
    items = cfg.get('items')
    if items is None or not isinstance(items, list):
        raise ProfileSchemaError('lov items must be an array', 'VALIDATION_ERROR')


def _validate_entry(config_type, new_entry, existing):
    if config_type == 'RIDER_PROFILE_SECTION':
        _validate_section(new_entry)
        return
    if config_type == 'LOV':
        _validate_lov(new_entry)
        return

    defs = get_definitions()
    validate_attribute_definitions_entry(new_entry, existing=existing, definitions=defs)


@api_handler('Failed to write admin config')
def lambda_handler(event, context):
    try:
        log_event(logger, event)

        if not _is_admin(event):
            return error_response('FORBIDDEN', 'Admin role is required', status_code=403)

        path_params = event.get('pathParameters') or {}
        config_type = (path_params.get('configType') or '').strip().upper()
        config_id = (path_params.get('configId') or '').strip()
        if config_type not in _ALLOWED_TYPES:
            return bad_request_response('Unsupported configType for admin config write')
        if not config_id:
            return bad_request_response('configId is required in path')

        try:
            body = json.loads(event.get('body') or '{}')
        except json.JSONDecodeError:
            return bad_request_response('Invalid JSON in request body')

        if not isinstance(body, dict):
            return bad_request_response('Request body must be an object')
        if 'version' not in body:
            return bad_request_response('version is required in request body')

        existing = get_item('APP_CONFIG_TABLE', {'configType': config_type, 'configId': config_id})
        incoming_version = body.get('version')
        if existing:
            if int(incoming_version) != int(existing.get('version', 0)):
                return conflict_response(
                    message='Configuration was updated by another user',
                    error_code='CONFIG_VERSION_CONFLICT',
                )

        entry = {
            'configType': config_type,
            'configId': config_id,
            'enabled': bool(body.get('enabled', True)),
            'description': body.get('description', ''),
            'config': body.get('config') or {},
            'version': int(existing.get('version', 0) + 1) if existing else 1,
            'updatedAt': utc_now_iso(),
            'updatedBy': _jwt_sub(event) or 'unknown',
        }

        _validate_entry(config_type, entry, existing)

        try:
            put_item(
                table_name_env='APP_CONFIG_TABLE',
                item=entry,
                condition_expression='attribute_not_exists(configType) AND attribute_not_exists(configId)' if not existing else None,
            )
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                return conflict_response(
                    message='Configuration was updated by another user',
                    error_code='CONFIG_VERSION_CONFLICT',
                )
            raise

        return success_response(entry)

    except ProfileSchemaError as exc:
        return error_response(error_code=exc.code, message=exc.message, status_code=exc.status_code)
