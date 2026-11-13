"""
List users from management Cognito User Pool.

Route: GET /v1/admin/usermgmt/users
"""

import sys

from botocore.exceptions import ClientError

from logger import get_logger, log_event
from response import success_response, validation_error_response
from handler_utils import api_handler
from usermgmt_common import (
    cognito_error_response,
    get_cognito_client,
    get_management_user_pool_id,
    get_user_groups,
    list_pool_groups,
    parse_bool_query,
    parse_limit,
    require_admin_only,
    to_managed_user,
    validate_roles,
)
from validation import ValidationError

sys.path.insert(0, "/opt/python")


logger = get_logger(__name__)


@api_handler("Failed to list users")
def lambda_handler(event, context):
    try:
        log_event(logger, event)

        deny = require_admin_only(event)
        if deny:
            return deny

        query = event.get("queryStringParameters") or {}
        role_filter = query.get("role")
        enabled_filter = parse_bool_query(query.get("enabled"), "enabled")
        limit = parse_limit(query.get("limit"))
        next_token = query.get("nextToken")

        cognito = get_cognito_client()
        user_pool_id = get_management_user_pool_id()

        valid_groups = set(list_pool_groups(cognito, user_pool_id))
        if role_filter:
            validate_roles([role_filter], valid_groups, field_name="role")

        params = {"UserPoolId": user_pool_id}
        if limit:
            params["Limit"] = limit
        if next_token:
            params["PaginationToken"] = next_token

        response = cognito.list_users(**params)

        users = []
        for cognito_user in response.get("Users", []):
            roles = get_user_groups(cognito, user_pool_id, cognito_user["Username"])
            managed_user = to_managed_user(cognito_user, roles)

            if role_filter and role_filter not in roles:
                continue
            if enabled_filter is not None and managed_user["enabled"] != enabled_filter:
                continue
            users.append(managed_user)

        return success_response(
            {
                "users": users,
                "nextToken": response.get("PaginationToken"),
            }
        )
    except ValidationError as exc:
        return validation_error_response(exc.message, exc.details)
    except ClientError as exc:
        logger.warning("Cognito list users failed: %s", str(exc))
        return cognito_error_response(exc)
