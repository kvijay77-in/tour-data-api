"""
Server-side Role-Based Access Control (RBAC) utilities

Extracts Cognito group membership from API Gateway JWT claims and provides
helper functions for enforcing group-based authorization in Lambda functions.

Cognito groups present in the JWT token as the `cognito:groups` claim are
forwarded by API Gateway HTTP API as a comma-separated string in
requestContext.authorizer.jwt.claims.

Authorization matrix:
  Endpoint                   | ADMINISTRATOR | SUPER_USER | PIT_STOP_CREW | HOTEL_STAFF | GUEST
  ---------------------------|:-------------:|:----------:|:-------------:|:-----------:|:-----:
  GET tours/riders/rides      |      ✅       |     ✅     |      ✅       |     ✅      |   ✅
  GET dashboard               |      ✅       |     ✅     |      ✅       |     ❌      |   ✅
  POST check-in (any method)  |      ✅       |     ✅     |      ✅       |     ✅      |   ❌
  POST check-in (MANUAL)      |      ✅       |     ✅     |      ❌       |     ❌      |   ❌
  POST tours (create)         |      ✅       |     ❌     |      ❌       |     ❌      |   ❌
  POST archive tour           |      ✅       |     ❌     |      ❌       |     ❌      |   ❌
  POST/PUT rides              |      ✅       |     ❌     |      ❌       |     ❌      |   ❌
  POST close ride             |      ✅       |     ❌     |      ❌       |     ❌      |   ❌
  GET tour users              |      ✅       |     ✅     |      ❌       |     ❌      |   ❌
"""

from typing import Any, Dict, List, Optional

from models import UserRole
from response import forbidden_response


# Convenience group constants (use the Enum values)
ADMINISTRATOR = UserRole.ADMINISTRATOR.value
SUPER_USER = UserRole.SUPER_USER.value
PIT_STOP_CREW = UserRole.PIT_STOP_CREW.value
HOTEL_STAFF = UserRole.HOTEL_STAFF.value
GUEST = UserRole.GUEST.value


def get_user_groups(event: Dict[str, Any]) -> List[str]:
    """
    Extract Cognito group membership from API Gateway JWT claims.

    API Gateway HTTP API serialises the `cognito:groups` array claim as a
    comma-separated string when forwarding claims to Lambda.

    Args:
        event: Lambda event dict from API Gateway HTTP API

    Returns:
        List of group names the caller belongs to.  Empty list when the
        claim is absent or the request context is missing.
    """
    jwt_claims = (
        event
        .get('requestContext', {})
        .get('authorizer', {})
        .get('jwt', {})
        .get('claims', {})
    )

    groups_raw = jwt_claims.get('cognito:groups', '')

    # Already a list (used in unit tests / local SAM invocations)
    if isinstance(groups_raw, list):
        return [g for g in groups_raw if g]

    if not groups_raw:
        return []

    # API Gateway serialises Cognito array claims as comma-separated strings
    return [g.strip() for g in groups_raw.split(',') if g.strip()]


def has_any_group(user_groups: List[str], required_groups: List[str]) -> bool:
    """
    Return True if the user belongs to at least one of the required groups.

    Args:
        user_groups: Groups the caller currently belongs to.
        required_groups: Groups that grant access to the resource.

    Returns:
        True when there is a non-empty intersection.
    """
    return bool(set(user_groups) & set(required_groups))


def require_groups(
    event: Dict[str, Any],
    allowed_groups: List[str],
    message: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Enforce group-based access control.

    Call this at the top of a Lambda handler before any business logic.
    If the caller does not belong to any of the *allowed_groups*, a 403
    Forbidden response dict is returned immediately.  The caller must
    return this response to API Gateway.  If access is granted, None is
    returned so the handler can continue.

    Args:
        event: Lambda event dict from API Gateway HTTP API.
        allowed_groups: Groups that are permitted to call this endpoint.
        message: Optional custom message for the 403 response.

    Returns:
        A 403 response dict if access is denied, otherwise None.

    Usage::

        deny = require_groups(event, [ADMINISTRATOR])
        if deny:
            return deny
    """
    user_groups = get_user_groups(event)

    if not has_any_group(user_groups, allowed_groups):
        deny_message = message or (
            f"Access denied. Required role(s): {', '.join(allowed_groups)}"
        )
        return forbidden_response(deny_message)

    return None
