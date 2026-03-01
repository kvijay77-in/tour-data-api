"""
Validation utilities for input validation
"""

import re
from typing import Dict, Any, Optional, List
from datetime import datetime


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
            f"Invalid Stage ID format: {stage_id}. Expected format: S001, S002",
            {"field": "stageId", "value": stage_id}
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


def validate_stage_number(stage_number: int, total_stages: int) -> None:
    """
    Validate stage number is within valid range
    
    Args:
        stage_number: Stage number to validate
        total_stages: Total number of stages in the ride
    
    Raises:
        ValidationError: If stage number is invalid
    """
    if stage_number < 1 or stage_number > total_stages:
        raise ValidationError(
            f"Invalid stage number: {stage_number}. Must be between 1 and {total_stages}",
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
