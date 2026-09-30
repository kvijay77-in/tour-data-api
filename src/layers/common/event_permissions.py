"""Effective event activity permissions."""

from typing import Any, Dict


def effective_event_self_service_allowed(
    event: Dict[str, Any],
    occurrence: Dict[str, Any],
    activity: Dict[str, Any],
) -> bool:
    """Resolve event, activity, occurrence-wide, then activity-specific settings."""
    for override in occurrence.get("activityOverrides", []) or []:
        if override.get("activityId") == activity.get("activityId"):
            if override.get("selfServiceAllowed") is not None:
                return bool(override["selfServiceAllowed"])
    if occurrence.get("selfServiceAllowed") is not None:
        return bool(occurrence["selfServiceAllowed"])
    if activity.get("selfServiceAllowed") is not None:
        return bool(activity["selfServiceAllowed"])
    return bool(event.get("selfServiceAllowed", False))
