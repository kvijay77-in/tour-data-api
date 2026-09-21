"""
Validation utilities for input validation
"""

import re
from typing import Dict, Any, Optional, List
from datetime import datetime


STAGE_TYPES = {"START", "PIT_STOP", "FINISH"}
PIT_STOP_RUNTIME_FIELDS = ('pitStopStatus', 'openedAt', 'closedAt')
RIDER_GENDER_VALUES = {"Male", "Female", "Other", "Prefer not to say"}
RIDER_ADDRESS_REQUIRED_FIELDS = ('line1', 'city', 'country', 'postalCode')
RIDER_ADDRESS_OPTIONAL_FIELDS = ('line2', 'state')
RIDER_ADDRESS_ALLOWED_FIELDS = RIDER_ADDRESS_REQUIRED_FIELDS + RIDER_ADDRESS_OPTIONAL_FIELDS
EMERGENCY_CONTACT_FIELDS = ('name', 'phone', 'relation')
ALLOWED_ARTIFACT_CONTENT_TYPES = {
    'image/png',
    'image/jpeg',
    'image/jpg',
    'image/webp',
    'application/pdf',
    'application/gpx+xml',
    'application/xml',
    'text/xml',
    'text/plain',
    'application/octet-stream',
}
ARTIFACT_CATEGORIES = {'tour', 'ride'}
DIETARY_PREFERENCE_VALUES = {'VEG', 'NON_VEG'}
EVENT_TYPES = {'SINGLE', 'REPEATING'}
EVENT_OCCURRENCE_STATUSES = {'PLANNED', 'ACTIVE', 'COMPLETED', 'CANCELLED'}
BAGGAGE_STATUSES = {'ACTIVE', 'RETAINED', 'WITH_RIDER'}


