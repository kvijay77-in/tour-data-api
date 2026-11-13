"""Event occurrence registration storage helpers.

Registrations are stored in the tour-specific ``EventRegistration-{tourId}``
table (partition key ``occurrenceId``, sort key ``riderId``, GSI
``RiderIdIndex`` on ``riderId``).

When an event definition has ``registrationEnabled == false`` every rider on
the tour whose status is not ``EXITED`` / ``WITHDRAWN`` counts as registered
for every occurrence of that event.
"""

from typing import Any, Dict, List, Optional, Set

from botocore.exceptions import ClientError

from dynamodb_utils import (
    get_tour_item,
    get_tour_table,
    put_tour_item,
    query_tour_items,
)
from models import TourRiderStatus, utc_now_iso

REGISTRATION_TABLE_TYPE = "EventRegistration"
SOURCE_RIDER = "RIDER"
SOURCE_STAFF = "STAFF"

INACTIVE_RIDER_STATUSES = {
    TourRiderStatus.EXITED.value,
    TourRiderStatus.WITHDRAWN.value,
}


def is_active_rider(tour_rider: Optional[Dict[str, Any]]) -> bool:
    """A rider counts as on the tour unless their status is EXITED or WITHDRAWN."""
    if not tour_rider:
        return False
    return str(tour_rider.get("status") or "").upper() not in INACTIVE_RIDER_STATUSES


def _is_missing_table(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException"


def get_registration(
    tour_id: str, occurrence_id: str, rider_id: str
) -> Optional[Dict[str, Any]]:
    """Return the stored registration for a rider, or None."""
    try:
        return get_tour_item(
            REGISTRATION_TABLE_TYPE,
            tour_id,
            {"occurrenceId": occurrence_id, "riderId": rider_id},
        )
    except ClientError as exc:
        if _is_missing_table(exc):
            return None
        raise


def list_registrations(tour_id: str, occurrence_id: str) -> List[Dict[str, Any]]:
    """Return all stored registrations for an occurrence."""
    try:
        return query_tour_items(
            REGISTRATION_TABLE_TYPE,
            tour_id,
            key_condition_expression="occurrenceId = :occurrenceId",
            expression_values={":occurrenceId": occurrence_id},
        )
    except ClientError as exc:
        if _is_missing_table(exc):
            return []
        raise


def list_rider_registrations(tour_id: str, rider_id: str) -> List[Dict[str, Any]]:
    """Return all stored registrations for a rider (uses the RiderIdIndex GSI)."""
    try:
        return query_tour_items(
            REGISTRATION_TABLE_TYPE,
            tour_id,
            key_condition_expression="riderId = :riderId",
            expression_values={":riderId": rider_id},
            index_name="RiderIdIndex",
        )
    except ClientError as exc:
        if _is_missing_table(exc):
            return []
        raise


def put_registration(
    tour_id: str,
    event_id: str,
    occurrence_id: str,
    rider_id: str,
    registered_by: str,
    source: str,
) -> Dict[str, Any]:
    """Store a registration and return it."""
    item = {
        "occurrenceId": occurrence_id,
        "riderId": rider_id,
        "eventId": event_id,
        "registeredAt": utc_now_iso(),
        "registeredBy": registered_by,
        "source": source,
    }
    put_tour_item(
        REGISTRATION_TABLE_TYPE,
        tour_id,
        item=item,
        condition_expression="attribute_not_exists(occurrenceId) AND attribute_not_exists(riderId)",
    )
    return item


def delete_registration(tour_id: str, occurrence_id: str, rider_id: str) -> None:
    """Remove a stored registration."""
    get_tour_table(REGISTRATION_TABLE_TYPE, tour_id).delete_item(
        Key={"occurrenceId": occurrence_id, "riderId": rider_id}
    )


def is_registered(
    event_definition: Dict[str, Any],
    tour_rider: Optional[Dict[str, Any]],
    registration: Optional[Dict[str, Any]],
) -> bool:
    """Effective registration status for one rider and one occurrence."""
    if event_definition.get("registrationEnabled") is True:
        return registration is not None
    return is_active_rider(tour_rider)


def registered_rider_ids(
    tour_id: str,
    event_definition: Dict[str, Any],
    occurrence_id: str,
    tour_riders: List[Dict[str, Any]],
) -> Set[str]:
    """Rider IDs that count as registered for an occurrence."""
    if event_definition.get("registrationEnabled") is True:
        return {
            item.get("riderId")
            for item in list_registrations(tour_id, occurrence_id)
            if item.get("riderId")
        }
    return {
        rider.get("riderId")
        for rider in tour_riders
        if rider.get("riderId") and is_active_rider(rider)
    }
