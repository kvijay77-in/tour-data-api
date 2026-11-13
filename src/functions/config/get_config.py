"""
Get application configuration items.

Route: GET /v1/config

Query parameters:
- configType (optional):
  - omitted or ALL -> all enabled config entries
  - any configType (e.g. ID_CODE_FORMAT)
  - comma separated types (e.g. ID_CODE_FORMAT,ID_CODE_TYPE)
  - returns 404 when no enabled rows exist for the requested type(s)

Notes:
- includeDisabled is intentionally out of scope.
- Read access requires authenticated users with READ permission.
"""

import sys

import hashlib
import json
from typing import List

from logger import get_logger, log_event
from response import (
    success_response,
    bad_request_response,
    error_response,
    not_modified_response,
    DecimalEncoder,
)
from handler_utils import api_handler
from dynamodb_utils import scan_items, query_items
from rbac import Permission, require_permission
from profile_schema import get_definitions_version

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def _parse_config_types(raw_value: str) -> List[str]:
    if not raw_value:
        return []

    entries = [part.strip().upper() for part in raw_value.split(',') if part.strip()]
    if not entries:
        return []

    if any(entry == 'ALL' for entry in entries):
        if len(entries) > 1:
            raise ValueError("configType=ALL cannot be combined with other configType values")
        return []

    # Preserve stable order and drop duplicates.
    deduped = []
    seen = set()
    for entry in entries:
        if entry in seen:
            continue
        deduped.append(entry)
        seen.add(entry)

    return deduped


def _query_enabled_by_type(config_types: List[str]):
    items = []
    for config_type in config_types:
        typed_items = query_items(
            table_name_env='APP_CONFIG_TABLE',
            key_condition_expression='configType = :ct',
            expression_values={':ct': config_type, ':enabled': True},
            filter_expression='enabled = :enabled',
        )
        items.extend(typed_items)
    return items


def _query_all_enabled():
    return scan_items(
        table_name_env='APP_CONFIG_TABLE',
        filter_expression='enabled = :enabled',
        expression_values={':enabled': True},
    )


@api_handler('Failed to retrieve config')
def lambda_handler(event, context):
    log_event(logger, event)

    deny = require_permission(event, Permission.READ)
    if deny:
        return deny

    query_params = event.get('queryStringParameters') or {}
    raw_config_type = (query_params.get('configType') or '').strip()

    try:
        config_types = _parse_config_types(raw_config_type)
    except ValueError as exc:
        return bad_request_response(str(exc))

    if config_types:
        items = _query_enabled_by_type(config_types)
        if not items:
            return error_response(
                error_code='INVALID_CONFIG_TYPE',
                message='Missing or Invalid configType',
                status_code=404,
            )
    else:
        items = _query_all_enabled()

    items.sort(key=lambda item: (item.get('configType', ''), item.get('configId', '')))

    payload = {
        'items': items,
        'definitionsVersion': get_definitions_version(),
    }

    payload_json = json.dumps(payload, sort_keys=True, cls=DecimalEncoder)
    etag = f'"{hashlib.md5(payload_json.encode()).hexdigest()}"'

    request_headers = event.get('headers', {}) or {}
    if_none_match = request_headers.get('if-none-match') or request_headers.get('If-None-Match')
    if if_none_match and if_none_match == etag:
        response = not_modified_response()
        response['headers']['ETag'] = etag
        return response

    response = success_response(payload)
    response['headers']['ETag'] = etag
    return response
