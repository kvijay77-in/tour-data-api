"""
Server-side Role-Based Access Control (RBAC) utilities

Design principle: Lambda functions are decoupled from Cognito group names.
They check API-level *permissions* (what action is being performed) rather
than group names (who the caller is).  The GROUP_PERMISSIONS mapping is the
single place that connects Cognito groups to API permissions.

Benefits of this approach:
- Cognito groups (frontend/org concept) can be renamed or restructured
  without touching Lambda code.
- New groups can be added and mapped to existing permissions in one place.
- Each Lambda function expresses its access requirement in terms of API
  function (e.g. Permission.TOUR_MANAGE), not user identity.

Flow:
    1. API Gateway validates the JWT and forwards claims to Lambda.
    2. get_user_groups()   – reads cognito:groups from JWT claims.
    3. get_user_permissions() – maps groups → Permission set via GROUP_PERMISSIONS.
    4. require_permission() – returns 403 if required permission is absent.

Permission → Group mapping (current default):

  Permission        | ADMINISTRATOR | SUPER_USER | PIT_STOP_CREW | HOTEL_STAFF | GUEST | RIDER
  ------------------|:-------------:|:----------:|:-------------:|:-----------:|:-----:|:-----:
  READ              |      ✅       |     ✅     |      ✅       |     ✅      |   ✅  |   ✅
  CHECKIN           |      ✅       |     ✅     |      ✅       |     ✅      |   ❌  |   ❌
  CHECKIN_MANUAL    |      ✅       |     ✅     |      ❌       |     ❌      |   ❌  |   ❌
  RIDE_MANAGE       |      ✅       |     ❌     |      ❌       |     ❌      |   ❌  |   ❌
  TOUR_MANAGE       |      ✅       |     ❌     |      ❌       |     ❌      |   ❌  |   ❌
  USER_LIST         |      ✅       |     ✅     |      ❌       |     ❌      |   ❌  |   ❌
  DASHBOARD         |      ✅       |     ✅     |      ✅       |     ❌      |   ✅  |   ❌
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Set

from response import forbidden_response


# ============================================================================
# API-LEVEL PERMISSIONS
# These describe what an API endpoint/action requires — they are independent
# of any frontend role or Cognito group name.
# ============================================================================

class Permission(str, Enum):
    """Functional API permissions — what each Lambda endpoint requires."""

    READ = "READ"
    """Read access: GET tours, riders, rides, check-ins (all endpoints)."""

    CHECKIN = "CHECKIN"
    """Create a check-in via QR scan or fallback method."""

    CHECKIN_MANUAL = "CHECKIN_MANUAL"
    """Create a check-in via manual entry (elevated privilege)."""

    RIDE_MANAGE = "RIDE_MANAGE"
    """Create, update, or close a ride."""

    TOUR_MANAGE = "TOUR_MANAGE"
    """Create or archive a tour."""

    USER_LIST = "USER_LIST"
    """List users assigned to a tour."""

    DASHBOARD = "DASHBOARD"
    """Access the ride dashboard with aggregated check-in data."""

    NOTIFICATION_MANAGE = "NOTIFICATION_MANAGE"
    """Create notifications for tour riders (admin/organizer action)."""


# ============================================================================
# GROUP → PERMISSION MAPPING
# This is the single configuration point that connects Cognito group names
# to API permissions.  To support a new group or change what an existing
# group can do, update only this dict — no Lambda code changes required.
# ============================================================================

GROUP_PERMISSIONS: Dict[str, List[Permission]] = {
    "ADMINISTRATOR": [
        Permission.READ,
        Permission.CHECKIN,
        Permission.CHECKIN_MANUAL,
        Permission.RIDE_MANAGE,
        Permission.TOUR_MANAGE,
        Permission.USER_LIST,
        Permission.DASHBOARD,
        Permission.NOTIFICATION_MANAGE,
    ],
    "SUPER_USER": [
        Permission.READ,
        Permission.CHECKIN,
        Permission.CHECKIN_MANUAL,
        Permission.USER_LIST,
        Permission.DASHBOARD,
        Permission.NOTIFICATION_MANAGE,
    ],
    "PIT_STOP_CREW": [
        Permission.READ,
        Permission.CHECKIN,
        Permission.DASHBOARD,
    ],
    "HOTEL_STAFF": [
        Permission.READ,
        Permission.CHECKIN,
    ],
    "GUEST": [
        Permission.READ,
        Permission.DASHBOARD,
    ],
    "RIDER": [
        Permission.READ,
    ],
}


# ============================================================================
# HELPERS — group extraction
# ============================================================================

def get_user_groups(event: Dict[str, Any]) -> List[str]:
    """
    Extract Cognito group membership from API Gateway JWT claims.

    API Gateway HTTP API serialises the `cognito:groups` array claim as a
    comma-separated string when forwarding claims to Lambda.

    Args:
        event: Lambda event dict from API Gateway HTTP API.

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
        required_groups: Groups to check against.

    Returns:
        True when there is a non-empty intersection.
    """
    return bool(set(user_groups) & set(required_groups))


# ============================================================================
# PERMISSION RESOLUTION
# ============================================================================

def get_user_permissions(event: Dict[str, Any]) -> Set[Permission]:
    """
    Resolve the full set of API permissions for the current caller.

    Looks up each Cognito group the caller belongs to in GROUP_PERMISSIONS
    and returns the union of all granted permissions.  Groups not present in
    GROUP_PERMISSIONS are silently ignored, making it safe to add new Cognito
    groups (e.g. for other applications) without breaking existing mappings.

    Args:
        event: Lambda event dict from API Gateway HTTP API.

    Returns:
        Set of Permission values granted to the caller.
    """
    user_groups = get_user_groups(event)
    permissions: Set[Permission] = set()
    for group in user_groups:
        permissions.update(GROUP_PERMISSIONS.get(group, []))
    return permissions


def require_permission(
    event: Dict[str, Any],
    permission: Permission,
    message: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Enforce permission-based access control.

    Call this at the top of a Lambda handler before any business logic.
    If the caller does not hold *permission*, a 403 Forbidden response dict
    is returned immediately and the caller must return it to API Gateway.
    If access is granted, None is returned so the handler can continue.

    Lambda functions use Permission values (API-centric) rather than Cognito
    group names (identity-centric), keeping the two concerns decoupled.

    Args:
        event: Lambda event dict from API Gateway HTTP API.
        permission: The Permission required to call this endpoint.
        message: Optional custom message for the 403 response.

    Returns:
        A 403 response dict if access is denied, otherwise None.

    Usage::

        deny = require_permission(event, Permission.TOUR_MANAGE)
        if deny:
            return deny
    """
    user_permissions = get_user_permissions(event)

    if permission not in user_permissions:
        deny_message = message or (
            f"Access denied. Required permission: {permission.value}"
        )
        return forbidden_response(deny_message)

    return None