class ValidationError(Exception):
    """Validation error exception"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


def validate_rider_id(rider_id: str) -> None:
    """
    Validate Rider ID format (R followed by 1-3 digits, no padding)
    
    Args:
        rider_id: Rider ID to validate
    
    Raises:
        ValidationError: If format is invalid
    """
    if not re.match(r'^R([1-9]\d{0,2})$', rider_id):
        raise ValidationError(
            f"Invalid Rider ID format: {rider_id}. Expected format: R1, R2, R57, R102",
            {"field": "riderId", "value": rider_id}
        )
    
    # Extract numeric part and validate range
    num = int(rider_id[1:])
    if num < 1 or num > 999:
        raise ValidationError(
            f"Rider ID number out of range: {num}. Must be between 1 and 999",
            {"field": "riderId", "value": rider_id}
        )


def validate_artifact_id(artifact_id: str) -> None:
    """Validate artifact IDs used in app config and storage keys."""
    if not artifact_id or not isinstance(artifact_id, str):
        raise ValidationError(
            "Artifact ID is required and must be a non-empty string",
            {"field": "artifactId", "value": artifact_id},
        )

    normalized = artifact_id.strip()
    if not re.match(r'^[a-z0-9][a-z0-9-]*$', normalized):
        raise ValidationError(
            f"Invalid artifact ID: '{artifact_id}'. Expected lowercase letters, numbers, and hyphens only",
            {"field": "artifactId", "value": artifact_id},
        )


def validate_artifact_content_type(content_type: str) -> None:
    """Validate the MIME type for a stored artifact."""
    if not content_type or not isinstance(content_type, str):
        raise ValidationError(
            "contentType is required and must be a string",
            {"field": "contentType", "value": content_type},
        )

    normalized = content_type.strip().lower()
    if normalized not in ALLOWED_ARTIFACT_CONTENT_TYPES:
        raise ValidationError(
            f"Unsupported artifact contentType: '{content_type}'. Allowed values: {sorted(ALLOWED_ARTIFACT_CONTENT_TYPES)}",
            {"field": "contentType", "value": content_type},
        )


def validate_artifact_category(category: str) -> None:
    """Validate artifact category values used by AppConfig and APIs."""
    if not category or not isinstance(category, str):
        raise ValidationError(
            "Artifact category is required and must be a string",
            {"field": "category", "value": category},
        )

    normalized = category.strip().lower()
    if normalized not in ARTIFACT_CATEGORIES:
        raise ValidationError(
            f"Unsupported artifact category: '{category}'. Supported values: {sorted(ARTIFACT_CATEGORIES)}",
            {"field": "category", "value": category},
        )


def validate_tour_id(tour_id: str) -> None:
    """
    Validate Tour ID format (free-form, used as DynamoDB table name suffix).
    
    Rules:
    - Allowed characters: a-z, A-Z, 0-9, _, -, .
    - Length: 3-50 characters
    - Must start with a letter or number
    
    Args:
        tour_id: Tour ID to validate
    
    Raises:
        ValidationError: If format is invalid
    """
    if not tour_id or len(tour_id) < 3 or len(tour_id) > 50:
        raise ValidationError(
            f"Invalid Tour ID: '{tour_id}'. Must be 3-50 characters long",
            {"field": "tourId", "value": tour_id}
        )
    
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.\-]{2,49}$', tour_id):
        raise ValidationError(
            f"Invalid Tour ID format: '{tour_id}'. Must start with letter/number, "
            "allowed chars: a-z, A-Z, 0-9, _, -, .",
            {"field": "tourId", "value": tour_id}
        )


def validate_ride_id(ride_id: str) -> None:
    """
    Validate Ride ID format (RIDE followed by 3-digit padded number)
    
    Args:
        ride_id: Ride ID to validate
    
    Raises:
        ValidationError: If format is invalid
    """
    if not re.match(r'^RIDE\d{3}$', ride_id):
        raise ValidationError(
            f"Invalid Ride ID format: {ride_id}. Expected format: RIDE001, RIDE008",
            {"field": "rideId", "value": ride_id}
        )


def validate_stage_id(stage_id: str) -> None:
    """
    Validate Stage ID format (S followed by 3-digit padded number)
    
    Args:
        stage_id: Stage ID to validate
    
    Raises:
        ValidationError: If format is invalid
    """
    if not re.match(r'^S\d{3}$', stage_id):
        raise ValidationError(
            f"Invalid Stage ID format: {stage_id}. Expected format: S000, S001",
            {"field": "stageId", "value": stage_id}
        )


def validate_event_id(event_id: str) -> None:
    """Validate event identifier format."""
    if not re.match(r'^EVT-[A-Z0-9]{2,20}$', event_id or ''):
        raise ValidationError(
            f"Invalid Event ID format: {event_id}. Expected format: EVT-BAGLOAD",
            {"field": "eventId", "value": event_id}
        )


def validate_activity_id(activity_id: str) -> None:
    """Validate activity identifier format."""
    if not re.match(r'^ACT-\d{3}$', activity_id or ''):
        raise ValidationError(
            f"Invalid Activity ID format: {activity_id}. Expected format: ACT-001",
            {"field": "activityId", "value": activity_id}
        )


def validate_occurrence_id(occurrence_id: str) -> None:
    """Validate occurrence identifier format."""
    if not re.match(r'^EVT-[A-Z0-9]{2,20}#\d{4}-\d{2}-\d{2}#[1-9]\d*$', occurrence_id or ''):
        raise ValidationError(
            f"Invalid occurrenceId format: {occurrence_id}",
            {"field": "occurrenceId", "value": occurrence_id}
        )


def validate_hotel_id(hotel_id: str) -> None:
    """Validate hotel identifier format."""
    if not re.match(r'^HTL-[A-Z]{3}-\d{2}$', hotel_id or ''):
        raise ValidationError(
            f"Invalid hotelId format: {hotel_id}. Expected format: HTL-MDU-01",
            {"field": "hotelId", "value": hotel_id}
        )


def validate_upload_id(upload_id: str) -> None:
    """Validate upload identifier format."""
    if not re.match(r'^UPL-\d{6}$', upload_id or ''):
        raise ValidationError(
            f"Invalid uploadId format: {upload_id}. Expected format: UPL-000042",
            {"field": "uploadId", "value": upload_id}
        )


def validate_iso_date(date_str: str, field_name: str = "date") -> None:
    """
    Validate ISO 8601 date format (YYYY-MM-DD)
    
    Args:
        date_str: Date string to validate
        field_name: Name of the field being validated
    
    Raises:
        ValidationError: If format is invalid
    """
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        raise ValidationError(
            f"Invalid date format: {date_str}. Expected format: YYYY-MM-DD",
            {"field": field_name, "value": date_str}
        )
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise ValidationError(
            f"Invalid date format: {date_str}. Expected format: YYYY-MM-DD",
            {"field": field_name, "value": date_str}
        )


def validate_iso_datetime(datetime_str: str, field_name: str = "timestamp") -> None:
    """
    Validate ISO 8601 datetime format in UTC with Z suffix.
    
    Accepts: YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DDTHH:MM:SS.ffffffZ
    Rejects non-UTC offsets (e.g., +05:30) to enforce project convention.
    
    Args:
        datetime_str: Datetime string to validate
        field_name: Name of the field being validated
    
    Raises:
        ValidationError: If format is invalid or not UTC with Z suffix
    """
    if not datetime_str or not datetime_str.endswith('Z'):
        raise ValidationError(
            f"Invalid datetime format: {datetime_str}. "
            "Expected ISO 8601 UTC format with Z suffix (e.g., 2026-02-11T10:30:00Z)",
            {"field": field_name, "value": datetime_str}
        )
    try:
        datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
    except ValueError:
        raise ValidationError(
            f"Invalid datetime format: {datetime_str}. "
            "Expected ISO 8601 UTC format with Z suffix (e.g., 2026-02-11T10:30:00Z)",
            {"field": field_name, "value": datetime_str}
        )


def validate_time_hhmm(time_str: str, field_name: str = "time") -> None:
    """
    Validate time format (HH:MM, 24-hour)
    
    Args:
        time_str: Time string to validate
        field_name: Name of the field being validated
    
    Raises:
        ValidationError: If format is invalid
    """
    if not re.match(r'^([01]\d|2[0-3]):[0-5]\d$', time_str):
        raise ValidationError(
            f"Invalid time format: {time_str}. Expected HH:MM in 24-hour format (e.g., 08:00, 14:30)",
            {"field": field_name, "value": time_str}
        )


def validate_email(email: str) -> None:
    """
    Validate email address format
    
    Args:
        email: Email address to validate
    
    Raises:
        ValidationError: If format is invalid
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        raise ValidationError(
            f"Invalid email format: {email}",
            {"field": "email", "value": email}
        )


