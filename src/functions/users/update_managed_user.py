"""
Update managed Cognito user profile and roles.

Route: PUT /v1/admin/usermgmt/users/{cognitoUserId}
"""

import sys

from botocore.exceptions import ClientError

from logger import get_logger, log_event
from response import (
    success_response,
    validation_error_response,
    internal_error_response,
)
from usermgmt_common import (
    audit_log,
    cognito_error_response,
    get_cognito_client,
    get_management_user_pool_id,
    get_user_by_sub,
    get_user_groups,
    list_pool_groups,
    normalize_name,
    parse_json_body,
    require_admin_only,
    validate_cognito_user_id,
    validate_phone_number,
    validate_roles,
)
from validation import ValidationError, validate_email

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
        body = parse_json_body(event)

        has_email = "email" in body
        has_phone = "phoneNumber" in body
        has_name = "name" in body
        has_roles = "roles" in body
        if not any([has_email, has_phone, has_name, has_roles]):
            raise ValidationError(
                "At least one of email, phoneNumber, name, roles must be provided"
            )

        cognito = get_cognito_client()
        user_pool_id = get_management_user_pool_id()
        user = get_user_by_sub(cognito, user_pool_id, target_user_id)
        if not user:
            return cognito_error_response(
                ClientError(
                    {"Error": {"Code": "UserNotFoundException", "Message": "User not found"}},
                    "AdminUpdateUserAttributes",
                )
            )

        username = user["Username"]
        attrs_to_update = []

        if has_email:
            email = (body.get("email") or "").strip()
            if not email:
                raise ValidationError("email cannot be empty", {"field": "email"})
            validate_email(email)
            attrs_to_update.append({"Name": "email", "Value": email})
            attrs_to_update.append({"Name": "email_verified", "Value": "true"})

        if has_phone:
            phone_number = body.get("phoneNumber")
            if phone_number in (None, ""):
                attrs_to_update.append({"Name": "phone_number", "Value": ""})
            else:
                validate_phone_number(phone_number)
                attrs_to_update.append({"Name": "phone_number", "Value": phone_number})

        if has_name:
            name = normalize_name(body.get("name"))
            attrs_to_update.append({"Name": "name", "Value": name or ""})

        if attrs_to_update:
            cognito.admin_update_user_attributes(
                UserPoolId=user_pool_id,
                Username=username,
                UserAttributes=attrs_to_update,
            )

        if has_roles:
            valid_groups = set(list_pool_groups(cognito, user_pool_id))
            requested_roles = validate_roles(body.get("roles"), valid_groups)
            current_roles = set(get_user_groups(cognito, user_pool_id, username))
            requested_set = set(requested_roles)

            to_remove = sorted(current_roles - requested_set)
            to_add = sorted(requested_set - current_roles)

            for role in to_remove:
                cognito.admin_remove_user_from_group(
                    UserPoolId=user_pool_id,
                    Username=username,
                    GroupName=role,
                )

            for role in to_add:
                cognito.admin_add_user_to_group(
                    UserPoolId=user_pool_id,
                    Username=username,
                    GroupName=role,
                )

        audit_log(
            action="UPDATE_USER",
            result="SUCCESS",
            event=event,
            target_cognito_user_id=target_user_id,
            extra={
                "updatedFields": [
                    field
                    for field in ["email", "phoneNumber", "name", "roles"]
                    if field in body
                ]
            },
        )

        return success_response({"cognitoUserId": target_user_id})

    except ValidationError as exc:
        audit_log(
            action="UPDATE_USER",
            result="FAILURE",
            event=event,
            target_cognito_user_id=target_user_id,
            extra={"reason": exc.message},
        )
        return validation_error_response(exc.message, exc.details)
    except ClientError as exc:
        audit_log(
            action="UPDATE_USER",
            result="FAILURE",
            event=event,
            target_cognito_user_id=target_user_id,
            extra={"reason": str(exc)},
        )
        return cognito_error_response(exc)
    except Exception as exc:
        audit_log(
            action="UPDATE_USER",
            result="FAILURE",
            event=event,
            target_cognito_user_id=target_user_id,
            extra={"reason": str(exc)},
        )
        logger.error("Error updating managed user: %s", str(exc), exc_info=True)
        return internal_error_response("Failed to update user")
