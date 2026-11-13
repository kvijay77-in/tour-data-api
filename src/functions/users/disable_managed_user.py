"""
Disable a managed Cognito user account.

Route: POST /v1/admin/usermgmt/users/{cognitoUserId}/disable
"""

import sys

from botocore.exceptions import ClientError

from logger import get_logger, log_event
from response import success_response, validation_error_response, internal_error_response
from usermgmt_common import (
    audit_log,
    cognito_error_response,
    get_cognito_client,
    get_management_user_pool_id,
    get_user_by_sub,
    require_admin_only,
    validate_cognito_user_id,
)
from validation import ValidationError

sys.path.insert(0, '/opt/python')


logger = get_logger(__name__)


def lambda_handler(event, context):
    target_user_id = event.get("pathParameters", {}).get("cognitoUserId")
    try:
        log_event(logger, event)

        deny = require_admin_only(event)
        if deny:
            return deny

        validate_cognito_user_id(target_user_id)

        cognito = get_cognito_client()
        user_pool_id = get_management_user_pool_id()
        user = get_user_by_sub(cognito, user_pool_id, target_user_id)
        if not user:
            return cognito_error_response(
                ClientError(
                    {"Error": {"Code": "UserNotFoundException", "Message": "User not found"}},
                    "AdminDisableUser",
                )
            )

        cognito.admin_disable_user(UserPoolId=user_pool_id, Username=user["Username"])

        audit_log(
            action="DISABLE_USER",
            result="SUCCESS",
            event=event,
            target_cognito_user_id=target_user_id,
        )
        return success_response({"cognitoUserId": target_user_id, "enabled": False})

    except ValidationError as exc:
        audit_log(
            action="DISABLE_USER",
            result="FAILURE",
            event=event,
            target_cognito_user_id=target_user_id,
            extra={"reason": exc.message},
        )
        return validation_error_response(exc.message, exc.details)
    except ClientError as exc:
        audit_log(
            action="DISABLE_USER",
            result="FAILURE",
            event=event,
            target_cognito_user_id=target_user_id,
            extra={"reason": str(exc)},
        )
        return cognito_error_response(exc)
    except Exception as exc:
        audit_log(
            action="DISABLE_USER",
            result="FAILURE",
            event=event,
            target_cognito_user_id=target_user_id,
            extra={"reason": str(exc)},
        )
        logger.error("Error disabling managed user: %s", str(exc), exc_info=True)
        return internal_error_response("Failed to disable user")
