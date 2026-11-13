"""
Self-service permission resolution for riders.

Single place that turns the stored tour, ride, stage, and event settings into
the effective permissions used by the Rider API self-service endpoints and
returned (read-only) on ride and event responses.

Ride check-ins
- Stage check-in allowed: stage ``selfCheckInAllowed`` if set, else ride
  ``selfCheckInAllowed`` if set, else the stage-type default
  (START = true, FINISH = true, PIT_STOP = false).
- Not Riding allowed: the START stage's ``selfNotRidingAllowed``, default false.
- Quit Riding allowed: ride ``selfQuitRidingAllowed`` if set, else tour
  ``selfQuitRidingAllowed``, default false.

Event activities
- Self-service allowed for one activity in one occurrence: occurrence activity
  override -> occurrence -> activity -> event -> false. The first value that is
  set (true or false) wins.

Settings that are absent (or stored as null) fall through to the next level, so
rides and events created before these settings existed resolve to the defaults.
"""

from typing import Any, Dict, List, Optional

STAGE_TYPE_SELF_CHECKIN_DEFAULTS = {
    "START": True,
    "FINISH": True,
    "PIT_STOP": False,
}


def _explicit_bool(value: Any) -> Optional[bool]:
    """Return the value when it is a stored boolean, else None (not set)."""
    return value if isinstance(value, bool) else None


def _first_set(*values: Any) -> Optional[bool]:
    for value in values:
        explicit = _explicit_bool(value)
        if explicit is not None:
            return explicit
    return None


def stage_check_in_allowed(ride: Dict[str, Any], stage: Dict[str, Any]) -> bool:
    """Resolve whether a rider may self check in at a stage."""
    resolved = _first_set(
        stage.get("selfCheckInAllowed"), ride.get("selfCheckInAllowed")
    )
    if resolved is not None:
        return resolved
    return STAGE_TYPE_SELF_CHECKIN_DEFAULTS.get(stage.get("type"), False)


def not_riding_allowed(ride: Dict[str, Any]) -> bool:
    """Resolve whether a rider may self-report Not Riding for a ride."""
    for stage in ride.get("stages") or []:
        if stage.get("type") == "START":
            return _explicit_bool(stage.get("selfNotRidingAllowed")) is True
    return False


def quit_riding_allowed(ride: Dict[str, Any], tour: Optional[Dict[str, Any]]) -> bool:
    """Resolve whether a rider may self-report Quit Riding for a ride."""
    resolved = _first_set(
        ride.get("selfQuitRidingAllowed"), (tour or {}).get("selfQuitRidingAllowed")
    )
    return resolved is True


def build_ride_self_service(
    ride: Dict[str, Any], tour: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Build the calculated ``selfService`` object returned on ride responses."""
    stages: List[Dict[str, Any]] = []
    for stage in sorted(
        ride.get("stages") or [], key=lambda item: int(item.get("stageNumber", 0))
    ):
        stages.append(
            {
                "stageNumber": int(stage.get("stageNumber", 0)),
                "stageId": stage.get("stageId"),
                "stageType": stage.get("type"),
                "checkInAllowed": stage_check_in_allowed(ride, stage),
            }
        )
    return {
        "quitRidingAllowed": quit_riding_allowed(ride, tour),
        "notRidingAllowed": not_riding_allowed(ride),
        "stages": stages,
    }


def activity_self_service_allowed(
    event_definition: Dict[str, Any],
    activity: Dict[str, Any],
    occurrence: Dict[str, Any],
    override: Optional[Dict[str, Any]] = None,
) -> bool:
    """Resolve rider self-service for one activity in one occurrence."""
    resolved = _first_set(
        (override or {}).get("selfServiceAllowed"),
        occurrence.get("selfServiceAllowed"),
        activity.get("selfServiceAllowed"),
        event_definition.get("selfServiceAllowed"),
    )
    return resolved is True


def apply_tour_defaults(tour: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the tour with ``selfQuitRidingAllowed`` always present (missing -> false)."""
    if tour is None:
        return None
    result = dict(tour)
    result["selfQuitRidingAllowed"] = (
        _explicit_bool(tour.get("selfQuitRidingAllowed")) is True
    )
    return result
