"""
Rider self check-in rules (Rider API).

Implements the ordered checks for ``POST .../rides/{rideId}/self-checkins`` and
its cancel endpoint. Storage and the existing check-in rules are delegated to
``checkin_service`` so self check-ins are identical to Mgmt check-ins apart from
``method = SELF_SERVICE`` and ``checkedInBy`` = rider ``profileId``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from checkin_service import list_rider_ride_checkins, read_value
from dynamodb_utils import get_item, get_tour_item
from models import (
    CheckInStatus,
    PitStopStatus,
    RideStatus,
    StageType,
    TourStatus,
    utc_today_iso,
)
from response import error_response
from rider_identity import resolve_active_caller_tour_rider
from self_service_policy import (
    not_riding_allowed,
    quit_riding_allowed,
    stage_check_in_allowed,
)

SELF_CHECKIN_ACTIVE_RIDE_STATUSES = {RideStatus.OPEN.value, RideStatus.STARTED.value}


def _error(code: str, message: str, status: int) -> Dict[str, Any]:
    return error_response(error_code=code, message=message, status_code=status)


def load_self_checkin_context(
    event: Dict[str, Any],
    tour_id: str,
    ride_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Run checks 1-4: tour ACTIVE, caller on tour, ride is today's, ride OPEN/STARTED.

    Returns ``({tour, identity, ride}, None)`` or ``(None, error_response)``.
    """
    tour = get_item(table_name_env="TOUR_MASTER_TABLE", key={"tourId": tour_id})
    if not tour or tour.get("status") != TourStatus.ACTIVE.value:
        return None, _error("TOUR_NOT_ACTIVE", f"Tour {tour_id} is not ACTIVE", 409)

    identity, error = resolve_active_caller_tour_rider(event, tour_id)
    if error:
        return None, error

    ride = get_tour_item(table_type="Ride", tour_id=tour_id, key={"rideId": ride_id})
    if not ride:
        return None, _error("RIDE_NOT_FOUND", f"Ride '{ride_id}' not found", 404)

    today = utc_today_iso()
    if ride.get("date") != today:
        return None, _error(
            "RIDE_NOT_TODAY",
            f"Ride {ride_id} is scheduled for {ride.get('date')}; self check-in is only available on the ride day ({today} UTC)",
            409,
        )

    if ride.get("status") not in SELF_CHECKIN_ACTIVE_RIDE_STATUSES:
        return None, _error(
            "RIDE_NOT_ACTIVE",
            f"Ride {ride_id} is {ride.get('status')}; self check-in needs the ride to be OPEN or STARTED",
            409,
        )

    return {"tour": tour, "identity": identity, "ride": ride}, None


def find_stage(ride: Dict[str, Any], stage_number: int) -> Optional[Dict[str, Any]]:
    for stage in ride.get("stages") or []:
        try:
            if int(stage.get("stageNumber")) == stage_number:
                return stage
        except (TypeError, ValueError):
            continue
    return None


def _is_finish_checkin(ride: Dict[str, Any], checkin: Dict[str, Any]) -> bool:
    if read_value(checkin, "isNotRiding", "is_not_riding", False) or read_value(
        checkin, "isQuitRiding", "is_quit_riding", False
    ):
        return False
    stage_number = read_value(checkin, "stageNumber", "stage_number")
    if stage_number is None:
        return False
    stage = find_stage(ride, int(stage_number))
    return bool(stage and stage.get("type") == StageType.FINISH.value)


