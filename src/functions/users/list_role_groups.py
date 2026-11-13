"""
List assignable role groups from management Cognito User Pool.

Route: GET /v1/admin/usermgmt/roles
"""

import sys

from logger import get_logger, log_event
from response import success_response, internal_error_response
from usermgmt_common import (
    get_cognito_client,
    get_management_user_pool_id,
    list_pool_groups,
    require_admin_only,
)

sys.path.insert(0, '/opt/python')


logger = get_logger(__name__)


def lambda_handler(event, context):
    try:
        log_event(logger, event)

        deny = require_admin_only(event)
        if deny:
            return deny

        cognito = get_cognito_client()
        user_pool_id = get_management_user_pool_id()
        groups = list_pool_groups(cognito, user_pool_id)

        return success_response({"groups": groups})
    except Exception as exc:
        logger.error("Error listing role groups: %s", str(exc), exc_info=True)
        return internal_error_response("Failed to list role groups")
