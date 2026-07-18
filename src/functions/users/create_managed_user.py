"""
Create user in management Cognito User Pool and assign role groups.

Route: POST /v1/admin/usermgmt/users
"""

import sys
sys.path.insert(0, '/opt/python')

from botocore.exceptions import ClientError

from logger import get_logger, log_event
from response import (
    success_response,
    validation_error_response,
    conflict_response,
    internal_error_response,
)
from usermgmt_common import (
    audit_log,
    cognito_error_response,
    generate_username,
    get_cognito_client,
    get_management_user_pool_id,
    list_pool_groups,
    normalize_name,
    parse_json_body,
    require_admin_only,
    validate_phone_number,
    validate_roles,
)
from validation import ValidationError, validate_email


logger = get_logger(__name__)


def _create_attributes(body):
    attrs = [
        {"Name": "email", "Value": body["email"]},
        {"Name": "email_verified", "Value": "true"},
    ]

    if "phoneNumber" in body and body["phoneNumber"]:
        attrs.append({"Name": "phone_number", "Value": body["phoneNumber"]})

    if "name" in body and body["name"]:
        attrs.append({"Name": "name", "Value": body["name"]})

    return attrs


def lambda_handler(event, context):
    target_user_sub = None
    try:
        log_event(logger, event)

        deny = require_admin_only(event)
        if deny:
            return deny

        body = parse_json_body(event)

        email = (body.get("email") or "").strip()
        if not email:
            raise ValidationError("email is required", {"field": "email"})
        validate_email(email)

        phone_number = body.get("phoneNumber")
        if phone_number is not None and phone_number != "":
            validate_phone_number(phone_number)

        name = normalize_name(body.get("name"))
        if name is not None:
            body["name"] = name

        if "roles" not in body:
            raise ValidationError("roles is required", {"field": "roles"})

        cognito = get_cognito_client()
        user_pool_id = get_management_user_pool_id()
        valid_groups = set(list_pool_groups(cognito, user_pool_id))
        roles = validate_roles(body.get("roles"), valid_groups)

        create_response = cognito.admin_create_user(
            UserPoolId=user_pool_id,
            Username=generate_username(),
            UserAttributes=_create_attributes(
                {
                    "email": email,
                    "phoneNumber": phone_number,
                    "name": name,
                }
            ),
        )

        created_username = create_response["User"]["Username"]
        target_user_sub = next(
            (
                attr["Value"]
                for attr in create_response["User"].get("Attributes", [])
                if attr["Name"] == "sub"
            ),
            None,
        )

        assigned_roles = []
        failed_roles = []
        role_error_message = None

        for role in roles:
            try:
                cognito.admin_add_user_to_group(
                    UserPoolId=user_pool_id,
                    Username=created_username,
                    GroupName=role,
                )
                assigned_roles.append(role)
            except ClientError as role_exc:
                failed_roles.append(role)
                role_error_message = role_exc.response.get("Error", {}).get("Message", str(role_exc))
                break

        if failed_roles:
            rollback_succeeded = False
            try:
                cognito.admin_delete_user(UserPoolId=user_pool_id, Username=created_username)
                rollback_succeeded = True
            except ClientError:
                rollback_succeeded = False

            audit_log(
                action="CREATE_USER",
                result="FAILURE",
                event=event,
                target_cognito_user_id=target_user_sub,
                extra={
                    "failedRoles": failed_roles,
                    "assignedRolesBeforeFailure": assigned_roles,
                    "rollbackAttempted": True,
                    "rollbackSucceeded": rollback_succeeded,
                },
            )

            return conflict_response(
                message="Role assignment failed for created user",
                error_code="ROLE_ASSIGNMENT_CONFLICT",
                details={
                    "rollbackAttempted": True,
                    "rollbackSucceeded": rollback_succeeded,
                    "failedRoles": failed_roles,
                    "assignedRolesBeforeFailure": assigned_roles,
                    "reason": role_error_message,
                },
            )

        if not target_user_sub:
            created_user = cognito.admin_get_user(
                UserPoolId=user_pool_id,
                Username=created_username,
            )
            target_user_sub = next(
                (
                    attr["Value"]
                    for attr in created_user.get("UserAttributes", [])
                    if attr["Name"] == "sub"
                ),
                None,
            )

        audit_log(
            action="CREATE_USER",
            result="SUCCESS",
            event=event,
            target_cognito_user_id=target_user_sub,
            extra={"assignedRoles": roles},
        )

        return success_response(
            {
                "cognitoUserId": target_user_sub,
                "username": created_username,
            },
            status_code=201,
        )

    except ValidationError as exc:
        audit_log(
            action="CREATE_USER",
            result="FAILURE",
            event=event,
            target_cognito_user_id=target_user_sub,
            extra={"reason": exc.message},
        )
        return validation_error_response(exc.message, exc.details)
    except ClientError as exc:
        audit_log(
            action="CREATE_USER",
            result="FAILURE",
            event=event,
            target_cognito_user_id=target_user_sub,
            extra={"reason": str(exc)},
        )
        logger.warning("Cognito create user failed: %s", str(exc))
        return cognito_error_response(exc)
    except Exception as exc:
        audit_log(
            action="CREATE_USER",
            result="FAILURE",
            event=event,
            target_cognito_user_id=target_user_sub,
            extra={"reason": str(exc)},
        )
        logger.error("Error creating managed user: %s", str(exc), exc_info=True)
        return internal_error_response("Failed to create user")
