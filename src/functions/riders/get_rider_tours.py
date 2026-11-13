"""List rider tour participation records by profile ID."""

import sys

from logger import get_logger
from response import success_response, bad_request_response, internal_error_response
from dynamodb_utils import query_items
from ownership import require_own_profile

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)

TABLE_ENV = 'RIDER_TOURS_TABLE'


def lambda_handler(event, context):
    try:
        path_params = event.get('pathParameters', {})
        profile_id = (path_params.get('profileId') or '').strip()
        if not profile_id:
            return bad_request_response('profileId is required in path')

        deny = require_own_profile(event, profile_id)
        if deny:
            return deny

        participations = query_items(
            table_name_env=TABLE_ENV,
            key_condition_expression='profileId = :profileId',
            expression_values={':profileId': profile_id},
        )

        return success_response({'profileId': profile_id, 'count': len(participations), 'tours': participations})

    except Exception as exc:
        logger.error("Error listing rider tour participations: %s", exc, exc_info=True)
        return internal_error_response('Failed to list rider tour participations')
