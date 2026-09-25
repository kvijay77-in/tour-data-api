"""Shared event engine, hotel, and tour-user helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import uuid
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from dynamodb_utils import (
    get_item,
    get_tour_item,
    put_tour_item,
    query_items,
    query_tour_items,
    scan_tour_items,
    update_tour_item,
)
from models import (
    ActivityDefinition,
    ActivityOverride,
    BaggageStatus,
    CheckInMethod,
    DietaryPreference,
    EventActivityRecord,
    EventDefinition,
    EventOccurrence,
    EventOccurrenceStatus,
    EventRecordOutcome,
    EventType,
    Hotel,
    RoomAllocation,
    TourRiderStatus,
    UserRole,
    utc_now_iso,
    utc_today_iso,
)
from response import (
    bad_request_response,
    conflict_response,
    error_response,
    internal_error_response,
    not_found_response,
    not_modified_response,
    success_response,
)
from validation import (
    ValidationError,
    validate_activity_id,
    validate_allowed_type_codes,
    validate_baggage_status,
    validate_cognito_user_id,
    validate_event_id,
    validate_event_occurrence_status,
    validate_event_type,
    validate_hotel_id,
    validate_iso_date,
    validate_iso_datetime,
    validate_occurrence_id,
    validate_required_fields,
    validate_rider_id,
    validate_sharing_with,
    validate_tour_id,
    validate_upload_id,
    validate_variant_options,
)


s3_client = boto3.client("s3")
cognito_client = boto3.client("cognito-idp")


def parse_body(event: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Parse a JSON body and return (body, error_response)."""
    raw_body = event.get("body") or "{}"
    if isinstance(raw_body, dict):
        return raw_body, None
    try:
        return json.loads(raw_body), None
    except json.JSONDecodeError:
        return None, bad_request_response("Invalid JSON in request body")


def get_claim(event: Dict[str, Any], key: str, default: str = "") -> str:
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
        .get(key, default)
    )


def _get_enabled_id_code_types() -> Dict[str, Dict[str, Any]]:
    items = query_items(
        table_name_env="APP_CONFIG_TABLE",
        key_condition_expression="configType = :configType",
        expression_values={":configType": "ID_CODE_TYPE"},
    )
    result: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if item.get("enabled") is True:
            result[str(item.get("configId"))] = item
    return result


def _validate_allowed_type_codes_exist(allowed_type_codes: List[str]) -> None:
    enabled_codes = _get_enabled_id_code_types()
    for code in allowed_type_codes:
        if code not in enabled_codes:
            raise ValidationError(
                f"Unknown or disabled ID code type: {code}",
                {"field": "allowedTypeCodes", "value": code},
            )


def _get_event_definition(tour_id: str, event_id: str) -> Optional[Dict[str, Any]]:
    return get_tour_item("Event", tour_id, {"eventId": event_id})


def _get_occurrence(tour_id: str, event_id: str, occurrence_id: str) -> Optional[Dict[str, Any]]:
    parts = occurrence_id.split("#", 1)
    if len(parts) != 2:
        return None
    return get_tour_item("EventOccurrence", tour_id, {"eventId": event_id, "dateSeq": parts[1]})


def _get_activity(event_definition: Dict[str, Any], activity_id: str) -> Optional[Dict[str, Any]]:
    for activity in event_definition.get("activities", []):
        if activity.get("activityId") == activity_id:
            return activity
    return None


