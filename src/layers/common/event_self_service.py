"""Event registration and rider self-service record endpoints.

Rider API endpoints take the rider ID from the caller's login (see
``rider_identity``); a ``riderId`` sent by the client is rejected. Records are
written and cancelled through the shared ``event_engine.record_activity`` and
``event_engine.cancel_record`` functions so they follow exactly the same rules
as staff records.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from botocore.exceptions import ClientError

from dynamodb_utils import batch_get_items, get_tour_item
from event_engine import (
    _activity_self_service,
    _get_activity,
    _get_event_definition,
    _get_occurrence,
    cancel_record,
    get_claim,
    parse_body,
    record_activity,
)
import event_registration
from models import EventOccurrenceStatus, EventRecordOutcome, utc_now_iso
from response import bad_request_response, error_response, success_response
from rider_identity import reject_client_rider_id, resolve_active_caller_tour_rider
from validation import (
    ValidationError,
    validate_activity_id,
    validate_event_id,
    validate_iso_datetime,
    validate_occurrence_id,
    validate_rider_id,
    validate_tour_id,
)

SELF_RECORD_FIELDS = {"activityId", "timestamp", "outcome", "variantSelected"}
SELF_RECORD_OUTCOMES = {
    EventRecordOutcome.COMPLETED.value,
    EventRecordOutcome.OPTED_OUT.value,
}


def _validation_error(
    message: str, details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    return error_response("VALIDATION_ERROR", message, status_code=400, details=details)


def _occurrence_path(
    event: Dict[str, Any],
) -> Tuple[Optional[Tuple[str, str, str]], Optional[Dict[str, Any]]]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    occurrence_id = params.get("occurrenceId")
    if not tour_id or not event_id or not occurrence_id:
        return None, bad_request_response(
            "tourId, eventId and occurrenceId are required in path"
        )
    try:
        validate_tour_id(tour_id)
        validate_event_id(event_id)
        validate_occurrence_id(occurrence_id)
    except ValidationError as exc:
        return None, bad_request_response(exc.message, exc.details)
    if not occurrence_id.startswith(f"{event_id}#"):
        return None, error_response(
            "OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404
        )
    return (tour_id, event_id, occurrence_id), None


def _load_event_and_occurrence(
    tour_id: str,
    event_id: str,
    occurrence_id: str,
) -> Tuple[
    Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]
]:
    event_definition = _get_event_definition(tour_id, event_id)
    if not event_definition:
        return (
            None,
            None,
            error_response("EVENT_NOT_FOUND", "Event not found.", status_code=404),
        )
    occurrence = _get_occurrence(tour_id, event_id, occurrence_id)
    if not occurrence:
        return (
            None,
            None,
            error_response(
                "OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404
            ),
        )
    return event_definition, occurrence, None


def _check_registration_open(
    event_definition: Dict[str, Any], occurrence: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Registration rules shared by rider and staff register/un-register."""
    if event_definition.get("registrationEnabled") is not True:
        return error_response(
            "REGISTRATION_NOT_ENABLED",
            "Registration is not enabled for this event.",
            status_code=409,
        )
    if occurrence.get("status") != EventOccurrenceStatus.PLANNED.value:
        return error_response(
            "REGISTRATION_CLOSED",
            "Registration is only open while the occurrence is PLANNED.",
            status_code=409,
        )
    return None


def _register(
    tour_id: str,
    event_id: str,
    occurrence_id: str,
    rider_id: str,
    registered_by: str,
    source: str,
) -> Dict[str, Any]:
    existing = event_registration.get_registration(tour_id, occurrence_id, rider_id)
    if existing:
        return success_response(existing, status_code=200)
    try:
        item = event_registration.put_registration(
            tour_id, event_id, occurrence_id, rider_id, registered_by, source
        )
    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            != "ConditionalCheckFailedException"
        ):
            raise
        existing = event_registration.get_registration(tour_id, occurrence_id, rider_id)
        if existing:
            return success_response(existing, status_code=200)
        raise
    return success_response(item, status_code=201)


def _unregister(tour_id: str, occurrence_id: str, rider_id: str) -> Dict[str, Any]:
    if not event_registration.get_registration(tour_id, occurrence_id, rider_id):
        return error_response(
            "REGISTRATION_NOT_FOUND",
            "The rider is not registered for this occurrence.",
            status_code=404,
        )
    event_registration.delete_registration(tour_id, occurrence_id, rider_id)
    return success_response(
        {"occurrenceId": occurrence_id, "riderId": rider_id, "registered": False}
    )


