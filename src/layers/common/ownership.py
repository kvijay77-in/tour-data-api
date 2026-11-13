"""Rider profile ownership enforcement helpers."""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

from dynamodb_utils import get_item
from response import error_response

RIDER_LINK_TABLE_ENV = "RIDER_COGNITO_USER_TABLE"
logger = logging.getLogger(__name__)


def get_jwt_sub(event: Dict[str, Any]) -> Optional[str]:
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
        .get("sub")
    )


def is_rider_api_request(event: Dict[str, Any]) -> bool:
    configured_rider_api_id = os.environ.get("RIDER_API_ID", "").strip()
    api_id = (event.get("requestContext", {}) or {}).get("apiId", "")
    if configured_rider_api_id and api_id:
        return api_id == configured_rider_api_id

    route_key = (event.get("routeKey") or "").upper()
    raw_path = (event.get("rawPath") or "").lower()

    is_profile_route = (
        route_key.startswith(
            (
                "GET /V1/RIDERS/",
                "POST /V1/RIDERS/",
                "PUT /V1/RIDERS/",
                "DELETE /V1/RIDERS/",
            )
        )
        or raw_path.startswith("/v1/riders/")
        or raw_path.startswith("/v1/profile/")
    )

    if api_id and not configured_rider_api_id:
        if is_profile_route:
            logger.error(
                "RIDER_API_ID is not configured; applying fail-closed ownership checks for route %s",
                raw_path or route_key,
            )
            return True
        return False

    if not api_id:
        # Local/unit-test fallback is opt-in to avoid breaking legacy tests.
        if os.environ.get("FORCE_RIDER_API_OWNERSHIP", "").lower() != "true":
            return False

    return is_profile_route


def resolve_profile_id_for_sub(cognito_sub: str) -> Optional[str]:
    if not cognito_sub:
        return None
    link = get_item(
        table_name_env=RIDER_LINK_TABLE_ENV, key={"cognitoUserName": cognito_sub}
    )
    if not link:
        return None
    return link.get("profileId")


def require_own_profile(
    event: Dict[str, Any], profile_id: str
) -> Optional[Dict[str, Any]]:
    """Enforce that Rider API callers can access only their own profile."""
    if not is_rider_api_request(event):
        return None

    sub = get_jwt_sub(event)
    linked_profile_id = resolve_profile_id_for_sub(sub or "")
    if linked_profile_id and linked_profile_id == profile_id:
        return None

    return error_response(
        error_code="PROFILE_ACCESS_DENIED",
        message="You can access only your own rider profile resources",
        status_code=403,
    )


def require_own_link_subject(
    event: Dict[str, Any], cognito_user_name: str
) -> Optional[Dict[str, Any]]:
    if not is_rider_api_request(event):
        return None
    sub = get_jwt_sub(event)
    if sub and sub == cognito_user_name:
        return None
    return error_response(
        error_code="PROFILE_ACCESS_DENIED",
        message="Link route subject does not match caller identity",
        status_code=403,
    )
