"""Effective rider self-check-in permissions for a ride."""

from typing import Any, Dict, Optional


def _stage_type(stage: Dict[str, Any]) -> str:
    return stage.get("type", "")


def effective_self_checkin_allowed(
    tour: Dict[str, Any],
    ride: Dict[str, Any],
    stage: Optional[Dict[str, Any]] = None,
) -> bool:
    """Resolve stage permission using stage -> ride -> safe defaults."""
    if stage and stage.get("selfCheckInAllowed") is not None:
        return bool(stage["selfCheckInAllowed"])
    if ride.get("selfCheckInAllowed") is not None:
        return bool(ride["selfCheckInAllowed"])
    if stage and _stage_type(stage) in {"START", "FINISH"}:
        return True
    return False


def effective_quit_riding_allowed(tour: Dict[str, Any], ride: Dict[str, Any]) -> bool:
    """Resolve ride quit-riding permission, with ride taking precedence."""
    if ride.get("selfQuitRidingAllowed") is not None:
        return bool(ride["selfQuitRidingAllowed"])
    return bool(tour.get("selfQuitRidingAllowed", False))


def effective_not_riding_allowed(stage: Dict[str, Any]) -> bool:
    """Resolve the START-only Not Riding permission."""
    return _stage_type(stage) == "START" and bool(stage.get("selfNotRidingAllowed", False))


def self_service_summary(
    tour: Dict[str, Any],
    ride: Dict[str, Any],
) -> Dict[str, Any]:
    """Return computed permissions suitable for a ride GET response."""
    stages = ride.get("stages", []) or []
    return {
        "quitRidingAllowed": effective_quit_riding_allowed(tour, ride),
        "stages": {
            str(stage.get("stageNumber")): {
                "checkInAllowed": effective_self_checkin_allowed(tour, ride, stage),
                "notRidingAllowed": effective_not_riding_allowed(stage),
            }
            for stage in stages
        },
    }