def _event_etag(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _normalise_activity(activity: Dict[str, Any]) -> ActivityDefinition:
    validate_required_fields(activity, ["activityId", "name", "sequenceNo"])
    validate_activity_id(activity["activityId"])
    validate_allowed_type_codes(activity.get("allowedTypeCodes", []))
    validate_variant_options(activity.get("variantOptions", []))

    prerequisite_ids = activity.get("prerequisiteActivityIds") or []
    if not isinstance(prerequisite_ids, list):
        raise ValidationError("prerequisiteActivityIds must be a list", {"field": "prerequisiteActivityIds"})
    for prerequisite_id in prerequisite_ids:
        validate_activity_id(prerequisite_id)

    return ActivityDefinition(
        activityId=activity["activityId"],
        name=activity["name"],
        sequenceNo=int(activity["sequenceNo"]),
        enabled=bool(activity.get("enabled", True)),
        mandatory=bool(activity.get("mandatory", False)),
        allowedTypeCodes=activity.get("allowedTypeCodes", []) or [],
        allowOptOut=bool(activity.get("allowOptOut", False)),
        prerequisiteActivityIds=prerequisite_ids,
        restrictToAssignedUsers=bool(activity.get("restrictToAssignedUsers", True)),
        variantOptions=activity.get("variantOptions", []) or [],
        notes=activity.get("notes", "") or "",
    )


def _validate_activities(activities: Any) -> List[ActivityDefinition]:
    if not isinstance(activities, list) or not activities:
        raise ValidationError("activities must be a non-empty list", {"field": "activities", "value": activities})

    normalized = [_normalise_activity(activity) for activity in activities]
    activity_ids = [activity.activityId for activity in normalized]
    if len(activity_ids) != len(set(activity_ids)):
        raise ValidationError("Duplicate activityId found in activities", {"field": "activities"})

    sequence_numbers = [activity.sequenceNo for activity in normalized]
    if sequence_numbers != sorted(sequence_numbers):
        raise ValidationError("activities must be ordered by ascending sequenceNo", {"field": "activities"})

    known_ids = set(activity_ids)
    for activity in normalized:
        unknown = [item for item in activity.prerequisiteActivityIds if item not in known_ids]
        if unknown:
            raise ValidationError(
                f"Activity {activity.activityId} has unknown prerequisiteActivityIds",
                {"field": "prerequisiteActivityIds", "value": unknown},
            )

    return normalized


def _scan_records_for_occurrence(tour_id: str, occurrence_id: str) -> List[Dict[str, Any]]:
    return query_tour_items(
        "EventActivityLogs",
        tour_id,
        key_condition_expression="occurrenceId = :occurrenceId",
        expression_values={":occurrenceId": occurrence_id},
    )


def _non_cancelled_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [record for record in records if not record.get("cancelledAt")]


def _effective_allowed_type_codes(
    event_definition: Dict[str, Any],
    occurrence: Dict[str, Any],
    activity: Dict[str, Any],
) -> List[str]:
    allowed_type_codes = activity.get("allowedTypeCodes") or event_definition.get("defaultAllowedTypeCodes") or []
    for override in occurrence.get("activityOverrides", []) or []:
        if override.get("activityId") == activity.get("activityId") and override.get("allowedTypeCodes") is not None:
            allowed_type_codes = override.get("allowedTypeCodes") or []
            break
    return allowed_type_codes


def _effective_activity_enabled(occurrence: Dict[str, Any], activity: Dict[str, Any]) -> bool:
    enabled = bool(activity.get("enabled", True))
    for override in occurrence.get("activityOverrides", []) or []:
        if override.get("activityId") == activity.get("activityId") and override.get("enabled") is not None:
            return bool(override.get("enabled"))
    return enabled


def _load_user_assignment(tour_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    return get_tour_item("User", tour_id, {"userId": user_id})


def _is_baggage_event(event_definition: Dict[str, Any]) -> bool:
    event_id = str(event_definition.get("eventId", ""))
    return "BAG" in event_id


def _check_event_scan_access(
    event: Dict[str, Any],
    tour_id: str,
    event_definition: Dict[str, Any],
    occurrence: Dict[str, Any],
    activity: Dict[str, Any],
    rider_id: str,
) -> Optional[Dict[str, Any]]:
    user_id = get_claim(event, "sub")
    if not user_id:
        return error_response("FORBIDDEN", "User identity missing.", status_code=403)

    user_record = _load_user_assignment(tour_id, user_id)
    if not user_record:
        return error_response("RIDER_NOT_ASSIGNED", "You are not assigned to this event today.", status_code=403)

    if activity.get("restrictToAssignedUsers", True):
        assignments = user_record.get("eventAssignments") or []
        assignment_match = False
        for assignment in assignments:
            if assignment.get("eventId") != occurrence.get("eventId"):
                continue
            dates = assignment.get("dates")
            if dates == "ALL" or dates == ["ALL"]:
                assignment_match = True
                break
            if isinstance(dates, list) and occurrence.get("date") in dates:
                assignment_match = True
                break
        if assignments and not assignment_match:
            return error_response("RIDER_NOT_ASSIGNED", "You are not assigned to this event today.", status_code=403)

    assigned_activity_ids = user_record.get("assignedActivityIds") or []
    if assigned_activity_ids and activity.get("activityId") not in assigned_activity_ids:
        return error_response("RIDER_NOT_ASSIGNED", "You are not assigned to this event today.", status_code=403)

    if _is_baggage_event(event_definition) and user_record.get("hotelId"):
        rider_allocation = get_tour_item(
            "RoomAllocation",
            tour_id,
            {"stayDate": occurrence.get("date"), "riderId": rider_id},
        )
        if not rider_allocation or rider_allocation.get("hotelId") != user_record.get("hotelId"):
            return error_response(
                "HOTEL_MISMATCH",
                "This rider is not staying at your assigned hotel tonight.",
                status_code=403,
            )

    return None


def list_events(event: Dict[str, Any]) -> Dict[str, Any]:
    tour_id = (event.get("pathParameters") or {}).get("tourId")
    if not tour_id:
        return bad_request_response("tourId is required in path")
    try:
        validate_tour_id(tour_id)
    except ValidationError as exc:
        return bad_request_response(exc.message, exc.details)
    items = sorted(scan_tour_items("Event", tour_id), key=lambda item: item.get("eventId", ""))
    return success_response({"items": items})


def get_event_definition_response(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    if not tour_id or not event_id:
        return bad_request_response("tourId and eventId are required in path")
    try:
        validate_tour_id(tour_id)
        validate_event_id(event_id)
    except ValidationError as exc:
        return bad_request_response(exc.message, exc.details)
    item = _get_event_definition(tour_id, event_id)
    if not item:
        return error_response("EVENT_NOT_FOUND", "Event not found.", status_code=404)
    return success_response(item)


def create_event_definition(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    if not tour_id:
        return bad_request_response("tourId is required in path")
    body, err = parse_body(event)
    if err:
        return err
    try:
        validate_tour_id(tour_id)
        validate_required_fields(
            body,
            [
                "eventId",
                "eventName",
                "eventType",
                "location",
                "sequenceEnforced",
                "defaultAllowedTypeCodes",
                "activities",
            ],
        )
        validate_event_id(body["eventId"])
        validate_event_type(body["eventType"])
        validate_allowed_type_codes(body.get("defaultAllowedTypeCodes"))
        _validate_allowed_type_codes_exist(body.get("defaultAllowedTypeCodes") or [])
        activities = _validate_activities(body["activities"])
        for activity in activities:
            _validate_allowed_type_codes_exist(activity.allowedTypeCodes)
    except ValidationError as exc:
        return error_response("VALIDATION_ERROR", exc.message, status_code=400, details=exc.details)

    item = EventDefinition(
        eventId=body["eventId"],
        eventName=body["eventName"],
        eventType=EventType(body["eventType"]),
        location=body["location"],
        sequenceEnforced=bool(body["sequenceEnforced"]),
        defaultAllowedTypeCodes=body.get("defaultAllowedTypeCodes") or [],
        allowSelfService=bool(body.get("allowSelfService", False)),
        activities=activities,
        updatedBy=get_claim(event, "sub"),
    ).to_dict()

    try:
        put_tour_item(
            "Event",
            tour_id,
            item=item,
            condition_expression="attribute_not_exists(eventId)",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return error_response("EVENT_ALREADY_EXISTS", "A event with this ID already exists.", status_code=409)
        return internal_error_response("Failed to create event")

    return success_response(item, status_code=201)


def update_event_definition(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    if not tour_id or not event_id:
        return bad_request_response("tourId and eventId are required in path")
    body, err = parse_body(event)
    if err:
        return err
    try:
        validate_tour_id(tour_id)
        validate_event_id(event_id)
    except ValidationError as exc:
        return bad_request_response(exc.message, exc.details)

    existing = _get_event_definition(tour_id, event_id)
    if not existing:
        return error_response("EVENT_NOT_FOUND", "Event not found.", status_code=404)

    updated = dict(existing)
    try:
        if "eventType" in body:
            validate_event_type(body["eventType"])
            updated["eventType"] = body["eventType"]
        if "defaultAllowedTypeCodes" in body:
            validate_allowed_type_codes(body["defaultAllowedTypeCodes"])
            _validate_allowed_type_codes_exist(body["defaultAllowedTypeCodes"] or [])
            updated["defaultAllowedTypeCodes"] = body.get("defaultAllowedTypeCodes") or []
        if "activities" in body:
            activities = _validate_activities(body["activities"])
            for activity in activities:
                _validate_allowed_type_codes_exist(activity.allowedTypeCodes)
            updated["activities"] = [activity.to_dict() for activity in activities]
        for field in ("eventName", "location", "sequenceEnforced", "allowSelfService"):
            if field in body:
                updated[field] = body[field]
    except ValidationError as exc:
        return error_response("VALIDATION_ERROR", exc.message, status_code=400, details=exc.details)

    updated["updatedAt"] = utc_now_iso()
    updated["updatedBy"] = get_claim(event, "sub")

    try:
        put_tour_item("Event", tour_id, updated, condition_expression="attribute_exists(eventId)")
    except ClientError:
        return internal_error_response("Failed to update event")
    return success_response(updated)


def list_occurrences(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    if not tour_id or not event_id:
        return bad_request_response("tourId and eventId are required in path")
    try:
        validate_tour_id(tour_id)
        validate_event_id(event_id)
    except ValidationError as exc:
        return bad_request_response(exc.message, exc.details)
    if not _get_event_definition(tour_id, event_id):
        return error_response("EVENT_NOT_FOUND", "Event not found.", status_code=404)
    items = query_tour_items(
        "EventOccurrence",
        tour_id,
        key_condition_expression="eventId = :eventId",
        expression_values={":eventId": event_id},
    )
    date_filter = query_params.get("date")
    status_filter = query_params.get("status")
    try:
        if date_filter:
            validate_iso_date(date_filter, "date")
        if status_filter:
            validate_event_occurrence_status(status_filter)
    except ValidationError as exc:
        return bad_request_response(exc.message, exc.details)
    if date_filter:
        items = [item for item in items if item.get("date") == date_filter]
    if status_filter:
        items = [item for item in items if item.get("status") == status_filter]
    return success_response({"items": sorted(items, key=lambda item: item.get("dateSeq", ""))})


def get_occurrence_response(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    occurrence_id = params.get("occurrenceId")
    if not tour_id or not event_id or not occurrence_id:
        return bad_request_response("tourId, eventId and occurrenceId are required in path")
    try:
        validate_tour_id(tour_id)
        validate_event_id(event_id)
        validate_occurrence_id(occurrence_id)
    except ValidationError as exc:
        return bad_request_response(exc.message, exc.details)
    occurrence = _get_occurrence(tour_id, event_id, occurrence_id)
    if not occurrence:
        return error_response("OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404)
    return success_response(occurrence)


def create_occurrence(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    if not tour_id or not event_id:
        return bad_request_response("tourId and eventId are required in path")
    body, err = parse_body(event)
    if err:
        return err
    event_definition = _get_event_definition(tour_id, event_id)
    if not event_definition:
        return error_response("EVENT_NOT_FOUND", "Event not found.", status_code=404)
    try:
        validate_required_fields(body, ["date", "seq"])
        validate_iso_date(body["date"], "date")
        seq = int(body["seq"])
        if seq <= 0:
            raise ValidationError("seq must be a positive integer", {"field": "seq", "value": body["seq"]})
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            return error_response("VALIDATION_ERROR", exc.message, status_code=400, details=exc.details)
        return bad_request_response("seq must be a positive integer")

    occurrence_id = f"{event_id}#{body['date']}#{seq}"
    item = EventOccurrence(
        eventId=event_id,
        dateSeq=f"{body['date']}#{seq}",
        occurrenceId=occurrence_id,
        date=body["date"],
        seq=seq,
        selfServiceEnabled=bool(body.get("selfServiceEnabled", event_definition.get("allowSelfService", False))),
        linkedOccurrenceRef=body.get("linkedOccurrenceRef"),
        restrictToAssignedUsers=True,
        updatedBy=get_claim(event, "sub"),
    ).to_dict()
    try:
        put_tour_item(
            "EventOccurrence",
            tour_id,
            item=item,
            condition_expression="attribute_not_exists(eventId) AND attribute_not_exists(dateSeq)",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return error_response("OCCURRENCE_ALREADY_EXISTS", "An occurrence for this date and sequence already exists.", status_code=409)
        return internal_error_response("Failed to create occurrence")
    return success_response(item, status_code=201)


def update_occurrence(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    occurrence_id = params.get("occurrenceId")
    if not tour_id or not event_id or not occurrence_id:
        return bad_request_response("tourId, eventId and occurrenceId are required in path")
    body, err = parse_body(event)
    if err:
        return err
    occurrence = _get_occurrence(tour_id, event_id, occurrence_id)
    if not occurrence:
        return error_response("OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404)
    if occurrence.get("status") in {EventOccurrenceStatus.COMPLETED.value, EventOccurrenceStatus.CANCELLED.value}:
        return error_response("OCCURRENCE_CLOSED", "Occurrence is already closed.", status_code=409)
    if "selfServiceEnabled" in body:
        occurrence["selfServiceEnabled"] = bool(body["selfServiceEnabled"])
    if "linkedOccurrenceRef" in body:
        occurrence["linkedOccurrenceRef"] = body.get("linkedOccurrenceRef")
    occurrence["updatedAt"] = utc_now_iso()
    occurrence["updatedBy"] = get_claim(event, "sub")
    put_tour_item("EventOccurrence", tour_id, occurrence, condition_expression="attribute_exists(eventId)")
    return success_response(occurrence)


def get_activity_overrides(event: Dict[str, Any]) -> Dict[str, Any]:
    response = get_occurrence_response(event)
    if response.get("statusCode") != 200:
        return response
    body = json.loads(response["body"])
    occurrence = body["data"]
    return success_response({"items": occurrence.get("activityOverrides", [])})


def update_activity_override(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    occurrence_id = params.get("occurrenceId")
    if not tour_id or not event_id or not occurrence_id:
        return bad_request_response("tourId, eventId and occurrenceId are required in path")
    body, err = parse_body(event)
    if err:
        return err
    occurrence = _get_occurrence(tour_id, event_id, occurrence_id)
    event_definition = _get_event_definition(tour_id, event_id)
    if not occurrence:
        return error_response("OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404)
    if not event_definition:
        return error_response("EVENT_NOT_FOUND", "Event not found.", status_code=404)
    if occurrence.get("status") in {EventOccurrenceStatus.COMPLETED.value, EventOccurrenceStatus.CANCELLED.value}:
        return error_response("OCCURRENCE_CLOSED", "Occurrence is already closed.", status_code=409)

    activity_id = body.get("activityId")
    if not activity_id:
        return error_response("VALIDATION_ERROR", "activityId is required", status_code=400)
    try:
        validate_activity_id(activity_id)
        validate_allowed_type_codes(body.get("allowedTypeCodes"), "allowedTypeCodes")
        if body.get("allowedTypeCodes") is not None:
            _validate_allowed_type_codes_exist(body.get("allowedTypeCodes") or [])
    except ValidationError as exc:
        return error_response("VALIDATION_ERROR", exc.message, status_code=400, details=exc.details)

    if not _get_activity(event_definition, activity_id):
        return error_response("ACTIVITY_NOT_FOUND", "Activity not found.", status_code=404)

    overrides = occurrence.get("activityOverrides", []) or []
    matched = None
    for override in overrides:
        if override.get("activityId") == activity_id:
            matched = override
            break
    if matched is None:
        matched = {"activityId": activity_id}
        overrides.append(matched)

    for field in ("enabled", "selfServiceEnabled", "allowedTypeCodes", "note"):
        if field in body:
            matched[field] = body.get(field)
    matched["updatedAt"] = utc_now_iso()
    matched["updatedBy"] = get_claim(event, "sub")

    if matched.get("enabled") is None and matched.get("selfServiceEnabled") is None and matched.get("allowedTypeCodes") is None:
        overrides = [override for override in overrides if override.get("activityId") != activity_id]

    occurrence["activityOverrides"] = overrides
    occurrence["updatedAt"] = utc_now_iso()
    occurrence["updatedBy"] = get_claim(event, "sub")
    put_tour_item("EventOccurrence", tour_id, occurrence, condition_expression="attribute_exists(eventId)")
    return success_response({"items": overrides})


def _transition_occurrence_status(
    event: Dict[str, Any],
    expected_status: str,
    next_status: str,
    timestamp_field: str,
    cancelled: bool = False,
) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    occurrence_id = params.get("occurrenceId")
    if not tour_id or not event_id or not occurrence_id:
        return bad_request_response("tourId, eventId and occurrenceId are required in path")
    occurrence = _get_occurrence(tour_id, event_id, occurrence_id)
    if not occurrence:
        return error_response("OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404)
    if occurrence.get("status") != expected_status:
        return error_response("INVALID_OCCURRENCE_TRANSITION", "Invalid occurrence status transition.", status_code=409)
    now = utc_now_iso()
    occurrence["status"] = next_status
    occurrence[timestamp_field] = now
    occurrence["updatedAt"] = now
    occurrence["updatedBy"] = get_claim(event, "sub")
    if cancelled:
        body, _ = parse_body(event)
        occurrence["cancelledBy"] = get_claim(event, "sub")
        occurrence["cancelReason"] = (body or {}).get("cancelReason")
    put_tour_item("EventOccurrence", tour_id, occurrence, condition_expression="attribute_exists(eventId)")
    if next_status == EventOccurrenceStatus.COMPLETED.value:
        return success_response({**occurrence, "outstandingMandatoryCount": _count_outstanding_mandatory(tour_id, event_id, occurrence)})
    return success_response(occurrence)


def start_occurrence(event: Dict[str, Any]) -> Dict[str, Any]:
    return _transition_occurrence_status(
        event,
        expected_status=EventOccurrenceStatus.PLANNED.value,
        next_status=EventOccurrenceStatus.ACTIVE.value,
        timestamp_field="startedAt",
    )


def complete_occurrence(event: Dict[str, Any]) -> Dict[str, Any]:
    return _transition_occurrence_status(
        event,
        expected_status=EventOccurrenceStatus.ACTIVE.value,
        next_status=EventOccurrenceStatus.COMPLETED.value,
        timestamp_field="completedAt",
    )


def cancel_occurrence(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    occurrence = _get_occurrence(params.get("tourId"), params.get("eventId"), params.get("occurrenceId"))
    if not occurrence:
        return error_response("OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404)
    if occurrence.get("status") in {EventOccurrenceStatus.COMPLETED.value, EventOccurrenceStatus.CANCELLED.value}:
        return error_response("INVALID_OCCURRENCE_TRANSITION", "Invalid occurrence status transition.", status_code=409)
    return _transition_occurrence_status(
        event,
        expected_status=occurrence.get("status"),
        next_status=EventOccurrenceStatus.CANCELLED.value,
        timestamp_field="cancelledAt",
        cancelled=True,
    )


def _count_outstanding_mandatory(tour_id: str, event_id: str, occurrence: Dict[str, Any]) -> int:
    event_definition = _get_event_definition(tour_id, event_id) or {}
    mandatory_activities = [
        activity for activity in event_definition.get("activities", [])
        if activity.get("mandatory") and _effective_activity_enabled(occurrence, activity)
    ]
    if not mandatory_activities:
        return 0
    riders = scan_tour_items("TourRider", tour_id)
    records = _non_cancelled_records(_scan_records_for_occurrence(tour_id, occurrence["occurrenceId"]))
    completed_pairs = {(record.get("riderId"), record.get("activityId")) for record in records}
    outstanding = 0
    for rider in riders:
        for activity in mandatory_activities:
            if (rider.get("riderId"), activity.get("activityId")) not in completed_pairs:
                outstanding += 1
    return outstanding


def create_activity_record(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    occurrence_id = params.get("occurrenceId")
    if not tour_id or not event_id or not occurrence_id:
        return bad_request_response("tourId, eventId and occurrenceId are required in path")
    body, err = parse_body(event)
    if err:
        return err
    try:
        validate_required_fields(body, ["activityId", "riderId", "method", "timestamp"])
        validate_activity_id(body["activityId"])
        validate_rider_id(body["riderId"])
        validate_iso_datetime(body["timestamp"], "timestamp")
    except ValidationError as exc:
        return error_response("VALIDATION_ERROR", exc.message, status_code=400, details=exc.details)

    event_definition = _get_event_definition(tour_id, event_id)
    occurrence = _get_occurrence(tour_id, event_id, occurrence_id)
    if not event_definition:
        return error_response("EVENT_NOT_FOUND", "Event not found.", status_code=404)
    if not occurrence:
        return error_response("OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404)
    activity = _get_activity(event_definition, body["activityId"])
    if not activity:
        return error_response("ACTIVITY_NOT_FOUND", "Activity not found.", status_code=404)
    if not _effective_activity_enabled(occurrence, activity):
        return error_response("ACTIVITY_NOT_FOUND", "Activity not found.", status_code=404)

    if occurrence.get("status") != EventOccurrenceStatus.ACTIVE.value:
        return error_response("OCCURRENCE_NOT_ACTIVE", "Occurrence is not active.", status_code=409)

    access_denied = _check_event_scan_access(event, tour_id, event_definition, occurrence, activity, body["riderId"])
    if access_denied:
        return access_denied

    rider = get_tour_item("TourRider", tour_id, {"riderId": body["riderId"]})
    if not rider:
        return error_response("RIDER_NOT_FOUND", "Rider not found.", status_code=404)

    flagged = False
    flag_reason = None
    if rider.get("baggageStatus") == BaggageStatus.WITH_RIDER.value and _is_baggage_event(event_definition):
        baggage_released_at = rider.get("baggageReleasedAt")
        if baggage_released_at and body["timestamp"] < baggage_released_at:
            flagged = True
            flag_reason = "LATE_SYNC_BEFORE_BAGGAGE_RELEASE"
        else:
            rider_profile = get_item("RIDER_PROFILE_TABLE", {"profileId": rider.get("profileId")}) or {}
            rider_name = rider_profile.get("name", body["riderId"])
            release_date = baggage_released_at or "an earlier date"
            return error_response(
                "BAGGAGE_NOT_IN_TOUR",
                f"{rider_name}'s baggage was returned to them on {release_date} and can no longer be scanned.",
                status_code=409,
            )

    if body.get("outcome") == EventRecordOutcome.OPTED_OUT.value and not activity.get("allowOptOut", False):
        return error_response("VALIDATION_ERROR", "This activity does not allow opt-out.", status_code=400)

    type_code = body.get("typeCode")
    requires_type_code = body.get("outcome") != EventRecordOutcome.OPTED_OUT.value
    effective_allowed_type_codes = _effective_allowed_type_codes(event_definition, occurrence, activity)
    if requires_type_code and not type_code:
        return error_response("VALIDATION_ERROR", "typeCode is required for this activity record.", status_code=400)
    if type_code and type_code not in effective_allowed_type_codes:
        return error_response(
            "SCAN_TYPE_NOT_ALLOWED",
            "The scanned type is not allowed for this event activity.",
            status_code=400,
        )

    variant_options = activity.get("variantOptions") or []
    if variant_options and body.get("variantSelected") not in variant_options:
        return error_response("VALIDATION_ERROR", "variantSelected is required and must match variantOptions.", status_code=400)

    records = _non_cancelled_records(_scan_records_for_occurrence(tour_id, occurrence_id))
    for record in records:
        if record.get("riderId") == body["riderId"] and record.get("activityId") == body["activityId"]:
            return error_response("DUPLICATE_ACTIVITY_RECORD", "Activity already recorded for this rider.", status_code=409)

    sequence_enforced = bool(event_definition.get("sequenceEnforced"))
    completed_activity_ids = {
        record.get("activityId")
        for record in records
        if record.get("riderId") == body["riderId"] and record.get("outcome") in {EventRecordOutcome.COMPLETED.value, EventRecordOutcome.OPTED_OUT.value}
    }
    prerequisites = set(activity.get("prerequisiteActivityIds") or [])
    if sequence_enforced:
        current_sequence = activity.get("sequenceNo")
        for candidate in event_definition.get("activities") or []:
            candidate_sequence = candidate.get("sequenceNo")
            candidate_id = candidate.get("activityId")
            if candidate_id == body["activityId"] or candidate_sequence is None or current_sequence is None:
                continue
            if candidate_sequence >= current_sequence:
                continue
            if not _effective_activity_enabled(occurrence, candidate):
                continue
            prerequisites.add(candidate_id)
    if sequence_enforced or prerequisites:
        missing = [activity_id for activity_id in prerequisites if activity_id not in completed_activity_ids]
        if missing:
            return error_response("PREREQUISITE_NOT_MET", "Prerequisite activity not yet completed.", status_code=409)

    record_id = f"{body['riderId']}#{body['activityId']}#{body['timestamp']}"
    type_map = _get_enabled_id_code_types()
    bag_label = ((type_map.get(type_code) or {}).get("config", {}) or {}).get("name")
    scanned_by = get_claim(event, "sub", "system")
    user_record = _load_user_assignment(tour_id, scanned_by) or {}

    item = EventActivityRecord(
        occurrenceId=occurrence_id,
        recordId=record_id,
        eventId=event_id,
        activityId=body["activityId"],
        activityName=activity.get("name"),
        riderId=body["riderId"],
        scannedBy=scanned_by,
        typeCode=type_code,
        bagLabel=bag_label,
        outcome=EventRecordOutcome(body.get("outcome", EventRecordOutcome.COMPLETED.value)),
        variantSelected=body.get("variantSelected"),
        hotelId=user_record.get("hotelId"),
        method=body["method"],
        timestamp=body["timestamp"],
        syncedAt=utc_now_iso(),
        isFlagged=flagged,
        flagReason=flag_reason,
    ).to_dict()

    try:
        put_tour_item(
            "EventActivityLogs",
            tour_id,
            item=item,
            condition_expression="attribute_not_exists(occurrenceId) AND attribute_not_exists(recordId)",
        )
    except ClientError:
        return internal_error_response("Failed to create activity record")
    return success_response(item, status_code=201)


def cancel_activity_record(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    occurrence_id = params.get("occurrenceId")
    record_id = params.get("recordId")
    if not tour_id or not event_id or not occurrence_id or not record_id:
        return bad_request_response("tourId, eventId, occurrenceId and recordId are required in path")
    record = get_tour_item("EventActivityLogs", tour_id, {"occurrenceId": occurrence_id, "recordId": record_id})
    if not record:
        return error_response("RECORD_NOT_FOUND", "Record not found.", status_code=404)
    if record.get("cancelledAt"):
        return error_response("RECORD_ALREADY_CANCELLED", "Record is already cancelled.", status_code=409)
    body, err = parse_body(event)
    if err:
        return err
    record["cancelledAt"] = utc_now_iso()
    record["cancelledBy"] = get_claim(event, "sub")
    record["cancelReason"] = (body or {}).get("cancelReason")
    put_tour_item("EventActivityLogs", tour_id, record, condition_expression="attribute_exists(occurrenceId)")
    return success_response(record)


def get_dashboard(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    occurrence_id = params.get("occurrenceId")
    occurrence = _get_occurrence(tour_id, event_id, occurrence_id)
    event_definition = _get_event_definition(tour_id, event_id)
    if not occurrence:
        return error_response("OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404)
    records = _scan_records_for_occurrence(tour_id, occurrence_id)
    non_cancelled = _non_cancelled_records(records)
    riders = scan_tour_items("TourRider", tour_id)
    items = []
    for rider in riders:
        rider_status = []
        for activity in event_definition.get("activities", []):
            status = "PENDING"
            for record in non_cancelled:
                if record.get("riderId") == rider.get("riderId") and record.get("activityId") == activity.get("activityId"):
                    status = record.get("outcome") or "COMPLETED"
                    break
            rider_status.append({"activityId": activity.get("activityId"), "status": status})
        items.append({"riderId": rider.get("riderId"), "activities": rider_status})
    return success_response(
        {
            "occurrence": occurrence,
            "riders": items,
            "cancelled": [record for record in records if record.get("cancelledAt")],
        }
    )


def get_dashboard_progress(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    occurrence_id = params.get("occurrenceId")
    occurrence = _get_occurrence(tour_id, event_id, occurrence_id)
    event_definition = _get_event_definition(tour_id, event_id)
    if not occurrence:
        return error_response("OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404)
    riders = scan_tour_items("TourRider", tour_id)
    records = _non_cancelled_records(_scan_records_for_occurrence(tour_id, occurrence_id))
    mandatory_count = _count_outstanding_mandatory(tour_id, event_id, occurrence)
    return success_response(
        {
            "totalRiders": len(riders),
            "completedCount": len([record for record in records if record.get("outcome") == EventRecordOutcome.COMPLETED.value]),
            "outstandingMandatoryCount": mandatory_count,
            "optedOutCount": len([record for record in records if record.get("outcome") == EventRecordOutcome.OPTED_OUT.value]),
            "flaggedCount": len([record for record in records if record.get("isFlagged")]),
        }
    )


def get_rider_progress(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}
    tour_id = params.get("tourId")
    rider_id = params.get("riderId")
    if not tour_id or not rider_id:
        return bad_request_response("tourId and riderId are required in path")
    try:
        validate_tour_id(tour_id)
        validate_rider_id(rider_id)
    except ValidationError as exc:
        return bad_request_response(exc.message, exc.details)
    items = query_tour_items(
        "EventActivityLogs",
        tour_id,
        key_condition_expression="riderId = :riderId",
        expression_values={":riderId": rider_id},
        index_name="RiderTimestampIndex",
    )
    event_filter = query_params.get("eventId")
    if event_filter:
        items = [item for item in items if item.get("eventId") == event_filter]
    progress_items = [
        {
            "eventId": item.get("eventId"),
            "occurrenceId": item.get("occurrenceId"),
            "activityId": item.get("activityId"),
            "status": item.get("outcome"),
        }
        for item in items
        if not item.get("cancelledAt")
    ]
    return success_response({"items": progress_items})


def get_reconciliation(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    event_id = params.get("eventId")
    occurrence_id = params.get("occurrenceId")
    occurrence = _get_occurrence(tour_id, event_id, occurrence_id)
    if not occurrence:
        return error_response("OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404)
    linked_occurrence_ref = occurrence.get("linkedOccurrenceRef")
    if not linked_occurrence_ref:
        return error_response("NO_LINKED_OCCURRENCE", "Occurrence does not have a linked occurrence.", status_code=400)

    linked_event_id = linked_occurrence_ref.split("#", 1)[0]
    linked_occurrence = _get_occurrence(tour_id, linked_event_id, linked_occurrence_ref)
    if not linked_occurrence:
        return error_response("OCCURRENCE_NOT_FOUND", "Occurrence not found.", status_code=404)

    loaded_records = _non_cancelled_records(_scan_records_for_occurrence(tour_id, occurrence_id))
    unloaded_records = _non_cancelled_records(_scan_records_for_occurrence(tour_id, linked_occurrence_ref))
    loaded_pairs = {(record.get("riderId"), record.get("typeCode")) for record in loaded_records}
    unloaded_pairs = {(record.get("riderId"), record.get("typeCode")) for record in unloaded_records}
    missing_rider_ids = sorted({rider_id for rider_id, _ in loaded_pairs - unloaded_pairs})
    return success_response(
        {
            "loadedCount": len(loaded_pairs),
            "unloadedCount": len(unloaded_pairs),
            "missingRiderIds": missing_rider_ids,
        }
    )


def get_bootstrap(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    if not tour_id:
        return bad_request_response("tourId is required in path")
    try:
        validate_tour_id(tour_id)
    except ValidationError as exc:
        return bad_request_response(exc.message, exc.details)

    today = utc_today_iso()
    events = scan_tour_items("Event", tour_id)
    occurrences = scan_tour_items("EventOccurrence", tour_id)
    filtered_occurrences = [
        occurrence for occurrence in occurrences
        if occurrence.get("status") in {EventOccurrenceStatus.ACTIVE.value, EventOccurrenceStatus.PLANNED.value}
        and occurrence.get("date", "") >= today
    ]
    rider_baggage_status = [
        {
            "riderId": rider.get("riderId"),
            "baggageStatus": rider.get("baggageStatus", BaggageStatus.ACTIVE.value),
            "baggageReleasedAt": rider.get("baggageReleasedAt"),
        }
        for rider in scan_tour_items("TourRider", tour_id)
    ]
    hotel_stays_today = query_tour_items(
        "RoomAllocation",
        tour_id,
        key_condition_expression="stayDate = :stayDate",
        expression_values={":stayDate": today},
    )
    payload = {
        "events": sorted(events, key=lambda item: item.get("eventId", "")),
        "activeOccurrences": sorted(filtered_occurrences, key=lambda item: item.get("dateSeq", "")),
        "riderBaggageStatus": rider_baggage_status,
        "hotelStaysToday": hotel_stays_today,
    }
    etag = _event_etag(payload)
    request_etag = (event.get("headers") or {}).get("if-none-match")
    if request_etag == etag:
        return not_modified_response()
    response = success_response(payload)
    response["headers"]["ETag"] = etag
    return response


def list_hotels(event: Dict[str, Any]) -> Dict[str, Any]:
    tour_id = (event.get("pathParameters") or {}).get("tourId")
    if not tour_id:
        return bad_request_response("tourId is required in path")
    items = [
        item for item in scan_tour_items("Hotel", tour_id)
        if str(item.get("hotelId", "")).startswith("HTL-")
    ]
    return success_response({"items": sorted(items, key=lambda item: item.get("hotelId", ""))})


def create_hotel(event: Dict[str, Any]) -> Dict[str, Any]:
    tour_id = (event.get("pathParameters") or {}).get("tourId")
    body, err = parse_body(event)
    if err:
        return err
    try:
        validate_required_fields(body, ["hotelId", "name", "city", "address"])
        validate_tour_id(tour_id)
        validate_hotel_id(body["hotelId"])
    except ValidationError as exc:
        return error_response("VALIDATION_ERROR", exc.message, status_code=400, details=exc.details)
    item = Hotel(
        hotelId=body["hotelId"],
        name=body["name"],
        city=body["city"],
        address=body["address"],
        contact=body.get("contact"),
        notes=body.get("notes"),
    ).to_dict()
    try:
        put_tour_item("Hotel", tour_id, item, condition_expression="attribute_not_exists(hotelId)")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return error_response("HOTEL_ALREADY_EXISTS", "A hotel with this ID already exists.", status_code=409)
        return internal_error_response("Failed to create hotel")
    return success_response(item, status_code=201)


def update_hotel(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    hotel_id = params.get("hotelId")
    body, err = parse_body(event)
    if err:
        return err
    item = get_tour_item("Hotel", tour_id, {"hotelId": hotel_id})
    if not item:
        return error_response("HOTEL_NOT_FOUND", "Hotel not found.", status_code=404)
    for field in ("name", "city", "address", "contact", "notes"):
        if field in body:
            item[field] = body.get(field)
    item["updatedAt"] = utc_now_iso()
    put_tour_item("Hotel", tour_id, item, condition_expression="attribute_exists(hotelId)")
    return success_response(item)


def get_hotel_stays(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}
    tour_id = params.get("tourId")
    rider_id = params.get("riderId")
    hotel_id = params.get("hotelId")
    date = query_params.get("date") or params.get("stayDate")
    try:
        validate_tour_id(tour_id)
        if rider_id:
            validate_rider_id(rider_id)
        if hotel_id:
            validate_hotel_id(hotel_id)
        if date:
            validate_iso_date(date, "date")
    except ValidationError as exc:
        return bad_request_response(exc.message, exc.details)

    if rider_id:
        items = query_tour_items(
            "RoomAllocation",
            tour_id,
            key_condition_expression="riderId = :riderId",
            expression_values={":riderId": rider_id},
            index_name="RiderIdIndex",
        )
    elif hotel_id:
        if not get_tour_item("Hotel", tour_id, {"hotelId": hotel_id}):
            return error_response("HOTEL_NOT_FOUND", "Hotel not found.", status_code=404)
        items = query_tour_items(
            "RoomAllocation",
            tour_id,
            key_condition_expression="hotelId = :hotelId",
            expression_values={":hotelId": hotel_id},
            index_name="HotelDateIndex",
        )
        if date:
            items = [item for item in items if item.get("stayDate") == date]
        items = sorted(items, key=lambda item: (item.get("roomNo", ""), item.get("riderId", "")))
    else:
        if not date:
            return error_response("VALIDATION_ERROR", "date query parameter is required", status_code=400)
        items = query_tour_items(
            "RoomAllocation",
            tour_id,
            key_condition_expression="stayDate = :stayDate",
            expression_values={":stayDate": date},
        )
    return success_response({"items": items})


def _validate_room_allocation_group(
    tour_id: str,
    stay_date: str,
    rider_id: str,
    hotel_id: str,
    room_no: str,
    room_capacity: int,
    sharing_with: List[str],
) -> Optional[Dict[str, Any]]:
    existing_same_date = query_tour_items(
        "RoomAllocation",
        tour_id,
        key_condition_expression="stayDate = :stayDate",
        expression_values={":stayDate": stay_date},
    )
    room_occupants = [
        item for item in existing_same_date
        if item.get("hotelId") == hotel_id and item.get("roomNo") == room_no and item.get("riderId") != rider_id
    ]
    expected_group = set([rider_id, *sharing_with])
    for occupant in room_occupants:
        occupant_rider_id = occupant.get("riderId")
        if occupant_rider_id not in expected_group:
            return error_response(
                "ROOM_CLASH",
                f"Room {room_no} is already allocated to another rider on this date.",
                status_code=409,
            )
        if occupant.get("roomCapacity", 2) != room_capacity or occupant.get("hotelId") != hotel_id or occupant.get("roomNo") != room_no:
            return error_response(
                "NON_RECIPROCAL_SHARING",
                "The paired rider's record does not confirm this room sharing.",
                status_code=409,
            )
        reciprocal = set(occupant.get("sharingWith") or [])
        if rider_id not in reciprocal:
            return error_response(
                "NON_RECIPROCAL_SHARING",
                "The paired rider's record does not confirm this room sharing.",
                status_code=409,
            )
    if len(expected_group) > room_capacity:
        return error_response(
            "ROOM_CAPACITY_EXCEEDED",
            f"Room {room_no} cannot hold more than {room_capacity} riders on this date.",
            status_code=409,
        )
    for paired_rider_id in sharing_with:
        paired = get_tour_item("RoomAllocation", tour_id, {"stayDate": stay_date, "riderId": paired_rider_id})
        if paired and (
            paired.get("hotelId") != hotel_id
            or paired.get("roomNo") != room_no
            or paired.get("roomCapacity", 2) != room_capacity
            or rider_id not in (paired.get("sharingWith") or [])
        ):
            return error_response(
                "NON_RECIPROCAL_SHARING",
                "The paired rider's record does not confirm this room sharing.",
                status_code=409,
            )
    return None


def upsert_hotel_stay(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    stay_date = params.get("stayDate")
    rider_id = params.get("riderId")
    body, err = parse_body(event)
    if err:
        return err
    try:
        validate_tour_id(tour_id)
        validate_iso_date(stay_date, "stayDate")
        validate_rider_id(rider_id)
        validate_required_fields(body, ["hotelId", "roomNo"])
        validate_hotel_id(body["hotelId"])
        validate_sharing_with(body.get("sharingWith", []))
    except ValidationError as exc:
        return error_response("VALIDATION_ERROR", exc.message, status_code=400, details=exc.details)
    if not get_tour_item("TourRider", tour_id, {"riderId": rider_id}):
        return error_response("RIDER_NOT_FOUND", "Rider not found.", status_code=404)
    if not get_tour_item("Hotel", tour_id, {"hotelId": body["hotelId"]}):
        return error_response("HOTEL_NOT_FOUND", "Hotel not found.", status_code=404)
    room_capacity = int(body.get("roomCapacity", 2))
    if room_capacity not in {2, 3}:
        return error_response("VALIDATION_ERROR", "roomCapacity must be 2 or 3", status_code=400)
    sharing_with = body.get("sharingWith") or []
    conflict = _validate_room_allocation_group(
        tour_id,
        stay_date,
        rider_id,
        body["hotelId"],
        body["roomNo"],
        room_capacity,
        sharing_with,
    )
    if conflict:
        return conflict
    now = utc_now_iso()
    item = RoomAllocation(
        stayDate=stay_date,
        riderId=rider_id,
        hotelId=body["hotelId"],
        roomNo=body["roomNo"],
        roomCapacity=room_capacity,
        sharingWith=sharing_with,
        source="MANUAL",
        checkInDate=body.get("checkInDate"),
        checkOutDate=body.get("checkOutDate"),
        updatedBy=get_claim(event, "sub"),
        createdAt=now,
        updatedAt=now,
    ).to_dict()
    existing = get_tour_item("RoomAllocation", tour_id, {"stayDate": stay_date, "riderId": rider_id})
    if existing:
        item["createdAt"] = existing.get("createdAt", now)
    put_tour_item("RoomAllocation", tour_id, item)
    return success_response(item)


def _next_upload_id() -> str:
    return f"UPL-{uuid.uuid4().int % 1000000000000:012d}"


def presign_hotel_upload(event: Dict[str, Any]) -> Dict[str, Any]:
    tour_id = (event.get("pathParameters") or {}).get("tourId")
    if not tour_id:
        return bad_request_response("tourId is required in path")
    bucket_name = os.environ.get("ARTIFACTS_BUCKET")
    if not bucket_name:
        return internal_error_response("Artifacts bucket not configured")
    status_item = None
    upload_id = None
    s3_key = None
    for _ in range(10):
        upload_id = _next_upload_id()
        s3_key = f"tours/{tour_id}/uploads/hotel-allocation/{upload_id}.csv"
        now = utc_now_iso()
        status_item = {
            "hotelId": f"UPLOAD#{upload_id}",
            "entityType": "UPLOAD_STATUS",
            "uploadId": upload_id,
            "status": "PENDING",
            "rowCount": 0,
            "errorCount": 0,
            "errors": [],
            "appliedCount": 0,
            "processedAt": None,
            "s3Key": s3_key,
            "createdAt": now,
            "updatedAt": now,
        }
        try:
            put_tour_item(
                "Hotel",
                tour_id,
                status_item,
                condition_expression="attribute_not_exists(hotelId)",
            )
            break
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            status_item = None
    else:
        return internal_error_response("Unable to allocate upload identifier")

    presigned_url = s3_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket_name, "Key": s3_key, "ContentType": "text/csv"},
        ExpiresIn=900,
    )
    return success_response(
        {
            "uploadId": upload_id,
            "uploadUrl": presigned_url,
            "s3Key": s3_key,
            "expiresIn": 900,
        }
    )


def get_hotel_upload_status(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    upload_id = params.get("uploadId")
    try:
        validate_upload_id(upload_id)
    except ValidationError as exc:
        return bad_request_response(exc.message, exc.details)
    item = get_tour_item("Hotel", tour_id, {"hotelId": f"UPLOAD#{upload_id}"})
    if not item:
        return error_response("UPLOAD_NOT_FOUND", "Upload not found.", status_code=404)
    return success_response(
        {
            "uploadId": item.get("uploadId"),
            "status": item.get("status"),
            "rowCount": item.get("rowCount", 0),
            "errorCount": item.get("errorCount", 0),
            "errors": item.get("errors", []),
            "appliedCount": item.get("appliedCount", 0),
            "processedAt": item.get("processedAt"),
        }
    )


def _validate_user_role(role: str) -> None:
    valid_roles = [member.value for member in UserRole]
    if role not in valid_roles and not re.fullmatch(r"PS_\d+_USER", role or ""):
        raise ValidationError(
            f"Invalid role. Must be one of: {', '.join(valid_roles)} or PS_<n>_USER",
            {"field": "role", "value": role},
        )


def _get_managed_cognito_user(user_id: str) -> Optional[Dict[str, Any]]:
    """Look up a managed Cognito user by sub. Fails closed: raises if the pool
    is not configured or the lookup itself fails, rather than assuming validity."""
    user_pool_id = os.environ.get("MGMT_USER_POOL_ID")
    if not user_pool_id:
        raise RuntimeError("MGMT_USER_POOL_ID is not configured")
    response = cognito_client.list_users(
        UserPoolId=user_pool_id,
        Filter=f'sub = "{user_id}"',
        Limit=1,
    )
    users = response.get("Users", [])
    return users[0] if users else None


def _validate_event_assignments(tour_id: str, event_assignments: Any) -> None:
    if event_assignments is None:
        return
    if not isinstance(event_assignments, list):
        raise ValidationError("eventAssignments must be a list", {"field": "eventAssignments"})
    for assignment in event_assignments:
        if not isinstance(assignment, dict):
            raise ValidationError("eventAssignments entries must be objects", {"field": "eventAssignments"})
        validate_event_id(assignment.get("eventId"))
        if not _get_event_definition(tour_id, assignment.get("eventId")):
            raise ValidationError(
                "One or more eventAssignments reference an event that does not exist.",
                {"field": "eventAssignments", "value": assignment.get("eventId")},
            )
        dates = assignment.get("dates")
        if dates != "ALL":
            if not isinstance(dates, list):
                raise ValidationError("eventAssignments.dates must be a list or ALL", {"field": "eventAssignments"})
            for date in dates:
                validate_iso_date(date, "dates")


def create_tour_user(event: Dict[str, Any]) -> Dict[str, Any]:
    tour_id = (event.get("pathParameters") or {}).get("tourId")
    body, err = parse_body(event)
    if err:
        return err
    try:
        validate_required_fields(body, ["userId", "role"])
        validate_cognito_user_id(body["userId"])
        _validate_user_role(body["role"])
        _validate_event_assignments(tour_id, body.get("eventAssignments"))
        if body.get("hotelId"):
            validate_hotel_id(body["hotelId"])
            if not get_tour_item("Hotel", tour_id, {"hotelId": body["hotelId"]}):
                raise ValidationError(
                    "hotelId references a hotel that does not exist.",
                    {"field": "hotelId", "value": body["hotelId"]},
                )
    except ValidationError as exc:
        code = "INVALID_EVENT_ASSIGNMENT" if exc.details.get("field") == "eventAssignments" else "VALIDATION_ERROR"
        return error_response(code, exc.message, status_code=400, details=exc.details)

    try:
        cognito_user = _get_managed_cognito_user(body["userId"])
    except (RuntimeError, ClientError):
        return internal_error_response("Unable to verify managed user")
    if not cognito_user:
        return error_response("USER_NOT_FOUND", "Managed user not found.", status_code=404)

    # username/email/name are snapshotted from Cognito at assignment time (not
    # trusted from the request body), so the tour-scoped record stays accurate
    # even if the Cognito user pool is later modified or deleted.
    cognito_attrs = {attr.get("Name"): attr.get("Value") for attr in cognito_user.get("Attributes", [])}

    now = utc_now_iso()
    item = {
        "userId": body["userId"],
        "username": cognito_user.get("Username"),
        "email": cognito_attrs.get("email"),
        "name": cognito_attrs.get("name"),
        "role": body["role"],
        "status": body.get("status", "ACTIVE"),
        "assignedStage": body.get("assignedStage"),
        "hotelId": body.get("hotelId"),
        "eventAssignments": body.get("eventAssignments"),
        "assignedActivityIds": body.get("assignedActivityIds"),
        "createdAt": now,
        "createdBy": get_claim(event, "sub"),
        "updatedAt": now,
        "updatedBy": get_claim(event, "sub"),
    }
    try:
        put_tour_item("User", tour_id, item, condition_expression="attribute_not_exists(userId)")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return error_response("USER_ALREADY_EXISTS", "A user with this ID already exists.", status_code=409)
        return internal_error_response("Failed to create tour user")
    return success_response(item, status_code=201)


def update_tour_user(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("pathParameters") or {}
    tour_id = params.get("tourId")
    user_id = params.get("userId")
    body, err = parse_body(event)
    if err:
        return err
    item = get_tour_item("User", tour_id, {"userId": user_id})
    if not item:
        return error_response("USER_NOT_FOUND", "Managed user not found.", status_code=404)
    try:
        if "role" in body:
            _validate_user_role(body["role"])
        if "eventAssignments" in body:
            _validate_event_assignments(tour_id, body.get("eventAssignments"))
        if "hotelId" in body and body.get("hotelId") is not None:
            validate_hotel_id(body["hotelId"])
            if not get_tour_item("Hotel", tour_id, {"hotelId": body["hotelId"]}):
                raise ValidationError(
                    "hotelId references a hotel that does not exist.",
                    {"field": "hotelId", "value": body["hotelId"]},
                )
    except ValidationError as exc:
        code = "INVALID_EVENT_ASSIGNMENT" if exc.details.get("field") == "eventAssignments" else "VALIDATION_ERROR"
        return error_response(code, exc.message, status_code=400, details=exc.details)

    for field in ("username", "email", "name", "role", "status", "assignedStage", "hotelId", "eventAssignments", "assignedActivityIds"):
        if field in body:
            if body[field] is None:
                item.pop(field, None)
            else:
                item[field] = body[field]
    item["updatedAt"] = utc_now_iso()
    item["updatedBy"] = get_claim(event, "sub")
    put_tour_item("User", tour_id, item, condition_expression="attribute_exists(userId)")
    return success_response(item)


def get_current_tour_user(event: Dict[str, Any]) -> Dict[str, Any]:
    """Return the caller's own tour-scoped User-{tourId} record, keyed by their Cognito sub."""
    tour_id = (event.get("pathParameters") or {}).get("tourId")
    if not tour_id:
        return bad_request_response("tourId is required in path")
    try:
        validate_tour_id(tour_id)
    except ValidationError as exc:
        return bad_request_response(exc.message, exc.details)

    user_id = get_claim(event, "sub")
    if not user_id:
        return error_response("FORBIDDEN", "User identity missing.", status_code=403)

    item = get_tour_item("User", tour_id, {"userId": user_id})
    if not item:
        return error_response("USER_NOT_FOUND", "You are not assigned to this tour.", status_code=404)
    return success_response(item)
