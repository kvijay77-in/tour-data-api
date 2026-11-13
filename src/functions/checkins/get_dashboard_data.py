"""
Get dashboard data Lambda function

Retrieves all data needed for the Check-In App dashboard:
- Ride details with stages
- All tour riders with profile data
- All check-ins for the ride
- Summary statistics
- ETag support for conditional requests (304 Not Modified)

Uses tour-specific tables: Ride-{tourId}, TourRider-{tourId}, CheckIn-{tourId}
and shared RiderProfile table.
Route: GET /v1/tours/{tourId}/rides/{rideId}/dashboard
"""

import sys

import hashlib
import json

from logger import get_logger, log_event
from response import (
    success_response,
    not_found_response,
    bad_request_response,
    not_modified_response,
    DecimalEncoder,
)
from handler_utils import api_handler
from dynamodb_utils import (
    get_tour_item,
    query_tour_items,
    scan_tour_items,
    batch_get_items,
)
from validation import (
    validate_tour_id,
    validate_ride_id,
    ValidationError,
    build_emergency_contact_from_profile,
)
from rbac import require_permission, Permission
from models import is_cancelled_checkin_item

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)


@api_handler("Failed to retrieve dashboard data")
def lambda_handler(event, context):
    """
    Get complete dashboard data for a ride

    Path Parameters:
        tourId: Tour identifier (e.g., TOT-2026)
        rideId: Ride identifier (e.g., RIDE001)
    """
    log_event(logger, event)

    # Extract path parameters early so denied requests can be tied to a specific route.
    tour_id = event.get("pathParameters", {}).get("tourId")
    ride_id = event.get("pathParameters", {}).get("rideId")

    # Enforce RBAC — DASHBOARD permission required; HOTEL_STAFF may not access
    deny = require_permission(event, Permission.DASHBOARD)
    if deny:
        return deny

    if not tour_id or not ride_id:
        return bad_request_response("tourId and rideId are required in path")

    # Validate IDs
    try:
        validate_tour_id(tour_id)
        validate_ride_id(ride_id)
    except ValidationError as e:
        return bad_request_response(str(e))

    logger.info("Getting dashboard data for ride: %s/%s", tour_id, ride_id)

    # Step 1: Get ride details from tour-specific Ride table
    ride = get_tour_item(table_type="Ride", tour_id=tour_id, key={"rideId": ride_id})

    if not ride:
        return not_found_response("Ride", ride_id)

    logger.info("Found ride: %s", ride_id)

    # Step 2: Get all riders from tour-specific TourRider table
    tour_riders = scan_tour_items(table_type="TourRider", tour_id=tour_id)

    logger.info("Found %s riders for tour: %s", len(tour_riders), tour_id)

    # Step 3: Get rider profiles in batch from shared RiderProfile table
    profile_keys = [
        {"profileId": tr["profileId"]} for tr in tour_riders if tr.get("profileId")
    ]
    profiles = (
        batch_get_items("RIDER_PROFILE_TABLE", profile_keys) if profile_keys else []
    )

    # Create profile lookup map
    profile_map = {p.get("profileId"): p for p in profiles}

    # Merge rider data with profiles
    riders_with_profiles = []
    for tr in tour_riders:
        profile_id = tr.get("profileId")
        profile = profile_map.get(profile_id, {})
        emergency_contact = build_emergency_contact_from_profile(profile)

        riders_with_profiles.append(
            {
                "riderId": tr.get("riderId"),
                "profileId": profile_id,
                "status": tr.get("status"),
                "name": profile.get("name"),
                "email": profile.get("email"),
                "phone": profile.get("phone"),
                "emergencyContact": emergency_contact,
                "photoS3Key": profile.get("photoS3Key"),
            }
        )

    # Step 4: Get all check-ins for this ride from tour-specific CheckIn table
    check_ins = query_tour_items(
        table_type="CheckIn",
        tour_id=tour_id,
        key_condition_expression="rideId = :rid",
        expression_values={":rid": ride_id},
    )
    check_ins = [
        checkin for checkin in check_ins if not is_cancelled_checkin_item(checkin)
    ]

    logger.info("Found %s check-ins for ride: %s", len(check_ins), ride_id)

    # Step 5: Calculate summary stats
    rider_ids = {tr.get("riderId") for tr in tour_riders}
    checked_in_riders = set()
    not_riding_riders = set()
    quit_riding_riders = set()

    for checkin in check_ins:
        crid = checkin.get("riderId")
        if checkin.get("isNotRiding"):
            not_riding_riders.add(crid)
        elif checkin.get("isQuitRiding"):
            quit_riding_riders.add(crid)
        else:
            checked_in_riders.add(crid)

    summary = {
        "totalRiders": len(rider_ids),
        "checkedIn": len(checked_in_riders),
        "notRiding": len(not_riding_riders),
        "quitRiding": len(quit_riding_riders),
        "notCheckedIn": len(rider_ids)
        - len(checked_in_riders)
        - len(not_riding_riders)
        - len(quit_riding_riders),
    }

    # Prepare response
    dashboard_data = {
        "ride": ride,
        "riders": riders_with_profiles,
        "checkIns": check_ins,
        "summary": summary,
    }

    # ETag support: compute hash of response data for conditional requests
    data_json = json.dumps(dashboard_data, sort_keys=True, cls=DecimalEncoder)
    etag = f'"{hashlib.md5(data_json.encode()).hexdigest()}"'

    # Check If-None-Match header for conditional request
    request_headers = event.get("headers", {})
    if_none_match = request_headers.get("if-none-match") or request_headers.get(
        "If-None-Match"
    )

    if if_none_match and if_none_match == etag:
        logger.info("ETag match — returning 304 Not Modified for ride: %s", ride_id)
        response = not_modified_response()
        response["headers"]["ETag"] = etag
        return response

    logger.info("Dashboard data prepared successfully for ride: %s", ride_id)
    response = success_response(dashboard_data)
    response["headers"]["ETag"] = etag
    return response
