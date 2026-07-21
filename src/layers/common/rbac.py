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

    Permission        | ADMINISTRATOR | SUPER_USER | PS_<n>_USER | HOTEL_STAFF | GUEST | RIDER
    ------------------|:-------------:|:----------:|:-----------:|:-----------:|:-----:|:-----:
    READ              |      ✅       |     ✅     |      ✅      |     ✅      |   ✅  |   ✅
    CHECKIN           |      ✅       |     ✅     |      ✅      |     ✅      |   ❌  |   ❌
    CHECKIN_MANUAL    |      ✅       |     ✅     |      ❌      |     ❌      |   ❌  |   ❌
    RIDE_MANAGE       |      ✅       |     ❌     |      ❌      |     ❌      |   ❌  |   ❌
    PIT_STOP_MANAGE   |      ✅       |     ✅     |      ✅      |     ❌      |   ❌  |   ❌
    TOUR_MANAGE       |      ✅       |     ❌     |      ❌      |     ❌      |   ❌  |   ❌
    USER_LIST         |      ✅       |     ✅     |      ❌      |     ❌      |   ❌  |   ❌
    DASHBOARD         |      ✅       |     ✅     |      ✅      |     ❌      |   ✅  |   ❌
"""

import json
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from logger import get_logger
from response import forbidden_response


logger = get_logger(__name__)


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

    PIT_STOP_MANAGE = "PIT_STOP_MANAGE"
    """Open or close a PIT_STOP stage for a ride."""

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
        Permission.PIT_STOP_MANAGE,
        Permission.TOUR_MANAGE,
        Permission.USER_LIST,
        Permission.DASHBOARD,
        Permission.NOTIFICATION_MANAGE,
    ],
    "SUPER_USER": [
        Permission.READ,
        Permission.CHECKIN,
        Permission.CHECKIN_MANUAL,
        Permission.PIT_STOP_MANAGE,
        Permission.USER_LIST,
        Permission.DASHBOARD,
        Permission.NOTIFICATION_MANAGE,
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

PIT_STOP_GROUP_PATTERN = re.compile(r'^PS_(\d+)_USER$')
PIT_STOP_GROUP_PERMISSIONS = {
    Permission.READ,
    Permission.CHECKIN,
    Permission.PIT_STOP_MANAGE,
    Permission.DASHBOARD,
}

ROLE_PRIORITY_ORDER = (
    "ADMINISTRATOR",
    "SUPER_USER",
)

LOW_PRIORITY_STANDARD_GROUPS = (
    "HOTEL_STAFF",
    "GUEST",
)


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

    # Prefer Cognito groups, but also tolerate common custom role claims.
    # Some clients/proxies serialize multi-value claims in different formats.
    claim_candidates = [
        jwt_claims.get('cognito:groups'),
        jwt_claims.get('groups'),
        jwt_claims.get('custom:roles'),
        jwt_claims.get('roles'),
        jwt_claims.get('role'),
    ]

    parsed_groups: List[str] = []
    for candidate in claim_candidates:
        parsed_groups.extend(_parse_group_claim(candidate))

    deduped_groups: List[str] = []
    seen = set()
    for group in parsed_groups:
        if group in seen:
            continue
        deduped_groups.append(group)
        seen.add(group)

    return deduped_groups


def _parse_group_claim(groups_raw: Any) -> List[str]:
    """Parse a role/group claim in list, JSON-list, or delimited string forms."""
    if not groups_raw:
        return []

    if isinstance(groups_raw, list):
        return [str(group).strip() for group in groups_raw if str(group).strip()]

    if not isinstance(groups_raw, str):
        return []

    raw = groups_raw.strip()
    if not raw:
        return []

    # Handles JSON arrays like ["PS_1_USER", "PS_3_USER"]
    if raw.startswith('[') and raw.endswith(']'):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(group).strip() for group in parsed if str(group).strip()]
        except json.JSONDecodeError:
            raw = raw[1:-1]

    # Tolerate both comma and whitespace-delimited values.
    groups = [
        token.strip().strip("'\"")
        for token in re.split(r'[\s,]+', raw)
    ]
    return [group for group in groups if group]


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


def is_pit_stop_group(group_name: str) -> bool:
    """Return True when the group name follows the dynamic pit-stop pattern."""
    return bool(PIT_STOP_GROUP_PATTERN.fullmatch(group_name or ''))


def get_pit_stop_stage_number(group_name: str) -> Optional[int]:
    """Extract the stage number from a pit-stop group like PS_3_USER."""
    match = PIT_STOP_GROUP_PATTERN.fullmatch(group_name or '')
    if not match:
        return None
    return int(match.group(1))


def get_user_pit_stop_stage_numbers(event: Dict[str, Any]) -> Set[int]:
    """Return all pit-stop stage numbers assigned to the caller via Cognito groups."""
    stage_numbers: Set[int] = set()
    for group in get_user_groups(event):
        stage_number = get_pit_stop_stage_number(group)
        if stage_number is not None:
            stage_numbers.add(stage_number)
    return stage_numbers


def get_effective_group(user_groups: List[str]) -> Optional[str]:
    """
    Resolve one effective group for permission decisions.

    Priority:
    1. ADMINISTRATOR
    2. SUPER_USER
    3. First pit-stop role in request order (PS_<n>_USER)
    4. HOTEL_STAFF
    5. GUEST

    If none of the above exists, return None so legacy union mapping can apply.
    """
    for priority_group in ROLE_PRIORITY_ORDER:
        if priority_group in user_groups:
            return priority_group

    for group in user_groups:
        if is_pit_stop_group(group):
            return group

    for low_priority_group in LOW_PRIORITY_STANDARD_GROUPS:
        if low_priority_group in user_groups:
            return low_priority_group

    return None


def has_non_pit_stop_checkin_access(event: Dict[str, Any]) -> bool:
    """Return True when any non pit-stop group grants generic CHECKIN access."""
    for group in get_user_groups(event):
        if is_pit_stop_group(group):
            continue
        if Permission.CHECKIN in GROUP_PERMISSIONS.get(group, []):
            return True
    return False


# ============================================================================
# PERMISSION RESOLUTION
# ============================================================================

def get_user_permissions(event: Dict[str, Any]) -> Set[Permission]:
    """
    Resolve API permissions for the current caller.

    Multi-role resolution uses one effective group with priority:
    ADMINISTRATOR > SUPER_USER > first PS_<n>_USER in claim order >
    HOTEL_STAFF > GUEST.

    If none of these priority roles exists, non-priority groups are resolved
    with legacy union semantics (mapped groups are combined; unknown groups are
    ignored). This keeps behavior deterministic for admin/super/pit-stop users
    while preserving compatibility for other role combinations.

    Args:
        event: Lambda event dict from API Gateway HTTP API.

    Returns:
        Set of Permission values granted to the caller.
    """
    user_groups = get_user_groups(event)
    permissions: Set[Permission] = set()

    effective_group = get_effective_group(user_groups)
    if effective_group:
        if is_pit_stop_group(effective_group):
            permissions.update(PIT_STOP_GROUP_PERMISSIONS)
        else:
            permissions.update(GROUP_PERMISSIONS.get(effective_group, []))
        return permissions

    # Legacy fallback for non-priority groups to preserve existing behavior.
    for group in user_groups:
        if is_pit_stop_group(group):
            permissions.update(PIT_STOP_GROUP_PERMISSIONS)
            continue
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
    route = event.get('rawPath') or event.get('routeKey') or 'unknown-route'
    user_groups = get_user_groups(event)
    user_permissions = get_user_permissions(event)

    logger.info(
        "RBAC access check: route=%s groups=%s permissions=%s required=%s",
        route,
        user_groups,
        [granted.value for granted in user_permissions],
        permission.value,
    )

    if permission not in user_permissions:
        deny_message = message or (
            f"Access denied. Required permission: {permission.value}"
        )
        logger.warning(
            "RBAC access denied: route=%s groups=%s permissions=%s required=%s",
            route,
            user_groups,
            [granted.value for granted in user_permissions],
            permission.value,
        )
        return forbidden_response(deny_message)

    return None


def require_pit_stop_stage_access(
    event: Dict[str, Any],
    stage_number: int,
    message: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Enforce stage-bound access for pit-stop-only users."""
    assigned_stage_numbers = get_user_pit_stop_stage_numbers(event)
    if not assigned_stage_numbers:
        return None

    if has_non_pit_stop_checkin_access(event):
        return None

    if stage_number in assigned_stage_numbers:
        return None

    deny_message = message or (
        f"Pit stop user is not authorized for stage {stage_number}. "
        f"Assigned stages: {sorted(assigned_stage_numbers)}"
    )
    return forbidden_response(deny_message)
