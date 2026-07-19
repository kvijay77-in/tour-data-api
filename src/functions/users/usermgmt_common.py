"""
Shared helpers for admin user-management APIs backed by Cognito.
"""

import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

import boto3
from botocore.exceptions import ClientError

from logger import get_logger
from rbac import get_user_groups as get_request_user_groups
from response import error_response, forbidden_response
from validation import ValidationError, validate_email


logger = get_logger(__name__)

E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")
COGNITO_SUB_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def get_cognito_client():
    """Return Cognito Identity Provider client."""
    return boto3.client("cognito-idp")


def get_management_user_pool_id() -> str:
    """Read management user pool id from environment."""
    user_pool_id = os.environ.get("MGMT_USER_POOL_ID", "").strip()
    if not user_pool_id:
        raise RuntimeError("MGMT_USER_POOL_ID is not configured")
    return user_pool_id


def require_admin_only(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Enforce ADMINISTRATOR-only access for user-management endpoints."""
    user_groups = get_request_user_groups(event)
    if "ADMINISTRATOR" not in user_groups:
        return forbidden_response("FORBIDDEN")
    return None


def parse_json_body(event: Dict[str, Any]) -> Dict[str, Any]:
    """Parse and validate request body as JSON object."""
    body_raw = event.get("body") or "{}"
    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Invalid JSON in request body") from exc

    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object")
    return body


def parse_bool_query(value: Optional[str], field_name: str) -> Optional[bool]:
    """Parse optional query string boolean value."""
    if value is None:
        return None
    val = value.strip().lower()
    if val == "true":
        return True
    if val == "false":
        return False
    raise ValidationError(
        f"{field_name} must be 'true' or 'false'",
        {"field": field_name, "value": value},
    )


def parse_limit(value: Optional[str]) -> Optional[int]:
    """Parse optional list limit query parameter."""
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValidationError("limit must be a positive integer") from exc
    if parsed <= 0:
        raise ValidationError("limit must be a positive integer")
    return parsed


def validate_cognito_user_id(cognito_user_id: str) -> None:
    """Validate Cognito user id (sub) without enforcing RFC UUID version bits."""
    if not cognito_user_id or not COGNITO_SUB_PATTERN.fullmatch(cognito_user_id):
        raise ValidationError(
            "cognitoUserId must be a valid Cognito sub",
            {"field": "cognitoUserId", "value": cognito_user_id},
        )


def validate_phone_number(phone_number: str) -> None:
    """Validate E.164 phone number format."""
    if not E164_PATTERN.fullmatch(phone_number):
        raise ValidationError(
            "phoneNumber must be in E.164 format",
            {"field": "phoneNumber", "value": phone_number},
        )


def normalize_name(name: Optional[str]) -> Optional[str]:
    """Trim and normalize name input."""
    if name is None:
        return None
    trimmed = str(name).strip()
    return trimmed


def list_pool_groups(cognito_client, user_pool_id: str) -> List[str]:
    """Return all group names from management user pool (sorted)."""
    groups: List[str] = []
    token = None
    while True:
        params = {"UserPoolId": user_pool_id, "Limit": 60}
        if token:
            params["NextToken"] = token
        response = cognito_client.list_groups(**params)
        groups.extend([group["GroupName"] for group in response.get("Groups", [])])
        token = response.get("NextToken")
        if not token:
            break
    return sorted(groups)


def validate_roles(roles: Any, valid_groups: Set[str], field_name: str = "roles") -> List[str]:
    """Validate role list against dynamic Cognito groups."""
    if not isinstance(roles, list):
        raise ValidationError(f"{field_name} must be an array")
    normalized = []
    for role in roles:
        if not isinstance(role, str) or not role.strip():
            raise ValidationError(f"{field_name} contains an invalid role value")
        normalized.append(role.strip())

    # Deduplicate while preserving order
    deduped = list(dict.fromkeys(normalized))
    if not deduped:
        raise ValidationError(f"{field_name} must be a non-empty array")

    invalid = [role for role in deduped if role not in valid_groups]
    if invalid:
        raise ValidationError(
            f"{field_name} contains unsupported groups",
            {"field": field_name, "invalidRoles": invalid},
        )
    return deduped


def get_user_by_sub(
    cognito_client,
    user_pool_id: str,
    cognito_user_id: str,
) -> Optional[Dict[str, Any]]:
    """Find Cognito user by sub UUID."""
    response = cognito_client.list_users(
        UserPoolId=user_pool_id,
        Filter=f'sub = "{cognito_user_id}"',
        Limit=1,
    )
    users = response.get("Users", [])
    if not users:
        return None
    return users[0]


def get_user_groups(cognito_client, user_pool_id: str, username: str) -> List[str]:
    """Return group names for a Cognito user."""
    groups: List[str] = []
    token = None
    while True:
        params = {
            "UserPoolId": user_pool_id,
            "Username": username,
            "Limit": 60,
        }
        if token:
            params["NextToken"] = token
        response = cognito_client.admin_list_groups_for_user(**params)
        groups.extend([group["GroupName"] for group in response.get("Groups", [])])
        token = response.get("NextToken")
        if not token:
            break
    return sorted(groups)


def to_managed_user(cognito_user: Dict[str, Any], roles: List[str]) -> Dict[str, Any]:
    """Map Cognito user payload to ManagedUser response model."""
    attrs = {
        attr.get("Name"): attr.get("Value")
        for attr in cognito_user.get("Attributes", [])
    }
    return {
        "cognitoUserId": attrs.get("sub"),
        "username": cognito_user.get("Username"),
        "email": attrs.get("email"),
        "phoneNumber": attrs.get("phone_number"),
        "name": attrs.get("name"),
        "enabled": bool(cognito_user.get("Enabled", False)),
        "status": cognito_user.get("UserStatus"),
        "roles": roles,
    }


def generate_username() -> str:
    """Generate an internal username for onboarding."""
    return f"usr-{uuid.uuid4().hex[:24]}"


def actor_claims(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract actor claims used in audit log entries."""
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    return {
        "sub": claims.get("sub"),
        "email": claims.get("email"),
        "username": claims.get("cognito:username") or claims.get("username"),
    }


def audit_log(
    *,
    action: str,
    result: str,
    event: Dict[str, Any],
    target_cognito_user_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit structured audit log event for write operations."""
    payload = {
        "audit": True,
        "action": action,
        "result": result,
        "actor": actor_claims(event),
        "targetCognitoUserId": target_cognito_user_id,
    }
    if extra:
        payload.update(extra)
    logger.info("AUDIT %s", json.dumps(payload, default=str))


def map_cognito_error(exc: ClientError) -> Tuple[str, str, int]:
    """Map Cognito ClientError to API error contract."""
    error = exc.response.get("Error", {})
    code = error.get("Code", "UnknownError")
    message = error.get("Message", "Unexpected Cognito error")

    if code in ("UserNotFoundException",):
        return "USER_NOT_FOUND", "Target user not found", 404
    if code in ("UsernameExistsException", "AliasExistsException"):
        return "USER_ALREADY_EXISTS", "A user with this email already exists", 409
    if code in ("TooManyRequestsException",):
        return "RATE_LIMITED", "Request throttled", 429
    if code in ("InvalidParameterException", "InvalidPasswordException"):
        return "VALIDATION_ERROR", message, 400
    return "INTERNAL_ERROR", "Unhandled server error", 500


def cognito_error_response(exc: ClientError):
    """Build standardized error response from Cognito ClientError."""
    error_code, message, status_code = map_cognito_error(exc)
    return error_response(error_code=error_code, message=message, status_code=status_code)