def normalize_personal_code(personal_code: Any) -> Optional[str]:
    """Normalize rider personalCode to uppercase.

    Returns None when the field is not supplied.
    """
    if personal_code is None:
        return None

    if not isinstance(personal_code, str):
        raise ValidationError(
            "personalCode must be a string when provided",
            {"field": "personalCode", "value": personal_code}
        )

    normalized = personal_code.strip().upper()
    if not normalized:
        raise ValidationError(
            "personalCode cannot be empty",
            {"field": "personalCode", "value": personal_code}
        )

    return normalized


def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> None:
    """
    Validate that all required fields are present
    
    Args:
        data: Data dictionary to validate
        required_fields: List of required field names
    
    Raises:
        ValidationError: If any required field is missing
    """
    missing_fields = [field for field in required_fields if field not in data or data[field] is None]
    
    if missing_fields:
        raise ValidationError(
            f"Missing required fields: {', '.join(missing_fields)}",
            {"missing_fields": missing_fields}
        )


def validate_event_type(event_type: str) -> None:
    if event_type not in EVENT_TYPES:
        raise ValidationError(
            f"Invalid eventType. Supported values: {', '.join(sorted(EVENT_TYPES))}",
            {"field": "eventType", "value": event_type}
        )


def validate_event_occurrence_status(status: str) -> None:
    if status not in EVENT_OCCURRENCE_STATUSES:
        raise ValidationError(
            f"Invalid occurrence status. Supported values: {', '.join(sorted(EVENT_OCCURRENCE_STATUSES))}",
            {"field": "status", "value": status}
        )


