"""Admin-only AppConfig reader for rider-profile configuration types."""

import sys

from logger import get_logger, log_event
from response import success_response, error_response, bad_request_response
from handler_utils import api_handler
from dynamodb_utils import query_items
from rbac import get_user_groups

sys.path.insert(0, '/opt/python')


logger = get_logger(__name__)

_ALLOWED_TYPES = {'RIDER_PROFILE_ATTRIBUTE', 'RIDER_PROFILE_SECTION', 'LOV'}


def _is_admin(event):
    return 'ADMINISTRATOR' in set(get_user_groups(event))


@api_handler('Failed to retrieve admin config')
def lambda_handler(event, context):
    log_event(logger, event)

    if not _is_admin(event):
        return error_response('FORBIDDEN', 'Admin role is required', status_code=403)

    config_type = ((event.get('pathParameters') or {}).get('configType') or '').strip().upper()
    if config_type not in _ALLOWED_TYPES:
        return bad_request_response('Unsupported configType for admin config read')

    items = query_items(
        table_name_env='APP_CONFIG_TABLE',
        key_condition_expression='configType = :ct',
        expression_values={':ct': config_type},
    )
    items.sort(key=lambda item: item.get('configId', ''))
    return success_response({'items': items, 'count': len(items), 'configType': config_type})
