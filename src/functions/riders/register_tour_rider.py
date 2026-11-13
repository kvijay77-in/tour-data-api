"""
Register tour rider Lambda function

Allows a rider to submit a tour registration request.
The registration starts in PENDING status and requires organizer approval.
Route: POST /v1/tours/{tourId}/riders
"""

import sys

import json

from logger import get_logger, log_event
from response import (
    success_response, bad_request_response, not_found_response,
    conflict_response, internal_error_response
)
from dynamodb_utils import get_item, get_tour_item, put_tour_item, query_tour_items
from validation import (
    validate_tour_id, validate_required_fields, ValidationError
)
from models import TourRiderStatus, TourStatus, utc_now_iso

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Register a rider for a tour (rider-initiated)

    Path Parameters:
        tourId: Tour identifier

    Body:
        profileId: Rider's profile ID (required)
        riderId: Rider ID assigned by organizer (optional, may be assigned later)
        experienceLevel: Cycling experience level (optional)
        medicalConditions: Medical conditions/allergies (optional)
        specialRequirements: Dietary, accommodation preferences (optional)

    Returns:
    - 201: Registration request submitted
    - 400: Invalid input
    - 404: Tour or profile not found
    - 409: Already registered
    - 500: Server error
    """
    try:
        log_event(logger, event)

        # Extract tour ID from path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')

        if not tour_id:
            return bad_request_response("tourId is required in path")

        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        # Parse request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")

        # Validate required fields
        try:
            validate_required_fields(body, ['profileId'])
        except ValidationError as e:
            return bad_request_response(str(e))

        profile_id = body['profileId']

        # Verify tour exists and is in a registerable status
        tour = get_item(
            table_name_env='TOUR_MASTER_TABLE',
            key={'tourId': tour_id}
        )

        if not tour:
            return not_found_response("Tour", tour_id)

        tour_status = tour.get('status')
        if tour_status not in [TourStatus.PLANNING.value, TourStatus.ACTIVE.value]:
            return bad_request_response(
                f"Tour '{tour_id}' is not accepting registrations (status: {tour_status})"
            )

        # Verify rider profile exists
        profile = get_item(
            table_name_env='RIDER_PROFILE_TABLE',
            key={'profileId': profile_id}
        )

        if not profile:
            return not_found_response("RiderProfile", profile_id)

        # Check if rider is already registered for this tour (by profileId)
        existing = query_tour_items(
            table_type='TourRider',
            tour_id=tour_id,
            key_condition_expression='profileId = :pid',
            expression_values={':pid': profile_id},
            index_name='ProfileIdIndex',
            limit=1
        )

        if existing:
            return conflict_response(
                f"Rider with profile '{profile_id}' is already registered for tour '{tour_id}'",
                error_code="ALREADY_REGISTERED"
            )

        now = utc_now_iso()
        rider_id = body.get('riderId', '')

        item = {
            'profileId': profile_id,
            'status': TourRiderStatus.PENDING.value,
            'registeredAt': now,
            'createdAt': now,
            'updatedAt': now
        }

        # Use provided riderId or generate a temporary placeholder
        if rider_id:
            item['riderId'] = rider_id
        else:
            # Use profileId as temporary key; organizer assigns riderId upon approval
            item['riderId'] = f"PENDING-{profile_id[:8]}"

        # Optional registration fields
        if body.get('experienceLevel'):
            item['experienceLevel'] = body['experienceLevel']
        if body.get('medicalConditions'):
            item['medicalConditions'] = body['medicalConditions']
        if body.get('specialRequirements'):
            item['specialRequirements'] = body['specialRequirements']

        logger.info("Registering rider %s for tour %s", profile_id, tour_id)
        put_tour_item(
            table_type='TourRider',
            tour_id=tour_id,
            item=item
        )

        logger.info("Successfully registered rider %s for tour %s", profile_id, tour_id)
        return success_response(item, status_code=201)

    except Exception as e:
        logger.error("Error registering tour rider: %s", e, exc_info=True)
        return internal_error_response("Failed to register tour rider")