def validate_baggage_status(status: str) -> None:
    if status not in BAGGAGE_STATUSES:
        raise ValidationError(
            f"Invalid baggageStatus. Supported values: {', '.join(sorted(BAGGAGE_STATUSES))}",
            {"field": "baggageStatus", "value": status}
        )


def validate_allowed_type_codes(allowed_type_codes: Any, field_name: str = "allowedTypeCodes") -> None:
    if allowed_type_codes is None:
        return
    if not isinstance(allowed_type_codes, list) or not all(isinstance(code, str) and code.strip() for code in allowed_type_codes):
        raise ValidationError(
            f"{field_name} must be a list of non-empty strings",
            {"field": field_name, "value": allowed_type_codes}
        )


def validate_variant_options(variant_options: Any) -> None:
    if variant_options is None:
        return
    if not isinstance(variant_options, list) or not all(isinstance(option, str) and option.strip() for option in variant_options):
        raise ValidationError(
            "variantOptions must be a list of non-empty strings",
            {"field": "variantOptions", "value": variant_options}
        )


def validate_sharing_with(sharing_with: Any) -> None:
    if sharing_with is None:
        return
    if not isinstance(sharing_with, list):
        raise ValidationError(
            "sharingWith must be a list of rider IDs",
            {"field": "sharingWith", "value": sharing_with}
        )
    for rider_id in sharing_with:
        validate_rider_id(rider_id)


def validate_rider_profile_optional_fields(
    data: Dict[str, Any],
    require_mandatory_fields: bool = False,
) -> None:
    """Validate rider profile optional/mandatory fields based on endpoint context."""
    if require_mandatory_fields:
        validate_required_fields(data, ['dateOfBirth', 'gender', 'address'])

    if 'dateOfBirth' in data and data.get('dateOfBirth') is not None:
        date_of_birth = data.get('dateOfBirth')
        if not isinstance(date_of_birth, str):
            raise ValidationError(
                "dateOfBirth must be a string in YYYY-MM-DD format",
                {"field": "dateOfBirth", "value": date_of_birth}
            )
        validate_iso_date(date_of_birth, field_name='dateOfBirth')

    if 'gender' in data and data.get('gender') is not None:
        gender = data.get('gender')
        if not isinstance(gender, str):
            raise ValidationError(
                "gender must be a string",
                {"field": "gender", "value": gender}
            )
        if gender not in RIDER_GENDER_VALUES:
            raise ValidationError(
                "Invalid gender. Supported values: Male, Female, Other, Prefer not to say",
                {"field": "gender", "value": gender}
            )

    if 'dietaryPreference' in data and data.get('dietaryPreference') is not None:
        dietary_preference = data.get('dietaryPreference')
        if not isinstance(dietary_preference, str):
            raise ValidationError(
                "dietaryPreference must be a string",
                {"field": "dietaryPreference", "value": dietary_preference}
            )
        if dietary_preference not in DIETARY_PREFERENCE_VALUES:
            raise ValidationError(
                "Invalid dietaryPreference. Supported values: VEG, NON_VEG",
                {"field": "dietaryPreference", "value": dietary_preference}
            )

    if 'emergencyContact' in data:
        validate_emergency_contact(data.get('emergencyContact'))

    if 'address' in data and data.get('address') is not None:
        address = data.get('address')
        if not isinstance(address, dict):
            raise ValidationError(
                "address must be an object with line1, line2, city, state, country, and postalCode",
                {"field": "address", "value": address}
            )

        missing_fields = [field for field in RIDER_ADDRESS_REQUIRED_FIELDS if field not in address]
        if missing_fields:
            raise ValidationError(
                f"address is missing required fields: {', '.join(missing_fields)}",
                {"field": "address", "missing_fields": missing_fields}
            )

        extra_fields = [field for field in address.keys() if field not in RIDER_ADDRESS_ALLOWED_FIELDS]
        if extra_fields:
            raise ValidationError(
                f"address has unsupported fields: {', '.join(extra_fields)}",
                {"field": "address", "unsupported_fields": extra_fields}
            )

        for field_name in RIDER_ADDRESS_REQUIRED_FIELDS:
            value = address.get(field_name)
            if not isinstance(value, str):
                raise ValidationError(
                    f"address['{field_name}'] must be a string",
                    {"field": f"address.{field_name}", "value": value}
                )

        for field_name in RIDER_ADDRESS_OPTIONAL_FIELDS:
            if field_name not in address:
                continue
            value = address.get(field_name)
            if not isinstance(value, str):
                raise ValidationError(
                    f"address['{field_name}'] must be a string",
                    {"field": f"address.{field_name}", "value": value}
                )