def check_self_checkin_request(
    context: Dict[str, Any],
    tour_id: str,
    stage_number: Optional[int],
    is_not_riding: bool,
    is_quit_riding: bool,
) -> Optional[Dict[str, Any]]:
    """Run checks 5-8 for a self check-in request. Returns an error response or None."""
    ride = context["ride"]
    tour = context["tour"]
    rider_id = context["identity"]["riderId"]
    ride_id = ride.get("rideId")

    active_checkins: List[Dict[str, Any]] = list_rider_ride_checkins(
        tour_id, ride_id, rider_id
    )

    # 5. No self check-in of any kind after Quit Riding (not cancelled)
    if any(
        read_value(c, "isQuitRiding", "is_quit_riding", False) for c in active_checkins
    ):
        return _error(
            "RIDER_ALREADY_QUIT",
            f"Rider {rider_id} has quit riding on ride {ride_id}",
            409,
        )

    if stage_number is not None:
        # 6a. Stage exists and its calculated self check-in permission is true
        stage = find_stage(ride, stage_number)
        if not stage:
            return _error(
                "STAGE_NOT_FOUND",
                f"Stage {stage_number} not found on ride {ride_id}",
                404,
            )
        if not stage_check_in_allowed(ride, stage):
            return _error(
                "SELF_CHECKIN_NOT_ALLOWED",
                f"Self check-in is not allowed at stage {stage_number} ({stage.get('type')})",
                403,
            )
        # 6b. Pit stops must be OPEN
        if (
            stage.get("type") == StageType.PIT_STOP.value
            and stage.get("pitStopStatus") != PitStopStatus.OPEN.value
        ):
            return _error(
                "PIT_STOP_NOT_OPEN",
                f"Pit stop at stage {stage_number} is not open",
                409,
            )
        return None

    if is_not_riding:
        # 7. Not Riding: allowed by configuration and only while the ride is OPEN
        if not not_riding_allowed(ride):
            return _error(
                "SELF_CHECKIN_NOT_ALLOWED",
                "Self-reporting Not Riding is not allowed for this ride",
                403,
            )
        if ride.get("status") != RideStatus.OPEN.value:
            return _error(
                "NOT_RIDING_NOT_AVAILABLE",
                f"Not Riding can only be self-reported while the ride is OPEN (ride is {ride.get('status')})",
                409,
            )
        return None

    if is_quit_riding:
        # 8. Quit Riding: allowed by configuration, ride STARTED, and no FINISH check-in yet
        if not quit_riding_allowed(ride, tour):
            return _error(
                "SELF_CHECKIN_NOT_ALLOWED",
                "Self-reporting Quit Riding is not allowed for this ride",
                403,
            )
        if ride.get("status") != RideStatus.STARTED.value:
            return _error(
                "QUIT_RIDING_NOT_AVAILABLE",
                f"Quit Riding can only be self-reported while the ride is STARTED (ride is {ride.get('status')})",
                409,
            )
        if any(_is_finish_checkin(ride, c) for c in active_checkins):
            return _error(
                "QUIT_RIDING_NOT_AVAILABLE",
                "Quit Riding is not available after a FINISH check-in",
                409,
            )
    return None


def derive_checkin_status(checkin: Dict[str, Any]) -> str:
    """Return the stored status, or derive it from the flags for older items."""
    if checkin.get("status"):
        return checkin["status"]
    if read_value(checkin, "isNotRiding", "is_not_riding", False):
        return CheckInStatus.NOT_RIDING.value
    if read_value(checkin, "isQuitRiding", "is_quit_riding", False):
        return CheckInStatus.QUIT_RIDING.value
    if read_value(checkin, "isFloat", "is_float", False):
        return CheckInStatus.FLOAT.value
    return CheckInStatus.CHECKED_IN.value


def check_self_cancel_allowed(
    context: Dict[str, Any], checkin: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Ownership, Quit Riding safety rule and calculated permission for a self cancel."""
    rider_id = context["identity"]["riderId"]
    ride = context["ride"]

    if checkin.get("riderId") != rider_id:
        return _error("NOT_OWN_CHECKIN", "You can only cancel your own check-ins", 403)

    # Safety rule: organisers assess the rider before they resume, so only Mgmt users
    # may cancel a Quit Riding check-in (existing Mgmt cancel endpoint).
    if read_value(checkin, "isQuitRiding", "is_quit_riding", False):
        return _error(
            "QUIT_RIDING_CANCEL_NOT_ALLOWED",
            "A Quit Riding check-in can only be cancelled by the organisers",
            403,
        )

    if derive_checkin_status(checkin) == CheckInStatus.CANCELLED.value or checkin.get(
        "cancelledAt"
    ):
        return _error(
            "CHECKIN_ALREADY_CANCELLED", "This check-in is already cancelled", 409
        )

    if read_value(checkin, "isNotRiding", "is_not_riding", False):
        if not not_riding_allowed(ride):
            return _error(
                "SELF_CHECKIN_NOT_ALLOWED",
                "Self-service Not Riding is not allowed for this ride",
                403,
            )
        return None

    stage_number = read_value(checkin, "stageNumber", "stage_number")
    stage = find_stage(ride, int(stage_number)) if stage_number is not None else None
    if not stage or not stage_check_in_allowed(ride, stage):
        return _error(
            "SELF_CHECKIN_NOT_ALLOWED",
            f"Self check-in is not allowed at stage {stage_number}",
            403,
        )
    return None