def _rider_request_context(event: Dict[str, Any]):
    """Common Rider API preamble: path, body without riderId, caller identity."""
    path, error = _occurrence_path(event)
    if error:
        return None, None, None, error
    body, error = parse_body(event)
    if error:
        return None, None, None, error
    if not isinstance(body, dict):
        return None, None, None, _validation_error("Request body must be a JSON object")
    denied = reject_client_rider_id(body, [event.get("queryStringParameters") or {}])
    if denied:
        return None, None, None, denied
    identity, error = resolve_active_caller_tour_rider(event, path[0])
    if error:
        return None, None, None, error
    return path, body, identity, None


# ---------------------------------------------------------------------------
# Rider API: own registration
# ---------------------------------------------------------------------------


def register_self(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST .../occurrences/{occurrenceId}/registration (Rider API)."""
    path, _body, identity, error = _rider_request_context(event)
    if error:
        return error
    tour_id, event_id, occurrence_id = path
    event_definition, occurrence, error = _load_event_and_occurrence(
        tour_id, event_id, occurrence_id
    )
    if error:
        return error
    error = _check_registration_open(event_definition, occurrence)
    if error:
        return error
    return _register(
        tour_id,
        event_id,
        occurrence_id,
        identity["riderId"],
        identity["profileId"],
        event_registration.SOURCE_RIDER,
    )


def unregister_self(event: Dict[str, Any]) -> Dict[str, Any]:
    """DELETE .../occurrences/{occurrenceId}/registration (Rider API)."""
    path, _body, identity, error = _rider_request_context(event)
    if error:
        return error
    tour_id, event_id, occurrence_id = path
    event_definition, occurrence, error = _load_event_and_occurrence(
        tour_id, event_id, occurrence_id
    )
    if error:
        return error
    error = _check_registration_open(event_definition, occurrence)
    if error:
        return error
    return _unregister(tour_id, occurrence_id, identity["riderId"])


# ---------------------------------------------------------------------------
# Mgmt API: staff-managed registrations
# ---------------------------------------------------------------------------


def list_registrations(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET .../occurrences/{occurrenceId}/registrations (Mgmt API)."""
    path, error = _occurrence_path(event)
    if error:
        return error
    tour_id, event_id, occurrence_id = path
    event_definition, _occurrence, error = _load_event_and_occurrence(
        tour_id, event_id, occurrence_id
    )
    if error:
        return error
    registration_enabled = event_definition.get("registrationEnabled") is True
    items = []
    if registration_enabled:
        registrations = event_registration.list_registrations(tour_id, occurrence_id)
        names = _rider_names(tour_id, [item.get("riderId") for item in registrations])
        items = [
            {
                "riderId": item.get("riderId"),
                "name": names.get(item.get("riderId")),
                "registeredAt": item.get("registeredAt"),
                "registeredBy": item.get("registeredBy"),
                "source": item.get("source"),
            }
            for item in sorted(
                registrations, key=lambda item: item.get("riderId") or ""
            )
        ]
    return success_response(
        {
            "occurrenceId": occurrence_id,
            "registrationEnabled": registration_enabled,
            "count": len(items),
            "items": items,
        }
    )


def _rider_names(tour_id: str, rider_ids) -> Dict[str, Optional[str]]:
    """Map riderId -> rider profile name (None when unknown)."""
    profile_ids = {}
    for rider_id in rider_ids:
        if not rider_id:
            continue
        tour_rider = get_tour_item("TourRider", tour_id, {"riderId": rider_id}) or {}
        if tour_rider.get("profileId"):
            profile_ids[rider_id] = tour_rider["profileId"]
    keys = [
        {"profileId": profile_id} for profile_id in sorted(set(profile_ids.values()))
    ]
    profiles = (
        {
            item.get("profileId"): item
            for item in batch_get_items("RIDER_PROFILE_TABLE", keys)
        }
        if keys
        else {}
    )
    return {
        rider_id: (profiles.get(profile_id) or {}).get("name")
        for rider_id, profile_id in profile_ids.items()
    }


def _staff_rider_path(event: Dict[str, Any]):
    path, error = _occurrence_path(event)
    if error:
        return None, None, error
    rider_id = (event.get("pathParameters") or {}).get("riderId")
    if not rider_id:
        return None, None, bad_request_response("riderId is required in path")
    try:
        validate_rider_id(rider_id)
    except ValidationError as exc:
        return None, None, bad_request_response(exc.message, exc.details)
    return path, rider_id, None


def staff_register(event: Dict[str, Any]) -> Dict[str, Any]:
    """PUT .../occurrences/{occurrenceId}/registrations/{riderId} (Mgmt API)."""
    path, rider_id, error = _staff_rider_path(event)
    if error:
        return error
    tour_id, event_id, occurrence_id = path
    event_definition, occurrence, error = _load_event_and_occurrence(
        tour_id, event_id, occurrence_id
    )
    if error:
        return error
    error = _check_registration_open(event_definition, occurrence)
    if error:
        return error
    tour_rider = get_tour_item("TourRider", tour_id, {"riderId": rider_id})
    if not event_registration.is_active_rider(tour_rider):
        return error_response(
            "RIDER_NOT_FOUND", "Rider not found on this tour.", status_code=404
        )
    return _register(
        tour_id,
        event_id,
        occurrence_id,
        rider_id,
        get_claim(event, "sub", "system"),
        event_registration.SOURCE_STAFF,
    )


def staff_unregister(event: Dict[str, Any]) -> Dict[str, Any]:
    """DELETE .../occurrences/{occurrenceId}/registrations/{riderId} (Mgmt API)."""
    path, rider_id, error = _staff_rider_path(event)
    if error:
        return error
    tour_id, event_id, occurrence_id = path
    event_definition, occurrence, error = _load_event_and_occurrence(
        tour_id, event_id, occurrence_id
    )
    if error:
        return error
    error = _check_registration_open(event_definition, occurrence)
    if error:
        return error
    return _unregister(tour_id, occurrence_id, rider_id)


# ---------------------------------------------------------------------------
# Rider API: self-service activity records
# ---------------------------------------------------------------------------


def create_self_record(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST .../occurrences/{occurrenceId}/self-records (Rider API)."""
    path, body, identity, error = _rider_request_context(event)
    if error:
        return error
    tour_id, event_id, occurrence_id = path

    unknown = sorted(set(body) - SELF_RECORD_FIELDS)
    if unknown:
        return _validation_error(
            f"Unsupported field(s): {', '.join(unknown)}",
            {"field": unknown[0], "allowed": sorted(SELF_RECORD_FIELDS)},
        )
    activity_id = body.get("activityId")
    if not activity_id:
        return _validation_error("activityId is required", {"field": "activityId"})
    outcome = body.get("outcome", EventRecordOutcome.COMPLETED.value)
    try:
        validate_activity_id(activity_id)
        timestamp = body.get("timestamp") or utc_now_iso()
        validate_iso_datetime(timestamp, "timestamp")
        if outcome not in SELF_RECORD_OUTCOMES:
            raise ValidationError(
                "outcome must be COMPLETED or OPTED_OUT",
                {"field": "outcome", "value": outcome},
            )
        variant = body.get("variantSelected")
        if variant is not None and not isinstance(variant, str):
            raise ValidationError(
                "variantSelected must be a string", {"field": "variantSelected"}
            )
    except ValidationError as exc:
        return _validation_error(exc.message, exc.details)

    record_body = {
        "activityId": activity_id,
        "timestamp": timestamp,
        "outcome": outcome,
    }
    if body.get("variantSelected") is not None:
        record_body["variantSelected"] = body["variantSelected"]

    return record_activity(
        event,
        tour_id=tour_id,
        event_id=event_id,
        occurrence_id=occurrence_id,
        body=record_body,
        rider_id=identity["riderId"],
        recorded_by=identity["profileId"],
        self_service=True,
    )


def cancel_self_record(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST .../occurrences/{occurrenceId}/self-records/{recordId}/cancel (Rider API)."""
    path, body, identity, error = _rider_request_context(event)
    if error:
        return error
    tour_id, event_id, occurrence_id = path
    record_id = (event.get("pathParameters") or {}).get("recordId")
    if not record_id:
        return bad_request_response("recordId is required in path")

    event_definition, occurrence, error = _load_event_and_occurrence(
        tour_id, event_id, occurrence_id
    )
    if error:
        return error
    record = get_tour_item(
        "EventActivityLogs",
        tour_id,
        {"occurrenceId": occurrence_id, "recordId": record_id},
    )
    if not record:
        return error_response("RECORD_NOT_FOUND", "Record not found.", status_code=404)
    if record.get("riderId") != identity["riderId"]:
        return error_response(
            "NOT_OWN_RECORD",
            "You can only cancel your own activity records.",
            status_code=403,
        )
    if occurrence.get("status") != EventOccurrenceStatus.ACTIVE.value:
        return error_response(
            "OCCURRENCE_NOT_ACTIVE", "Occurrence is not active.", status_code=409
        )
    activity = _get_activity(event_definition, record.get("activityId")) or {
        "activityId": record.get("activityId")
    }
    if not _activity_self_service(event_definition, occurrence, activity):
        return error_response(
            "SELF_SERVICE_NOT_ALLOWED",
            "Self-service is not allowed for this activity.",
            status_code=403,
        )
    return cancel_record(
        tour_id, record, identity["profileId"], (body or {}).get("cancelReason")
    )