def validate_emergency_contact(emergency_contact: Any) -> None:
    """Validate emergencyContact map payload."""
    if not isinstance(emergency_contact, dict):
        raise ValidationError(
            "emergencyContact must be an object with name, phone, and relation",
            {"field": "emergencyContact", "value": emergency_contact}
        )

    missing_fields = [field for field in EMERGENCY_CONTACT_FIELDS if field not in emergency_contact]
    if missing_fields:
        raise ValidationError(
            f"emergencyContact is missing required fields: {', '.join(missing_fields)}",
            {"field": "emergencyContact", "missing_fields": missing_fields}
        )

    extra_fields = [field for field in emergency_contact.keys() if field not in EMERGENCY_CONTACT_FIELDS]
    if extra_fields:
        raise ValidationError(
            f"emergencyContact has unsupported fields: {', '.join(extra_fields)}",
            {"field": "emergencyContact", "unsupported_fields": extra_fields}
        )

    for field_name in EMERGENCY_CONTACT_FIELDS:
        value = emergency_contact.get(field_name)
        if not isinstance(value, str):
            raise ValidationError(
                f"emergencyContact['{field_name}'] must be a string",
                {"field": f"emergencyContact.{field_name}", "value": value}
            )


def build_emergency_contact_from_profile(profile: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Return emergencyContact map from canonical field or legacy flat fields."""
    if not isinstance(profile, dict):
        return None

    emergency_contact = profile.get('emergencyContact')
    if isinstance(emergency_contact, dict):
        return {
            'name': emergency_contact.get('name'),
            'phone': emergency_contact.get('phone'),
            'relation': emergency_contact.get('relation'),
        }

    name = profile.get('emergencyContactName')
    phone = profile.get('emergencyContactPhone')
    relation = profile.get('emergencyContactRelationship', profile.get('Relationship'))
    if name is None and phone is None and relation is None:
        return None

    return {
        'name': name,
        'phone': phone,
        'relation': relation,
    }


def validate_stage_number(stage_number: int, total_stages: int) -> None:
    """
    Validate stage number is within valid range
    
    Args:
        stage_number: Stage number to validate
        total_stages: Total number of stages in the ride
    
    Raises:
        ValidationError: If stage number is invalid
    """
    max_stage_number = total_stages - 1
    if stage_number < 0 or stage_number > max_stage_number:
        raise ValidationError(
            f"Invalid stage number: {stage_number}. Must be between 0 and {max_stage_number}",
            {"field": "stageNumber", "value": stage_number, "maxStages": total_stages}
        )


def validate_positive_number(value: float, field_name: str) -> None:
    """
    Validate that a number is positive
    
    Args:
        value: Number to validate
        field_name: Name of the field being validated
    
    Raises:
        ValidationError: If number is not positive
    """
    if value <= 0:
        raise ValidationError(
            f"{field_name} must be a positive number",
            {"field": field_name, "value": value}
        )


def validate_ride_count(value: Any, field_name: str = "rideCount") -> None:
    """
    Validate the total number of rides planned for a tour

    Args:
        value: Value to validate
        field_name: Name of the field being validated

    Raises:
        ValidationError: If value is not a positive integer
    """
    # bool is a subclass of int and must be rejected explicitly
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError(
            f"{field_name} must be a positive integer",
            {"field": field_name, "value": value}
        )


def validate_ride_stages(stages: Any) -> List[Dict[str, Any]]:
    """Validate and normalize ride stages payload."""
    if not isinstance(stages, list) or not stages:
        raise ValidationError("stages must be a non-empty array", {"field": "stages"})

    normalized_stages: List[Dict[str, Any]] = []
    seen_stage_ids = set()

    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            raise ValidationError(
                f"Stage at index {index} must be an object",
                {"field": f"stages[{index}]"}
            )

        validate_required_fields(stage, ['stageId', 'stageNumber', 'type', 'name'])
        validate_stage_id(stage['stageId'])

        if not isinstance(stage['stageNumber'], int):
            raise ValidationError(
                f"stageNumber for stage '{stage['stageId']}' must be an integer",
                {"field": f"stages[{index}].stageNumber", "value": stage['stageNumber']}
            )

        stage_type = stage['type']
        if stage_type not in STAGE_TYPES:
            raise ValidationError(
                f"Invalid stage type: {stage_type}. Must be one of: START, PIT_STOP, FINISH",
                {"field": f"stages[{index}].type", "value": stage_type}
            )

        if not isinstance(stage['name'], str) or not stage['name'].strip():
            raise ValidationError(
                f"name for stage '{stage['stageId']}' must be a non-empty string",
                {"field": f"stages[{index}].name", "value": stage['name']}
            )

        stage_id = stage['stageId']
        if stage_id in seen_stage_ids:
            raise ValidationError(
                f"Duplicate stageId: {stage_id}",
                {"field": f"stages[{index}].stageId", "value": stage_id}
            )
        seen_stage_ids.add(stage_id)

        normalized_stage = {
            'stageId': stage_id,
            'stageNumber': stage['stageNumber'],
            'type': stage_type,
            'name': stage['name'].strip(),
        }

        if 'location' in stage and stage['location'] is not None:
            if not isinstance(stage['location'], str) or not stage['location'].strip():
                raise ValidationError(
                    f"location for stage '{stage_id}' must be a non-empty string when provided",
                    {"field": f"stages[{index}].location", "value": stage['location']}
                )
            normalized_stage['location'] = stage['location'].strip()

        if 'distanceFromStart' in stage and stage['distanceFromStart'] is not None:
            if not isinstance(stage['distanceFromStart'], (int, float)) or stage['distanceFromStart'] < 0:
                raise ValidationError(
                    f"distanceFromStart for stage '{stage_id}' must be a non-negative number",
                    {"field": f"stages[{index}].distanceFromStart", "value": stage['distanceFromStart']}
                )
            normalized_stage['distanceFromStart'] = stage['distanceFromStart']

        if 'estimatedOpenTime' in stage and stage['estimatedOpenTime'] is not None:
            if stage_type != 'PIT_STOP':
                raise ValidationError(
                    f"estimatedOpenTime is only applicable to PIT_STOP stages: {stage_id}",
                    {"field": f"stages[{index}].estimatedOpenTime", "value": stage['estimatedOpenTime']}
                )
            if not isinstance(stage['estimatedOpenTime'], int) or stage['estimatedOpenTime'] < 0:
                raise ValidationError(
                    f"estimatedOpenTime for stage '{stage_id}' must be a non-negative integer",
                    {"field": f"stages[{index}].estimatedOpenTime", "value": stage['estimatedOpenTime']}
                )
            normalized_stage['estimatedOpenTime'] = stage['estimatedOpenTime']

        if 'pitStopDuration' in stage and stage['pitStopDuration'] is not None:
            if stage_type != 'PIT_STOP':
                raise ValidationError(
                    f"pitStopDuration is only applicable to PIT_STOP stages: {stage_id}",
                    {"field": f"stages[{index}].pitStopDuration", "value": stage['pitStopDuration']}
                )
            if not isinstance(stage['pitStopDuration'], int) or stage['pitStopDuration'] < 0:
                raise ValidationError(
                    f"pitStopDuration for stage '{stage_id}' must be a non-negative integer",
                    {"field": f"stages[{index}].pitStopDuration", "value": stage['pitStopDuration']}
                )
            normalized_stage['pitStopDuration'] = stage['pitStopDuration']

        if 'estimatedTimeFromStart' in stage:
            raise ValidationError(
                "estimatedTimeFromStart is no longer supported; use estimatedOpenTime and pitStopDuration",
                {"field": f"stages[{index}].estimatedTimeFromStart"}
            )

        for runtime_field in PIT_STOP_RUNTIME_FIELDS:
            if runtime_field in stage and stage[runtime_field] is not None:
                raise ValidationError(
                    f"{runtime_field} is managed by the system and cannot be set in ride payloads",
                    {"field": f"stages[{index}].{runtime_field}", "value": stage[runtime_field]}
                )

        normalized_stages.append(normalized_stage)

    ordered_stages = sorted(normalized_stages, key=lambda stage: stage['stageNumber'])

    for expected_stage_number, stage in enumerate(ordered_stages):
        if stage['stageNumber'] != expected_stage_number:
            raise ValidationError(
                f"stageNumber values must be sequential starting at 0. Expected {expected_stage_number}, got {stage['stageNumber']}",
                {"field": "stages.stageNumber", "value": stage['stageNumber']}
            )

    if ordered_stages[0]['type'] != 'START':
        raise ValidationError("First stage must be type START", {"field": "stages[0].type"})

    if ordered_stages[-1]['type'] != 'FINISH':
        raise ValidationError("Last stage must be type FINISH", {"field": "stages[-1].type"})

    for stage in ordered_stages[1:-1]:
        if stage['type'] != 'PIT_STOP':
            raise ValidationError(
                "Intermediate stages must be type PIT_STOP",
                {"field": "stages.type", "value": stage['type']}
            )

    return ordered_stages


def validate_ride_floats(floats: Any, total_stages: int) -> List[Dict[str, int]]:
    """Validate and normalize ride floats payload."""
    if not isinstance(floats, list):
        raise ValidationError("floats must be an array", {"field": "floats"})

    if total_stages < 2:
        raise ValidationError(
            "Ride must define at least start and finish stages before floats can be set",
            {"field": "floats", "totalStages": total_stages}
        )

    normalized_floats: List[Dict[str, int]] = []
    seen_float_numbers = set()

    for index, ride_float in enumerate(floats):
        if not isinstance(ride_float, dict):
            raise ValidationError(
                f"Float at index {index} must be an object",
                {"field": f"floats[{index}]"}
            )

        validate_required_fields(ride_float, ['floatNo', 'floatToStage'])

        float_no = ride_float['floatNo']
        float_to_stage = ride_float['floatToStage']

        if not isinstance(float_no, int) or float_no < 1:
            raise ValidationError(
                f"floatNo at index {index} must be a positive integer",
                {"field": f"floats[{index}].floatNo", "value": float_no}
            )

        if float_no in seen_float_numbers:
            raise ValidationError(
                f"Duplicate floatNo: {float_no}",
                {"field": f"floats[{index}].floatNo", "value": float_no}
            )
        seen_float_numbers.add(float_no)

        if not isinstance(float_to_stage, int) or float_to_stage < 1 or float_to_stage >= total_stages:
            raise ValidationError(
                f"floatToStage at index {index} must be an integer between 1 and {total_stages - 1}",
                {"field": f"floats[{index}].floatToStage", "value": float_to_stage, "maxStageNumber": total_stages - 1}
            )

        normalized_floats.append({
            'floatNo': float_no,
            'floatToStage': float_to_stage,
        })

    return sorted(normalized_floats, key=lambda ride_float: ride_float['floatNo'])
