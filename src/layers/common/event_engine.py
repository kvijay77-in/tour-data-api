"""Shared event engine, hotel, and tour-user helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import uuid
from datetime import date as calendar_date, timedelta
from decimal import Decimal
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

from dynamodb_utils import (
    get_item,
    get_tour_item,
    get_tour_table,
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
    HotelUploadStatus,
    RoomAllocation,
    TourRiderStatus,
    UserRole,
    utc_now_iso,
    utc_today_iso,
)
from event_permissions import effective_event_self_service_allowed
from ownership import is_rider_api_request, resolve_profile_id_for_sub
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
from logger import get_logger
from notification_service import notify


logger = get_logger(__name__)
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


def _rider_id_for_request(event: Dict[str, Any], tour_id: str) -> Optional[str]:
    profile_id = resolve_profile_id_for_sub(get_claim(event, "sub"))
    riders = query_tour_items(
        "TourRider",
        tour_id,
        key_condition_expression="profileId = :profileId",
        expression_values={":profileId": profile_id},
        index_name="ProfileIdIndex",
    ) if profile_id else []
    return riders[0].get("riderId") if riders else None


def _event_occurrence_registration_status(
    tour_id: str,
    event_definition: Dict[str, Any],
    occurrence_id: str,
    rider_id: str,
) -> str:
    if not event_definition.get("registrationEnabled", False):
        return "NOT_REQUIRED"
    registration = get_tour_item(
        "EventRegistration",
        tour_id,
        {"occurrenceId": occurrence_id, "riderId": rider_id},
    )
    return "REGISTERED" if registration else "NOT_REGISTERED"


def _effective_self_service_by_activity(
    event_definition: Dict[str, Any],
    occurrence: Dict[str, Any],
) -> Dict[str, bool]:
    return {
        activity.get("activityId"): effective_event_self_service_allowed(
            event_definition, occurrence, activity
        )
        for activity in event_definition.get("activities", []) or []
        if activity.get("activityId")
    }


def _occurrence_registrations(tour_id: str, occurrence_id: str) -> List[Dict[str, Any]]:
    return query_tour_items(
        "EventRegistration",
        tour_id,
        key_condition_expression="occurrenceId = :occurrenceId",
        expression_values={":occurrenceId": occurrence_id},
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
    item = get_tour_item("Event", tour_id, {"eventId": event_id})
    return _without_legacy_self_service(item) if item else item


def _get_occurrence(tour_id: str, event_id: str, occurrence_id: str) -> Optional[Dict[str, Any]]:
    parts = occurrence_id.split("#", 1)
    if len(parts) != 2:
        return None
    item = get_tour_item("EventOccurrence", tour_id, {"eventId": event_id, "dateSeq": parts[1]})
    return _without_legacy_self_service(item) if item else item


def _without_legacy_self_service(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Prevent legacy informational fields from being read or returned."""
    if item is None:
        return None
    clean = dict(item)
    clean.pop("allowSelfService", None)
    clean.pop("selfServiceEnabled", None)
    for activity in clean.get("activities", []) or []:
        activity.pop("selfServiceEnabled", None)
    for override in clean.get("activityOverrides", []) or []:
        override.pop("selfServiceEnabled", None)
    return clean


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
    if "selfServiceAllowed" in activity and activity["selfServiceAllowed"] is not None and not isinstance(activity["selfServiceAllowed"], bool):
        raise ValidationError("selfServiceAllowed must be a boolean or null", {"field": "selfServiceAllowed"})

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
        selfServiceAllowed=(
            activity.get("selfServiceAllowed")
            if isinstance(activity.get("selfServiceAllowed"), bool) else None
        ),
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


def _is_activity_skipped_by_organizer(occurrence: Dict[str, Any], activity_id: str) -> bool:
    for override in occurrence.get("activityOverrides", []) or []:
        if override.get("activityId") == activity_id and override.get("skipped") is True:
            return True
    return False


def _validate_notification_config(config: Dict[str, Any] | None) -> Dict[str, Any]:
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValidationError("notificationConfig must be an object", {"field": "notificationConfig"})
    validated = dict(config)
    bool_fields = ("completionNotifyEnabled", "reminderEnabled")
    for field in bool_fields:
        if field in validated and not isinstance(validated[field], bool):
            raise ValidationError(f"{field} must be boolean", {"field": f"notificationConfig.{field}"})
    for field in ("completionRuleId", "reminderRuleId"):
        if field in validated and validated[field] is not None and (
            not isinstance(validated[field], str) or not validated[field].strip()
        ):
            raise ValidationError(f"{field} must be a non-empty string", {"field": f"notificationConfig.{field}"})
    return validated


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
    items = sorted(
        (_without_legacy_self_service(item) for item in scan_tour_items("Event", tour_id)),
        key=lambda item: item.get("eventId", ""),
    )
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
        for field in ("registrationEnabled", "selfServiceAllowed"):
            if field in body and not isinstance(body[field], bool):
                raise ValidationError(f"{field} must be a boolean", {"field": field})
        _validate_allowed_type_codes_exist(body.get("defaultAllowedTypeCodes") or [])
        activities = _validate_activities(body["activities"])
        notification_config = _validate_notification_config(body.get("notificationConfig"))
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
        registrationEnabled=bool(body.get("registrationEnabled", False)),
        selfServiceAllowed=bool(body.get("selfServiceAllowed", False)),
        notificationConfig=notification_config or None,
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
        if "notificationConfig" in body:
            updated["notificationConfig"] = _validate_notification_config(body.get("notificationConfig")) or None
        for field in ("eventName", "location", "sequenceEnforced", "registrationEnabled", "selfServiceAllowed"):
            if field in body:
                if field in {"registrationEnabled", "selfServiceAllowed"} and not isinstance(body[field], bool):
                    raise ValidationError(f"{field} must be a boolean", {"field": field})
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
    return success_response({
        "items": sorted(
            (_without_legacy_self_service(item) for item in items),
            key=lambda item: item.get("dateSeq", ""),
        )
    })


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
        if "selfServiceAllowed" in body and body["selfServiceAllowed"] is not None and not isinstance(body["selfServiceAllowed"], bool):
            raise ValidationError("selfServiceAllowed must be a boolean or null", {"field": "selfServiceAllowed"})
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
        selfServiceAllowed=(
            body.get("selfServiceAllowed")
            if isinstance(body.get("selfServiceAllowed"), bool) else None
        ),
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
    if "selfServiceAllowed" in body:
        if body["selfServiceAllowed"] is not None and not isinstance(body["selfServiceAllowed"], bool):
            return error_response(
                "VALIDATION_ERROR",
                "selfServiceAllowed must be a boolean or null",
                status_code=400,
            )
        occurrence["selfServiceAllowed"] = (
            body["selfServiceAllowed"]
            if isinstance(body["selfServiceAllowed"], bool) else None
        )
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
        if "selfServiceAllowed" in body and body["selfServiceAllowed"] is not None and not isinstance(body["selfServiceAllowed"], bool):
            raise ValidationError("selfServiceAllowed must be a boolean or null", {"field": "selfServiceAllowed"})
        if "skipped" in body and not isinstance(body.get("skipped"), bool):
            raise ValidationError("skipped must be boolean", {"field": "skipped"})
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

    for field in ("enabled", "selfServiceAllowed", "allowedTypeCodes", "note", "skipped"):
        if field in body:
            matched[field] = body.get(field)
    matched["updatedAt"] = utc_now_iso()
    matched["updatedBy"] = get_claim(event, "sub")

    if (
        matched.get("enabled") is None
        and matched.get("selfServiceAllowed") is None
        and matched.get("allowedTypeCodes") is None
        and matched.get("skipped") is None
    ):
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


