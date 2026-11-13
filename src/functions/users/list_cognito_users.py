"""
List minimal Cognito users for frontend user-name mapping.

Route: GET /v1/users/cognito
Returns only `sub` and `name` attributes from the management user pool.
"""

import sys

from botocore.exceptions import ClientError

from logger import get_logger, log_event
from rbac import Permission, require_permission
from response import success_response
from handler_utils import api_handler
from usermgmt_common import (
    cognito_error_response,
    get_cognito_client,
    get_management_user_pool_id,
)

sys.path.insert(0, "/opt/python")


logger = get_logger(__name__)


def _is_attribute_constraint_error(exc: ClientError) -> bool:
    """Return True for projected ListUsers InvalidParameterException errors."""
    error = exc.response.get("Error", {})
    return error.get("Code") == "InvalidParameterException"


def _to_min_user(cognito_user):
    """Map Cognito user payload to minimal frontend-safe shape."""
    attrs = {
        attr.get("Name"): attr.get("Value")
        for attr in cognito_user.get("Attributes", [])
    }
    user_sub = attrs.get("sub")
    if not user_sub:
        return None
    return {
        "sub": user_sub,
        "name": attrs.get("name"),
    }


@api_handler("Failed to list Cognito users")
def lambda_handler(event, context):
    """Return all Cognito users with only `sub` and `name` attributes."""
    try:
        log_event(logger, event)

        deny = require_permission(event, Permission.READ)
        if deny:
            return deny

        cognito = get_cognito_client()
        user_pool_id = get_management_user_pool_id()

        users = []
        next_token = None

        use_attribute_projection = True

        while True:
            params = {
                "UserPoolId": user_pool_id,
                "Limit": 60,
            }
            if use_attribute_projection:
                params["AttributesToGet"] = ["sub", "name"]
            if next_token:
                params["PaginationToken"] = next_token

            try:
                response = cognito.list_users(**params)
            except ClientError as exc:
                if use_attribute_projection and _is_attribute_constraint_error(exc):
                    # Cognito rejects AttributesToGet when any returned user is missing
                    # one of the requested attributes (for example, missing `name`).
                    # Fallback to unprojected ListUsers and still expose only sub/name.
                    logger.warning(
                        "ListUsers attribute projection rejected; retrying without AttributesToGet"
                    )
                    use_attribute_projection = False
                    next_token = None
                    users = []
                    continue
                raise

            for cognito_user in response.get("Users", []):
                mapped = _to_min_user(cognito_user)
                if mapped:
                    users.append(mapped)

            next_token = response.get("PaginationToken")
            if not next_token:
                break

        return success_response(
            {
                "users": users,
                "count": len(users),
            }
        )
    except ClientError as exc:
        logger.warning("Cognito list users failed: %s", str(exc))
        return cognito_error_response(exc)
