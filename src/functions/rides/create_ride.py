"""
Lambda function to create a new ride for a tour

Uses tour-specific Ride-{tourId} table and shared TourMaster table.
Route: POST /v1/tours/{tourId}/rides
"""

import json
import sys

from logger import get_logger
from response import (
    success_response,
    bad_request_response,
    conflict_response,
    not_found_response,
    validation_exception_response,
)
from handler_utils import api_handler
from validation import (
    validate_tour_id,
    validate_ride_id,
    validate_required_fields,
    validate_iso_date,
    validate_time_hhmm,
    validate_ride_stages,
    validate_ride_floats,
    validate_optional_bool,
    ValidationError,
)
from dynamodb_utils import get_item, get_tour_item, put_tour_item
from models import RideStatus, TourStatus, utc_now_iso
from rbac import require_permission, Permission

sys.path.insert(0, "/opt/python")
logger = get_logger(__name__)

# Optional ride-level self check-in settings; absent means "follow the default".
RIDE_SELF_SERVICE_FIELDS = ("selfCheckInAllowed", "selfQuitRidingAllowed")


@api_handler("Failed to create ride")
def lambda_handler(event, context):
    """
    Create a new ride for a tour

    Path parameter: tourId (e.g., TOT-2026)
    Body: JSON with ride details
    {
        "rideId": "RIDE001",
        "date": "2026-06-15",
        "rideNo": 1,
        "name": "Geneva to Lausanne",
        "startLocation": "Geneva Central",
        "finishLocation": "Lausanne",
        "totalDistance": 65.5,
        "flagOffTime": "08:00",
        "stages": [...],
        "description": "Optional description",
        "selfCheckInAllowed": true,        # optional ride-wide stage default
        "selfQuitRidingAllowed": false     # optional, overrides the tour setting
    }

    Returns:
    - 201: Ride created successfully
    - 400: Invalid input
    - 404: Tour not found
    - 409: Ride already exists
    - 500: Server error
    """
    # Enforce RBAC — only RIDE_MANAGE permission may create rides
    deny = require_permission(event, Permission.RIDE_MANAGE)
    if deny:
        return deny

    # Extract tour ID from path parameters
    tour_id = event.get("pathParameters", {}).get("tourId")

    if not tour_id:
        return bad_request_response("tourId is required in path")

    # Validate tour ID
    try:
        validate_tour_id(tour_id)
    except ValidationError as e:
        return bad_request_response(str(e))

    # Parse request body
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return bad_request_response("Invalid JSON in request body")

    # Validate required fields
    required_fields = [
        "rideId",
        "date",
        "rideNo",
        "name",
        "startLocation",
        "finishLocation",
        "totalDistance",
        "flagOffTime",
        "stages",
    ]
    try:
        validate_required_fields(body, required_fields)
    except ValidationError as e:
        return bad_request_response(str(e))

    try:
        validate_ride_id(body["rideId"])
    except ValidationError as e:
        return bad_request_response(str(e))

    # Validate date
    try:
        validate_iso_date(body["date"], "date")
    except ValidationError as e:
        return bad_request_response(str(e))

    # Validate flagOffTime (HH:MM 24-hour format)
    try:
        validate_time_hhmm(body["flagOffTime"], "flagOffTime")
    except ValidationError as e:
        return bad_request_response(str(e))

    if body.get("openTime") is not None:
        try:
            validate_time_hhmm(body["openTime"], "openTime")
        except ValidationError as e:
            return bad_request_response(str(e))

    if body.get("closeTime") is not None:
        try:
            validate_time_hhmm(body["closeTime"], "closeTime")
        except ValidationError as e:
            return bad_request_response(str(e))

    # Validate numeric fields
    if (
        not isinstance(body["totalDistance"], (int, float))
        or body["totalDistance"] <= 0
    ):
        return bad_request_response("totalDistance must be a positive number")

    if not isinstance(body["rideNo"], int) or body["rideNo"] < 1:
        return bad_request_response("rideNo must be a positive integer")

    try:
        normalized_stages = validate_ride_stages(body["stages"])
        for setting in RIDE_SELF_SERVICE_FIELDS:
            if setting in body and body[setting] is not None:
                validate_optional_bool(body[setting], setting)
    except ValidationError as e:
        return validation_exception_response(e)

    normalized_floats = None
    if "floats" in body:
        try:
            normalized_floats = validate_ride_floats(
                body["floats"], len(normalized_stages)
            )
        except ValidationError as e:
            return bad_request_response(str(e))

    # Check if tour exists and is in the right status
    logger.info("Checking if tour exists: %s", tour_id)
    tour = get_item(table_name_env="TOUR_MASTER_TABLE", key={"tourId": tour_id})

    if not tour:
        return not_found_response("Tour", tour_id)

    tour_status = tour.get("status")
    if tour_status not in [TourStatus.PLANNING.value, TourStatus.ACTIVE.value]:
        return bad_request_response(
            f"Cannot create rides for tour in {tour_status} status. "
            "Tour must be in PLANNING or ACTIVE status."
        )

    ride_id = body["rideId"]

    # Check if ride already exists
    existing_ride = get_tour_item(
        table_type="Ride", tour_id=tour_id, key={"rideId": ride_id}
    )

    if existing_ride:
        return conflict_response(f"Ride '{ride_id}' already exists in tour '{tour_id}'")

    # Create ride object
    now = utc_now_iso()
    ride = {
        "rideId": ride_id,
        "date": body["date"],
        "rideNo": body["rideNo"],
        "name": body["name"],
        "startLocation": body["startLocation"],
        "finishLocation": body["finishLocation"],
        "totalDistance": body["totalDistance"],
        "flagOffTime": body["flagOffTime"],
        "stages": normalized_stages,
        "floats": normalized_floats,
        "status": RideStatus.PLANNED.value,
        "openTime": body.get("openTime"),
        "closeTime": body.get("closeTime"),
        "description": body.get("description"),
        "selfCheckInAllowed": body.get("selfCheckInAllowed"),
        "selfQuitRidingAllowed": body.get("selfQuitRidingAllowed"),
        "createdAt": now,
        "updatedAt": now,
    }

    # Remove None values
    ride = {k: v for k, v in ride.items() if v is not None}

    # Save to tour-specific Ride table
    logger.info("Creating ride: %s in tour %s", ride_id, tour_id)
    put_tour_item(table_type="Ride", tour_id=tour_id, item=ride)

    logger.info("Successfully created ride: %s", ride_id)
    return success_response(ride, status_code=201)