def _completion_activity_ids(event_definition: Dict[str, Any], occurrence: Dict[str, Any]) -> List[str]:
    required: List[str] = []
    for activity in event_definition.get("activities", []) or []:
        activity_id = activity.get("activityId")
        if not activity_id:
            continue
        if not _effective_activity_enabled(occurrence, activity):
            continue
        if _is_activity_skipped_by_organizer(occurrence, activity_id):
            continue
        required.append(activity_id)
    return required


def _rider_event_completion_reached(
    rider_id: str,
    event_definition: Dict[str, Any],
    occurrence: Dict[str, Any],
    records: List[Dict[str, Any]],
) -> bool:
    required_ids = _completion_activity_ids(event_definition, occurrence)
    if not required_ids:
        return False
    rider_completed = {
        record.get("activityId")
        for record in records
        if record.get("riderId") == rider_id
        and record.get("outcome") in {EventRecordOutcome.COMPLETED.value, EventRecordOutcome.OPTED_OUT.value}
    }
    return all(activity_id in rider_completed for activity_id in required_ids)


def create_activity_record(event: Dict[str, Any]) -> Dict[str, Any]:
    self_service = bool(event.get("_self_service"))
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

    if self_service and not effective_event_self_service_allowed(event_definition, occurrence, activity):
        return error_response("SELF_SERVICE_NOT_ALLOWED", "Self-service is not allowed for this activity.", status_code=403)

    if occurrence.get("status") != EventOccurrenceStatus.ACTIVE.value:
        return error_response("OCCURRENCE_NOT_ACTIVE", "Occurrence is not active.", status_code=409)

    if not self_service:
        access_denied = _check_event_scan_access(event, tour_id, event_definition, occurrence, activity, body["riderId"])
        if access_denied:
            return access_denied

    rider = get_tour_item("TourRider", tour_id, {"riderId": body["riderId"]})
    if not rider:
        return error_response("RIDER_NOT_FOUND", "Rider not found.", status_code=404)
    if rider.get("status") == TourRiderStatus.EXITED.value:
        return error_response("RIDER_EXITED", "Exited riders cannot participate in event activities.", status_code=403)

    if event_definition.get("registrationEnabled"):
        registration = get_tour_item(
            "EventRegistration",
            tour_id,
            {"occurrenceId": occurrence_id, "riderId": body["riderId"]},
        )
        if not registration:
            return error_response(
                "RIDER_NOT_REGISTERED_FOR_EVENT",
                "Rider is not registered for this event occurrence.",
                status_code=403,
            )

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
    requires_type_code = not self_service and body.get("outcome") != EventRecordOutcome.OPTED_OUT.value
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
    completion_before = _rider_event_completion_reached(body["riderId"], event_definition, occurrence, records)
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

    notification_config = event_definition.get("notificationConfig") or {}
    completion_after = _rider_event_completion_reached(body["riderId"], event_definition, occurrence, records + [item])
    if notification_config.get("completionNotifyEnabled") and not completion_before and completion_after:
        try:
            notify(
                rule_id=notification_config.get("completionRuleId") or "EVENT_COMPLETED_BY_RIDER",
                tour_id=tour_id,
                context={
                    "tourId": tour_id,
                    "eventId": event_id,
                    "eventName": event_definition.get("eventName"),
                    "occurrenceId": occurrence_id,
                    "riderId": body["riderId"],
                    "activityId": body["activityId"],
                    "timestamp": body["timestamp"],
                },
                audience_override=[f"TOUR#{tour_id}#RIDER#{body['riderId']}"],
                actor=scanned_by,
            )
        except Exception as notify_exc:  # pragma: no cover - safeguard only
            logger.warning("event completion notify trigger failed: %s", str(notify_exc))
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
    if event.get("_self_service"):
        from ownership import resolve_profile_id_for_sub
        profile_id = resolve_profile_id_for_sub(get_claim(event, "sub"))
        riders = query_tour_items(
            "TourRider", tour_id,
            "profileId = :profileId",
            {":profileId": profile_id},
            index_name="ProfileIdIndex",
        ) if profile_id else []
        if not riders or riders[0].get("riderId") != record.get("riderId"):
            return error_response("FORBIDDEN", "Riders may only cancel their own records.", status_code=403)
        definition = _get_event_definition(tour_id, event_id)
        occurrence = _get_occurrence(tour_id, event_id, occurrence_id)
        activity = _get_activity(definition or {}, record.get("activityId"))
        if not definition or not occurrence or not activity or not effective_event_self_service_allowed(definition, occurrence, activity):
            return error_response("SELF_SERVICE_NOT_ALLOWED", "Self-service is not allowed for this activity.", status_code=403)
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
    eligible_rider_ids = {
        rider.get("riderId")
        for rider in riders
        if rider.get("riderId") and rider.get("status") != TourRiderStatus.EXITED.value
    }
    registration_enabled = bool(event_definition.get("registrationEnabled", False))
    registered_ids = {
        item.get("riderId")
        for item in _occurrence_registrations(tour_id, occurrence_id)
    } & eligible_rider_ids if registration_enabled else eligible_rider_ids
    items = []
    for rider in riders:
        rider_status = []
        for activity in event_definition.get("activities", []):
            status = "PENDING"
            for record in non_cancelled:
                if record.get("riderId") == rider.get("riderId") and record.get("activityId") == activity.get("activityId"):
                    status = record.get("outcome") or "COMPLETED"
                    break
            rider_status.append({
                "activityId": activity.get("activityId"),
                "status": status,
                "selfServiceAllowed": effective_event_self_service_allowed(
                    event_definition, occurrence, activity
                ),
            })
        rider_id = rider.get("riderId")
        items.append({
            "riderId": rider_id,
            "registrationStatus": "REGISTERED" if rider_id in registered_ids else "NOT_REGISTERED",
            "activities": rider_status,
        })
    return success_response(
        {
            "occurrence": occurrence,
            "riders": items,
            "cancelled": [record for record in records if record.get("cancelledAt")],
            "summary": {
                "totalRiders": len(riders),
                "registrationEnabled": registration_enabled,
                "registeredCount": len(registered_ids),
                "notRegisteredCount": len(eligible_rider_ids) - len(registered_ids),
            },
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
    eligible_rider_ids = {
        rider.get("riderId")
        for rider in riders
        if rider.get("riderId") and rider.get("status") != TourRiderStatus.EXITED.value
    }
    registration_enabled = bool(event_definition.get("registrationEnabled", False))
    registered_ids = {
        item.get("riderId")
        for item in _occurrence_registrations(tour_id, occurrence_id)
    } & eligible_rider_ids if registration_enabled else eligible_rider_ids
    records = _non_cancelled_records(_scan_records_for_occurrence(tour_id, occurrence_id))
    mandatory_count = _count_outstanding_mandatory(tour_id, event_id, occurrence)
    return success_response(
        {
            "totalRiders": len(riders),
            "registrationEnabled": registration_enabled,
            "registeredCount": len(registered_ids),
            "notRegisteredCount": len(eligible_rider_ids) - len(registered_ids),
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
    if is_rider_api_request(event):
        caller_rider_id = _rider_id_for_request(event, tour_id)
        if not caller_rider_id:
            return error_response(
                "RIDER_PROFILE_NOT_LINKED",
                "Rider profile is not linked to this account.",
                status_code=403,
            )
        if caller_rider_id != rider_id:
            return error_response(
                "PROFILE_ACCESS_DENIED",
                "Riders may only read their own event progress.",
                status_code=403,
            )
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

    events = scan_tour_items("Event", tour_id)
    if event_filter:
        events = [item for item in events if item.get("eventId") == event_filter]
    event_by_id = {item.get("eventId"): _without_legacy_self_service(item) for item in events}
    occurrences = scan_tour_items("EventOccurrence", tour_id)
    occurrence_progress = []
    records_by_occurrence_activity = {
        (item.get("occurrenceId"), item.get("activityId")): item
        for item in items
        if not item.get("cancelledAt")
    }
    for occurrence in occurrences:
        event_definition = event_by_id.get(occurrence.get("eventId"))
        if not event_definition:
            continue
        if event_filter and occurrence.get("eventId") != event_filter:
            continue
        activities = []
        for activity in event_definition.get("activities", []) or []:
            record = records_by_occurrence_activity.get(
                (occurrence.get("occurrenceId"), activity.get("activityId"))
            )
            activities.append({
                "activityId": activity.get("activityId"),
                "status": (record or {}).get("outcome", "PENDING"),
                "selfServiceAllowed": effective_event_self_service_allowed(
                    event_definition, occurrence, activity
                ),
            })
        occurrence_progress.append({
            "eventId": event_definition.get("eventId"),
            "occurrenceId": occurrence.get("occurrenceId"),
            "registrationStatus": _event_occurrence_registration_status(
                tour_id, event_definition, occurrence.get("occurrenceId"), rider_id
            ),
            "activities": activities,
        })
    return success_response({"items": progress_items, "occurrences": occurrence_progress})


def _final_activity_id(tour_id: str, event_id: str, occurrence: Dict[str, Any]) -> Optional[str]:
    event_definition = _get_event_definition(tour_id, event_id) or {}
    enabled_activities = [
        activity for activity in event_definition.get("activities", [])
        if _effective_activity_enabled(occurrence, activity)
    ]
    if not enabled_activities:
        return None
    return max(enabled_activities, key=lambda activity: activity.get("sequenceNo", 0)).get("activityId")


def _reconciliation_bag_pairs(tour_id: str, event_id: str, occurrence: Dict[str, Any]) -> set:
    """Distinct (riderId, typeCode) bags scanned at the occurrence's final enabled activity."""
    final_activity_id = _final_activity_id(tour_id, event_id, occurrence)
    if not final_activity_id:
        return set()
    records = _non_cancelled_records(_scan_records_for_occurrence(tour_id, occurrence["occurrenceId"]))
    return {
        (record.get("riderId"), record.get("typeCode"))
        for record in records
        if record.get("activityId") == final_activity_id
        and record.get("typeCode")
        and record.get("outcome") != EventRecordOutcome.OPTED_OUT.value
    }


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

    loaded_pairs = _reconciliation_bag_pairs(tour_id, event_id, occurrence)
    unloaded_pairs = _reconciliation_bag_pairs(tour_id, linked_event_id, linked_occurrence)
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
    rider_id = None
    if is_rider_api_request(event):
        rider_id = _rider_id_for_request(event, tour_id)
        if not rider_id:
            return error_response(
                "RIDER_PROFILE_NOT_LINKED",
                "Rider profile is not linked to this account.",
                status_code=403,
            )
    events = [
        _without_legacy_self_service(item)
        for item in scan_tour_items("Event", tour_id)
    ]
    event_by_id = {item.get("eventId"): item for item in events}
    occurrences = scan_tour_items("EventOccurrence", tour_id)
    filtered_occurrences = [
        occurrence for occurrence in occurrences
        if occurrence.get("status") in {EventOccurrenceStatus.ACTIVE.value, EventOccurrenceStatus.PLANNED.value}
        and occurrence.get("date", "") >= today
    ]
    for occurrence in filtered_occurrences:
        event_definition = event_by_id.get(occurrence.get("eventId"))
        if not event_definition:
            continue
        occurrence = _without_legacy_self_service(occurrence)
        occurrence["registrationEnabled"] = bool(
            event_definition.get("registrationEnabled", False)
        )
        occurrence["effectiveSelfServiceByActivity"] = (
            _effective_self_service_by_activity(event_definition, occurrence)
        )
        if rider_id:
            occurrence["registrationStatus"] = _event_occurrence_registration_status(
                tour_id,
                event_definition,
                occurrence.get("occurrenceId"),
                rider_id,
            )
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
            "status": HotelUploadStatus.PENDING.value,
            "rowCount": 0,
            "errorCount": 0,
            "errors": [],
            "appliedCount": 0,
            "processedAt": None,
            "s3Key": s3_key,
            "createdBy": get_claim(event, "sub") or None,
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


# ---------------------------------------------------------------------------
# Hotel allocation CSV processor (S3 -> EventBridge -> Lambda), §8.22a/§8.22b
# ---------------------------------------------------------------------------

HOTEL_UPLOAD_KEY_PATTERN = re.compile(
    r"^tours/(?P<tourId>[a-zA-Z0-9][a-zA-Z0-9_.\-]{2,49})/uploads/hotel-allocation/(?P<uploadId>UPL-\d{6,12})\.csv$"
)
HOTEL_UPLOAD_CONFIG_DEFAULTS: Dict[str, int] = {
    "maxFileSizeBytes": 1048576,
    "maxDataRows": 500,
    "maxStayDates": 31,
    "maxStoredErrors": 200,
    "timeReserveSeconds": 20,
}
HOTEL_UPLOAD_COLUMNS = {
    "riderid": "riderId",
    "hotelid": "hotelId",
    "roomno": "roomNo",
    "roomcapacity": "roomCapacity",
    "sharingwith": "sharingWith",
}
HOTEL_UPLOAD_DIRECTIVES = {
    "staydates": "stayDates",
    "startdate": "startDate",
    "nights": "nights",
    "hotelid": "hotelId",
}
HOTEL_UPLOAD_DIRECTIVE_PATTERN = re.compile(r"^#\s*([A-Za-z]+)\s*=\s*(.*)$")
ROOM_NO_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/\-]{0,9}$")
TRANSACT_MAX_ITEMS = 100
INELIGIBLE_RIDER_STATUSES = {TourRiderStatus.WITHDRAWN.value, TourRiderStatus.EXITED.value}
FILE_LEVEL_ROW = 0
NOTHING_CHANGED = "No allocations were changed"


class HotelUploadDeadline(Exception):
    """Remaining Lambda time dropped below the configured reserve."""


class HotelUploadRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _upload_error(row: int, code: str, message: str) -> Dict[str, Any]:
    return {"row": row, "code": code, "message": message}


def _clip(value: Any, limit: int = 40) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}..."


def _passes(validator, value: Any) -> bool:
    try:
        validator(value)
    except (ValidationError, TypeError):
        return False
    return True


def _get_hotel_upload_config() -> Dict[str, int]:
    config = dict(HOTEL_UPLOAD_CONFIG_DEFAULTS)
    try:
        item = get_item("APP_CONFIG_TABLE", {"configType": "HOTEL_UPLOAD", "configId": "PROCESSING"})
    except (ClientError, ValueError):
        logger.warning("HOTEL_UPLOAD/PROCESSING config unreadable; using defaults", exc_info=True)
        return config
    if not item or item.get("enabled") is not True:
        logger.warning("HOTEL_UPLOAD/PROCESSING config missing or disabled; using defaults")
        return config
    overrides = item.get("config") or {}
    for name in HOTEL_UPLOAD_CONFIG_DEFAULTS:
        if name not in overrides:
            continue
        try:
            value = int(overrides[name])
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            config[name] = value
        else:
            logger.warning("Invalid HOTEL_UPLOAD config %s=%r; using default", name, overrides[name])
    return config


def _ensure_time_remaining(context: Any, reserve_seconds: int) -> None:
    if context is not None and context.get_remaining_time_in_millis() < reserve_seconds * 1000:
        raise HotelUploadDeadline()


def _parse_hotel_upload_key(bucket: Optional[str], key: Optional[str]) -> Optional[Tuple[str, str, str]]:
    if not bucket or not key or bucket != os.environ.get("ARTIFACTS_BUCKET"):
        return None
    object_key = unquote_plus(key)
    match = HOTEL_UPLOAD_KEY_PATTERN.fullmatch(object_key)
    if not match:
        return None
    return match.group("tourId"), match.group("uploadId"), object_key


def _hotel_upload_snapshot_key(tour_id: str, upload_id: str) -> str:
    return f"tours/{tour_id}/uploads/hotel-allocation/{upload_id}.snapshot.json"


def _update_upload_status(tour_id: str, upload_id: str, fields: Dict[str, Any], expected_status: str) -> bool:
    """Conditionally SET fields on the upload status record; False if the status no longer matches."""
    names = {"#status": "status"}
    values: Dict[str, Any] = {":expected": expected_status}
    assignments = []
    for index, (name, value) in enumerate(fields.items()):
        names[f"#f{index}"] = name
        values[f":v{index}"] = value
        assignments.append(f"#f{index} = :v{index}")
    try:
        get_tour_table("Hotel", tour_id).update_item(
            Key={"hotelId": f"UPLOAD#{upload_id}"},
            UpdateExpression="SET " + ", ".join(assignments),
            ConditionExpression="#status = :expected",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def _reject_upload(
    tour_id: str,
    upload_id: str,
    errors: List[Dict[str, Any]],
    max_stored_errors: int,
    row_count: Optional[int] = None,
) -> Dict[str, Any]:
    unique: List[Dict[str, Any]] = []
    seen = set()
    for error in sorted(errors, key=lambda entry: entry["row"]):
        marker = (error["row"], error["code"], error["message"])
        if marker not in seen:
            seen.add(marker)
            unique.append(error)
    now = utc_now_iso()
    fields: Dict[str, Any] = {
        "status": HotelUploadStatus.REJECTED.value,
        "errorCount": len(unique),
        "errors": unique[:max_stored_errors],
        "appliedCount": 0,
        "processedAt": now,
        "updatedAt": now,
    }
    if row_count is not None:
        fields["rowCount"] = row_count
    _update_upload_status(tour_id, upload_id, fields, HotelUploadStatus.VALIDATING.value)
    logger.info("Hotel upload %s/%s rejected with %d error(s)", tour_id, upload_id, len(unique))
    return {"status": HotelUploadStatus.REJECTED.value, "tourId": tour_id, "uploadId": upload_id}


def _read_hotel_upload_file(bucket: str, key: str, max_bytes: int) -> Tuple[str, List[Dict[str, Any]]]:
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    size = int(obj.get("ContentLength", 0))
    if size > max_bytes:
        obj["Body"].close()
        return "", [_upload_error(FILE_LEVEL_ROW, "FILE_TOO_LARGE", f"File is {size} bytes; the maximum is {max_bytes} bytes.")]
    try:
        return obj["Body"].read().decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return "", [_upload_error(FILE_LEVEL_ROW, "INVALID_ENCODING", "File must be a UTF-8 encoded CSV.")]


def _parse_hotel_upload_header(cells: List[str], line_no: int) -> Tuple[List[str], List[Dict[str, Any]]]:
    columns: List[str] = []
    errors: List[Dict[str, Any]] = []
    for cell in cells:
        canonical = HOTEL_UPLOAD_COLUMNS.get(cell.lower())
        if not canonical:
            errors.append(_upload_error(line_no, "INVALID_HEADER", f"Unknown column '{_clip(cell)}'."))
        elif canonical in columns:
            errors.append(_upload_error(line_no, "INVALID_HEADER", f"Duplicate column '{canonical}'."))
        else:
            columns.append(canonical)
    for required in ("riderId", "roomNo"):
        if required not in columns:
            errors.append(_upload_error(line_no, "INVALID_HEADER", f"Missing required column '{required}'."))
    return columns, errors


def _parse_hotel_upload_csv(
    text: str,
) -> Tuple[Dict[str, Tuple[int, str]], List[str], List[Tuple[int, List[str]]], List[Dict[str, Any]]]:
    """Split the file into directives, header columns and data rows, keeping physical line numbers."""
    directives: Dict[str, Tuple[int, str]] = {}
    columns: Optional[List[str]] = None
    rows: List[Tuple[int, List[str]]] = []
    errors: List[Dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            match = HOTEL_UPLOAD_DIRECTIVE_PATTERN.match(stripped) if columns is None else None
            if match and match.group(1).lower() in HOTEL_UPLOAD_DIRECTIVES:
                directives[HOTEL_UPLOAD_DIRECTIVES[match.group(1).lower()]] = (line_no, match.group(2).strip())
            continue
        try:
            cells = [cell.strip() for cell in next(csv.reader([line]))]
        except csv.Error:
            errors.append(_upload_error(line_no, "MALFORMED_ROW", "Row could not be parsed as CSV."))
            continue
        if columns is None:
            columns, header_errors = _parse_hotel_upload_header(cells, line_no)
            if header_errors:
                errors.extend(header_errors)
                return directives, columns, rows, errors
            continue
        rows.append((line_no, cells))
    if columns is None:
        errors.append(_upload_error(FILE_LEVEL_ROW, "INVALID_HEADER", "Header row is missing."))
    return directives, columns or [], rows, errors


def _resolve_stay_dates(
    directives: Dict[str, Tuple[int, str]], max_stay_dates: int
) -> Tuple[List[str], List[Dict[str, Any]]]:
    stay_dates = directives.get("stayDates")
    start_date = directives.get("startDate")
    nights = directives.get("nights")
    errors: List[Dict[str, Any]] = []
    dates: List[str] = []
    if stay_dates and (start_date or nights):
        return [], [_upload_error(stay_dates[0], "INVALID_STAY_DATES", "Use either stayDates or startDate with nights, not both.")]
    if stay_dates:
        line_no, value = stay_dates
        for raw in value.split(","):
            stay_date = raw.strip()
            if not stay_date:
                continue
            if not _passes(validate_iso_date, stay_date):
                errors.append(_upload_error(line_no, "INVALID_STAY_DATES", f"Invalid stay date '{_clip(stay_date)}'. Expected YYYY-MM-DD."))
            elif stay_date not in dates:
                dates.append(stay_date)
    elif start_date or nights:
        if not (start_date and nights):
            line_no = (start_date or nights)[0]
            return [], [_upload_error(line_no, "INVALID_STAY_DATES", "startDate and nights must be provided together.")]
        if not _passes(validate_iso_date, start_date[1]):
            errors.append(_upload_error(start_date[0], "INVALID_STAY_DATES", f"Invalid startDate '{_clip(start_date[1])}'. Expected YYYY-MM-DD."))
        if not nights[1].isdigit() or int(nights[1]) < 1:
            errors.append(_upload_error(nights[0], "INVALID_STAY_DATES", "nights must be a positive whole number."))
        if not errors:
            first = calendar_date.fromisoformat(start_date[1])
            count = min(int(nights[1]), max_stay_dates + 1)
            dates = [(first + timedelta(days=offset)).isoformat() for offset in range(count)]
    else:
        return [], [_upload_error(
            FILE_LEVEL_ROW,
            "MISSING_STAY_DATES",
            "Add '# stayDates=YYYY-MM-DD,...' or '# startDate=YYYY-MM-DD' with '# nights=N' before the header row.",
        )]
    if not errors and not dates:
        errors.append(_upload_error((stay_dates or (FILE_LEVEL_ROW,))[0], "MISSING_STAY_DATES", "stayDates does not contain any dates."))
    if len(dates) > max_stay_dates:
        errors.append(_upload_error(FILE_LEVEL_ROW, "TOO_MANY_STAY_DATES", f"A file can cover at most {max_stay_dates} stay dates."))
    return sorted(dates), errors


def _validate_hotel_upload_rows(
    rows: List[Tuple[int, List[str]]],
    columns: List[str],
    directives: Dict[str, Tuple[int, str]],
    riders: Dict[str, Dict[str, Any]],
    hotel_ids: set,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Phase 1: per-row structural and reference checks; every failing row is reported."""
    errors: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    default_hotel = None
    if "hotelId" in directives:
        line_no, default_hotel = directives["hotelId"]
        if not _passes(validate_hotel_id, default_hotel):
            errors.append(_upload_error(line_no, "INVALID_HOTEL_ID", f"Invalid default hotelId '{_clip(default_hotel)}'."))
        elif default_hotel not in hotel_ids:
            errors.append(_upload_error(line_no, "UNKNOWN_HOTEL_ID", f"Default hotel {default_hotel} does not exist in this tour."))

    for line_no, cells in rows:
        if len(cells) > len(columns):
            errors.append(_upload_error(line_no, "MALFORMED_ROW", f"Row has {len(cells)} values but the header has {len(columns)} columns."))
            continue
        values = dict(zip(columns, cells + [""] * (len(columns) - len(cells))))

        rider_id = values.get("riderId", "")
        if not rider_id:
            errors.append(_upload_error(line_no, "MISSING_RIDER_ID", "riderId is required."))
        elif not _passes(validate_rider_id, rider_id):
            errors.append(_upload_error(line_no, "INVALID_RIDER_ID", f"Invalid riderId '{_clip(rider_id)}'."))
        elif rider_id not in riders:
            errors.append(_upload_error(line_no, "UNKNOWN_RIDER_ID", f"Rider {rider_id} is not registered for this tour."))
        elif riders[rider_id].get("status") in INELIGIBLE_RIDER_STATUSES:
            errors.append(_upload_error(line_no, "RIDER_NOT_ELIGIBLE", f"Rider {rider_id} is {riders[rider_id].get('status')} and cannot be allocated."))

        row_hotel = values.get("hotelId", "")
        hotel_id = row_hotel or default_hotel
        if not hotel_id:
            errors.append(_upload_error(line_no, "MISSING_HOTEL_ID", "hotelId is required when no default '# hotelId=' is set."))
        elif row_hotel and not _passes(validate_hotel_id, row_hotel):
            errors.append(_upload_error(line_no, "INVALID_HOTEL_ID", f"Invalid hotelId '{_clip(row_hotel)}'."))
        elif row_hotel and row_hotel not in hotel_ids:
            errors.append(_upload_error(line_no, "UNKNOWN_HOTEL_ID", f"Hotel {row_hotel} does not exist in this tour."))

        room_no = values.get("roomNo", "")
        if not room_no:
            errors.append(_upload_error(line_no, "MISSING_ROOM_NO", "roomNo is required."))
        elif not ROOM_NO_PATTERN.match(room_no):
            errors.append(_upload_error(line_no, "INVALID_ROOM_NO", f"Invalid roomNo '{_clip(room_no)}'."))

        raw_capacity = values.get("roomCapacity", "")
        capacity = int(raw_capacity) if raw_capacity.isdigit() else (2 if not raw_capacity else None)
        if capacity not in (2, 3):
            errors.append(_upload_error(line_no, "INVALID_ROOM_CAPACITY", "roomCapacity must be 2 or 3."))
            capacity = None

        sharing_with = [rider.strip() for rider in values.get("sharingWith", "").split(";") if rider.strip()]
        invalid_mates = [mate for mate in sharing_with if not _passes(validate_rider_id, mate)]
        if invalid_mates:
            errors.append(_upload_error(line_no, "INVALID_SHARING_WITH", f"Invalid rider ID(s) in sharingWith: {_clip(', '.join(invalid_mates))}."))
        elif rider_id in sharing_with:
            errors.append(_upload_error(line_no, "INVALID_SHARING_WITH", "A rider cannot share a room with themselves."))
        elif len(set(sharing_with)) != len(sharing_with):
            errors.append(_upload_error(line_no, "INVALID_SHARING_WITH", "sharingWith contains duplicate rider IDs."))
        elif capacity and len(sharing_with) > capacity - 1:
            errors.append(_upload_error(line_no, "ROOM_CAPACITY_EXCEEDED", f"A room of capacity {capacity} can have at most {capacity - 1} room-mate(s)."))

        records.append({
            "row": line_no,
            "riderId": rider_id,
            "hotelId": hotel_id,
            "roomNo": room_no,
            "roomCapacity": capacity,
            "sharingWith": sharing_with,
        })
    return records, errors


def _check_hotel_upload_room_rules(
    stay_date: str, merged: Dict[str, Dict[str, Any]], file_rows: Dict[str, int]
) -> List[Dict[str, Any]]:
    """Reciprocity, consistency, clash and capacity rules (§5.4) over file rows merged with existing data."""
    errors: List[Dict[str, Any]] = []
    rooms: Dict[Tuple[Any, Any], List[str]] = {}
    for rider_id, allocation in merged.items():
        rooms.setdefault((allocation.get("hotelId"), allocation.get("roomNo")), []).append(rider_id)

    def same_room(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
        return (
            first.get("hotelId") == second.get("hotelId")
            and first.get("roomNo") == second.get("roomNo")
            and int(first.get("roomCapacity", 2)) == int(second.get("roomCapacity", 2))
        )

    for rider_id, row in file_rows.items():
        allocation = merged[rider_id]
        capacity = int(allocation["roomCapacity"])
        where = f"room {allocation['roomNo']} at {allocation['hotelId']} on {stay_date}"
        for mate in allocation["sharingWith"]:
            mate_allocation = merged.get(mate)
            if not mate_allocation:
                errors.append(_upload_error(row, "NON_RECIPROCAL_SHARING", f"{mate} has no allocation on {stay_date}; add {mate} to {where}."))
            elif not same_room(allocation, mate_allocation):
                errors.append(_upload_error(
                    row,
                    "NON_RECIPROCAL_SHARING",
                    f"{mate} is in room {mate_allocation.get('roomNo')} at {mate_allocation.get('hotelId')} "
                    f"(capacity {int(mate_allocation.get('roomCapacity', 2))}) on {stay_date}, not {where} (capacity {capacity}).",
                ))
            elif rider_id not in (mate_allocation.get("sharingWith") or []):
                errors.append(_upload_error(row, "NON_RECIPROCAL_SHARING", f"{mate} does not list {rider_id} in sharingWith on {stay_date}."))
        occupants = rooms[(allocation["hotelId"], allocation["roomNo"])]
        for other in occupants:
            if other != rider_id and other not in allocation["sharingWith"]:
                errors.append(_upload_error(row, "ROOM_CLASH", f"{where[0].upper()}{where[1:]} is also allocated to {other}."))
        if len(occupants) > capacity:
            errors.append(_upload_error(row, "ROOM_CAPACITY_EXCEEDED", f"{len(occupants)} riders are allocated to {where}; capacity is {capacity}."))

    for rider_id, allocation in merged.items():
        if rider_id in file_rows:
            continue
        for mate in allocation.get("sharingWith") or []:
            if mate not in file_rows:
                continue
            mate_allocation = merged[mate]
            if not same_room(allocation, mate_allocation) or rider_id not in mate_allocation["sharingWith"]:
                errors.append(_upload_error(
                    file_rows[mate],
                    "NON_RECIPROCAL_SHARING",
                    f"{rider_id} still lists {mate} as a room-mate in room {allocation.get('roomNo')} at "
                    f"{allocation.get('hotelId')} on {stay_date}; include {rider_id} in the file or update that allocation first.",
                ))
    return errors


def _validate_hotel_upload_batch(
    tour_id: str, records: List[Dict[str, Any]], stay_dates: List[str], check_time
) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], List[Dict[str, Any]]]:
    """Phase 2: cross-row and existing-data checks; returns existing items keyed by (stayDate, riderId)."""
    errors: List[Dict[str, Any]] = []
    file_rows: Dict[str, int] = {}
    for record in records:
        first_row = file_rows.get(record["riderId"])
        if first_row is not None:
            errors.append(_upload_error(
                record["row"],
                "DUPLICATE_RIDER_FOR_DATE",
                f"Rider {record['riderId']} already appears on row {first_row}; a rider can have one allocation per stay date.",
            ))
        else:
            file_rows[record["riderId"]] = record["row"]
    if errors:
        return {}, errors

    existing: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for stay_date in stay_dates:
        check_time()
        items = query_tour_items(
            "RoomAllocation",
            tour_id,
            key_condition_expression="stayDate = :stayDate",
            expression_values={":stayDate": stay_date},
        )
        merged: Dict[str, Dict[str, Any]] = {}
        for item in items:
            existing[(stay_date, item["riderId"])] = item
            merged[item["riderId"]] = item
        for record in records:
            merged[record["riderId"]] = record
        errors.extend(_check_hotel_upload_room_rules(stay_date, merged, file_rows))
    return existing, errors


def _build_hotel_upload_items(
    records: List[Dict[str, Any]],
    stay_dates: List[str],
    existing: Dict[Tuple[str, str], Dict[str, Any]],
    upload_id: str,
    updated_by: Optional[str],
) -> List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
    now = utc_now_iso()
    entries = []
    for stay_date in stay_dates:
        for record in records:
            previous = existing.get((stay_date, record["riderId"]))
            item = RoomAllocation(
                stayDate=stay_date,
                riderId=record["riderId"],
                hotelId=record["hotelId"],
                roomNo=record["roomNo"],
                roomCapacity=record["roomCapacity"],
                sharingWith=record["sharingWith"],
                source="UPLOAD",
                uploadId=upload_id,
                createdAt=(previous or {}).get("createdAt", now),
                updatedAt=now,
                updatedBy=updated_by,
            ).to_dict()
            entries.append((item, previous))
    return entries


def _json_number(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Unsupported type {type(value).__name__}")


def _write_hotel_upload_snapshot(
    bucket: str, tour_id: str, upload_id: str, entries: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]
) -> None:
    body = {
        "tourId": tour_id,
        "uploadId": upload_id,
        "entries": [
            {"key": {"stayDate": item["stayDate"], "riderId": item["riderId"]}, "previous": previous}
            for item, previous in entries
        ],
    }
    s3_client.put_object(
        Bucket=bucket,
        Key=_hotel_upload_snapshot_key(tour_id, upload_id),
        Body=json.dumps(body, default=_json_number).encode("utf-8"),
        ContentType="application/json",
    )


def _read_hotel_upload_snapshot(
    bucket: str, tour_id: str, upload_id: str
) -> List[Tuple[Dict[str, str], Optional[Dict[str, Any]]]]:
    obj = s3_client.get_object(Bucket=bucket, Key=_hotel_upload_snapshot_key(tour_id, upload_id))
    body = json.loads(obj["Body"].read(), parse_float=Decimal)
    return [(entry["key"], entry.get("previous")) for entry in body.get("entries", [])]


def _rollback_hotel_upload(
    tour_id: str, upload_id: str, entries: List[Tuple[Dict[str, str], Optional[Dict[str, Any]]]]
) -> None:
    """Restore pre-upload items; only touches items still owned by this upload."""
    table = get_tour_table("RoomAllocation", tour_id)
    owned = {"ConditionExpression": "uploadId = :uploadId", "ExpressionAttributeValues": {":uploadId": upload_id}}
    for key, previous in entries:
        try:
            if previous:
                table.put_item(Item=previous, **owned)
            else:
                table.delete_item(Key=key, **owned)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
    logger.info("Rolled back %d allocation(s) for hotel upload %s/%s", len(entries), tour_id, upload_id)


def _put_condition(previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Optimistic check that the item is unchanged since validation read it."""
    if previous is None:
        return {"ConditionExpression": "attribute_not_exists(riderId)"}
    if previous.get("updatedAt") is None:
        return {"ConditionExpression": "attribute_exists(riderId) AND attribute_not_exists(updatedAt)"}
    return {
        "ConditionExpression": "updatedAt = :previousUpdatedAt",
        "ExpressionAttributeValues": {":previousUpdatedAt": previous["updatedAt"]},
    }


def _apply_hotel_upload(
    tour_id: str,
    upload_id: str,
    entries: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]],
    check_time,
) -> None:
    table = get_tour_table("RoomAllocation", tour_id)
    committed: List[Tuple[Dict[str, str], Optional[Dict[str, Any]]]] = []
    try:
        for start in range(0, len(entries), TRANSACT_MAX_ITEMS):
            check_time()
            chunk = entries[start:start + TRANSACT_MAX_ITEMS]
            table.meta.client.transact_write_items(
                TransactItems=[
                    {"Put": {"TableName": table.name, "Item": item, **_put_condition(previous)}}
                    for item, previous in chunk
                ]
            )
            committed.extend(
                ({"stayDate": item["stayDate"], "riderId": item["riderId"]}, previous) for item, previous in chunk
            )
    except ClientError as exc:
        _rollback_hotel_upload(tour_id, upload_id, committed)
        reasons = exc.response.get("CancellationReasons") or []
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException" and any(
            reason.get("Code") == "ConditionalCheckFailed" for reason in reasons
        ):
            raise HotelUploadRejected(
                "CONCURRENT_MODIFICATION",
                f"Room allocations changed while this file was being processed. {NOTHING_CHANGED}; re-upload the file.",
            ) from exc
        raise
    except Exception:
        _rollback_hotel_upload(tour_id, upload_id, committed)
        raise


def process_hotel_upload(bucket: Optional[str], key: Optional[str], context: Any = None) -> Dict[str, Any]:
    """Validate an uploaded hotel allocation CSV in full, then apply it all-or-nothing (D21)."""
    target = _parse_hotel_upload_key(bucket, key)
    if not target:
        logger.warning("Ignoring object outside hotel upload scope: %s/%s", bucket, key)
        return {"status": "IGNORED"}
    tour_id, upload_id, object_key = target

    started = utc_now_iso()
    claimed = _update_upload_status(
        tour_id,
        upload_id,
        {"status": HotelUploadStatus.VALIDATING.value, "processingStartedAt": started, "updatedAt": started},
        HotelUploadStatus.PENDING.value,
    )
    if not claimed:
        logger.info("Hotel upload %s/%s is not PENDING; skipping", tour_id, upload_id)
        return {"status": "IGNORED", "tourId": tour_id, "uploadId": upload_id}

    config = _get_hotel_upload_config()
    max_errors = config["maxStoredErrors"]

    def check_time() -> None:
        _ensure_time_remaining(context, config["timeReserveSeconds"])

    row_count: Optional[int] = None
    try:
        text, errors = _read_hotel_upload_file(bucket, object_key, config["maxFileSizeBytes"])
        if errors:
            return _reject_upload(tour_id, upload_id, errors, max_errors)
        check_time()

        directives, columns, rows, errors = _parse_hotel_upload_csv(text)
        row_count = len(rows)
        if not errors and not rows:
            errors = [_upload_error(FILE_LEVEL_ROW, "EMPTY_FILE", "The file has no data rows.")]
        if not errors and row_count > config["maxDataRows"]:
            errors = [_upload_error(FILE_LEVEL_ROW, "TOO_MANY_ROWS", f"The file has {row_count} data rows; the maximum is {config['maxDataRows']}.")]
        if errors:
            return _reject_upload(tour_id, upload_id, errors, max_errors, row_count)

        stay_dates, errors = _resolve_stay_dates(directives, config["maxStayDates"])
        riders = {item["riderId"]: item for item in scan_tour_items("TourRider", tour_id)}
        hotel_ids = {
            item["hotelId"] for item in scan_tour_items("Hotel", tour_id) if str(item.get("hotelId", "")).startswith("HTL-")
        }
        records, row_errors = _validate_hotel_upload_rows(rows, columns, directives, riders, hotel_ids)
        errors.extend(row_errors)
        # Phase 2 only runs on a structurally clean file to avoid misleading cross-row errors.
        if errors:
            return _reject_upload(tour_id, upload_id, errors, max_errors, row_count)
        check_time()

        existing, errors = _validate_hotel_upload_batch(tour_id, records, stay_dates, check_time)
        if errors:
            return _reject_upload(tour_id, upload_id, errors, max_errors, row_count)
        check_time()

        status_item = get_tour_item("Hotel", tour_id, {"hotelId": f"UPLOAD#{upload_id}"}) or {}
        entries = _build_hotel_upload_items(records, stay_dates, existing, upload_id, status_item.get("createdBy"))
        _write_hotel_upload_snapshot(bucket, tour_id, upload_id, entries)
        apply_started = utc_now_iso()
        if not _update_upload_status(
            tour_id,
            upload_id,
            {"applyStartedAt": apply_started, "updatedAt": apply_started},
            HotelUploadStatus.VALIDATING.value,
        ):
            logger.warning("Hotel upload %s/%s left VALIDATING before apply; aborting", tour_id, upload_id)
            return {"status": "IGNORED", "tourId": tour_id, "uploadId": upload_id}

        _apply_hotel_upload(tour_id, upload_id, entries, check_time)
        finished = utc_now_iso()
        _update_upload_status(
            tour_id,
            upload_id,
            {
                "status": HotelUploadStatus.APPLIED.value,
                "rowCount": row_count,
                "errorCount": 0,
                "errors": [],
                "appliedCount": len(entries),
                "processedAt": finished,
                "updatedAt": finished,
            },
            HotelUploadStatus.VALIDATING.value,
        )
        logger.info("Hotel upload %s/%s applied %d allocation(s)", tour_id, upload_id, len(entries))
        return {"status": HotelUploadStatus.APPLIED.value, "tourId": tour_id, "uploadId": upload_id}
    except HotelUploadDeadline:
        logger.warning("Hotel upload %s/%s stopped: time reserve reached", tour_id, upload_id)
        error = _upload_error(
            FILE_LEVEL_ROW,
            "PROCESSING_TIMEOUT",
            f"Processing did not finish in time. {NOTHING_CHANGED}; re-upload the file or split it into smaller files.",
        )
        return _reject_upload(tour_id, upload_id, [error], max_errors, row_count)
    except HotelUploadRejected as exc:
        return _reject_upload(tour_id, upload_id, [_upload_error(FILE_LEVEL_ROW, exc.code, exc.message)], max_errors, row_count)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Hotel upload %s/%s failed", tour_id, upload_id)
        error = _upload_error(FILE_LEVEL_ROW, "PROCESSING_ERROR", f"The file could not be processed. {NOTHING_CHANGED}; re-upload the file.")
        return _reject_upload(tour_id, upload_id, [error], max_errors, row_count)


def handle_hotel_upload_failure(event: Dict[str, Any]) -> Dict[str, Any]:
    """OnFailure destination for the processor: records hard timeouts/crashes and rolls back a started apply."""
    detail = (event.get("requestPayload") or {}).get("detail") or {}
    bucket = (detail.get("bucket") or {}).get("name")
    target = _parse_hotel_upload_key(bucket, (detail.get("object") or {}).get("key"))
    if not target:
        logger.warning("Ignoring failure record outside hotel upload scope")
        return {"status": "IGNORED"}
    tour_id, upload_id, _ = target

    status_item = get_tour_item("Hotel", tour_id, {"hotelId": f"UPLOAD#{upload_id}"})
    if not status_item or status_item.get("status") != HotelUploadStatus.VALIDATING.value:
        logger.info("Hotel upload %s/%s is not VALIDATING; nothing to recover", tour_id, upload_id)
        return {"status": "IGNORED", "tourId": tour_id, "uploadId": upload_id}

    response_payload = event.get("responsePayload") or {}
    error_type = str(response_payload.get("errorType", ""))
    error_message = str(response_payload.get("errorMessage", ""))
    logger.error("Hotel upload %s/%s processor failed: %s %s", tour_id, upload_id, error_type, error_message)
    timed_out = error_type == "Sandbox.Timedout" or "timed out" in error_message.lower()

    rolled_back = True
    if status_item.get("applyStartedAt"):
        try:
            _rollback_hotel_upload(tour_id, upload_id, _read_hotel_upload_snapshot(bucket, tour_id, upload_id))
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Rollback failed for hotel upload %s/%s", tour_id, upload_id)
            rolled_back = False

    if not rolled_back:
        error = _upload_error(
            FILE_LEVEL_ROW,
            "PROCESSING_ERROR",
            "Processing failed and some allocations may not have been restored. Contact an administrator before re-uploading.",
        )
    elif timed_out:
        error = _upload_error(
            FILE_LEVEL_ROW,
            "PROCESSING_TIMEOUT",
            f"Processing did not finish in time. {NOTHING_CHANGED}; re-upload the file or split it into smaller files.",
        )
    else:
        error = _upload_error(FILE_LEVEL_ROW, "PROCESSING_ERROR", f"The file could not be processed. {NOTHING_CHANGED}; re-upload the file.")
    return _reject_upload(tour_id, upload_id, [error], HOTEL_UPLOAD_CONFIG_DEFAULTS["maxStoredErrors"])


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
