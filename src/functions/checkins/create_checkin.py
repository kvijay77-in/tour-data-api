"""
Create check-in Lambda function

Handles creating new check-in records including:
- Normal check-ins at stages
- Not Riding (NR) status
- Quit Riding (QR) status
- Manual entry support

Uses tour-specific tables: CheckIn-{tourId}, Ride-{tourId}, TourRider-{tourId}.
Route: POST /v1/tours/{tourId}/checkins
"""

import sys
sys.path.insert(0, '/opt/python')

import json
import uuid
from datetime import datetime

from logger import get_logger, log_event
from response import (
    success_response, error_response, conflict_response,
    bad_request_response, not_found_response, internal_error_response
)
from dynamodb_utils import get_tour_item, query_tour_items, put_tour_item
from validation import (
    validate_rider_id,
    validate_ride_id,
    validate_required_fields,
    validate_tour_id,
    validate_stage_number,
    ValidationError
)
from models import CheckIn, CheckInMethod, RideStatus

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Create a check-in record
    
    Path Parameters:
        tourId: Tour identifier
    
    Body:
        riderId: Rider ID (required)
        rideId: Ride ID (required)
        stageNumber: Stage number (required)
        method: Check-in method (QR_SCAN, MANUAL, FALLBACK)
        isNotRiding: Not Riding flag (default: false)
        isQuitRiding: Quit Riding flag (default: false)
        notes: Optional notes
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
            validate_required_fields(body, ['riderId', 'rideId', 'stageNumber', 'method'])
        except ValidationError as e:
            return bad_request_response(str(e))
        
        rider_id = body['riderId']
        ride_id = body['rideId']
        stage_number = int(body['stageNumber'])
        method = body['method']
        is_not_riding = body.get('isNotRiding', False)
        is_quit_riding = body.get('isQuitRiding', False)
        notes = body.get('notes')
        
        # Validate inputs
        try:
            validate_rider_id(rider_id)
            validate_ride_id(ride_id)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Validate method
        try:
            CheckInMethod(method)
        except ValueError:
            valid_methods = [m.value for m in CheckInMethod]
            return bad_request_response(
                f"Invalid method. Must be one of: {', '.join(valid_methods)}"
            )
        
        logger.info(f"Creating check-in: rider={rider_id}, ride={ride_id}, stage={stage_number}")
        
        # Step 1: Get ride details from tour-specific Ride table
        ride = get_tour_item(
            table_type='Ride',
            tour_id=tour_id,
            key={'PK': f'RIDE#{ride_id}'}
        )
        
        if not ride:
            return not_found_response("Ride", ride_id)
        
        # Check if ride is closed
        if ride.get('status') == RideStatus.CLOSED.value:
            return error_response(
                error_code="RIDE_CLOSED",
                message=f"Ride {ride_id} is closed. No further check-ins allowed.",
                status_code=409
            )
        
        # Validate stage number against ride stages
        stages = ride.get('stages', [])
        total_stages = len(stages)
        
        try:
            validate_stage_number(stage_number, total_stages)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Get stage info
        stage = stages[stage_number - 1]
        stage_id = stage.get('stageId')
        
        # Step 2: Verify rider is registered for this tour
        tour_rider = get_tour_item(
            table_type='TourRider',
            tour_id=tour_id,
            key={'PK': f'RIDER#{rider_id}'}
        )
        
        if not tour_rider:
            return error_response(
                error_code="RIDER_NOT_IN_TOUR",
                message=f"Rider {rider_id} is not registered for this tour",
                status_code=400
            )
        
        # Step 3: Check for existing check-ins (business rules)
        existing_checkins = query_tour_items(
            table_type='CheckIn',
            tour_id=tour_id,
            key_condition_expression='PK = :pk AND begins_with(SK, :sk)',
            expression_values={
                ':pk': f'RIDE#{ride_id}',
                ':sk': f'CHECKIN#{rider_id}#'
            }
        )
        
        # Check for Not Riding conflicts
        if is_not_riding:
            nr_checkins = [c for c in existing_checkins if c.get('isNotRiding')]
            if nr_checkins:
                return conflict_response(
                    f"Rider {rider_id} already marked as Not Riding for this ride"
                )
        
        # Check if rider already marked as Not Riding (can't check in normally)
        if not is_not_riding and not is_quit_riding:
            nr_checkins = [c for c in existing_checkins if c.get('isNotRiding')]
            if nr_checkins:
                return conflict_response(
                    f"Rider {rider_id} is marked as Not Riding. Cannot check in."
                )
        
        # Check if rider already quit (latest check-in has isQuitRiding=true)
        if existing_checkins:
            sorted_checkins = sorted(
                existing_checkins,
                key=lambda x: x.get('timestamp', ''),
                reverse=True
            )
            if sorted_checkins[0].get('isQuitRiding'):
                return conflict_response(
                    f"Rider {rider_id} has quit riding. No further check-ins allowed."
                )
        
        # Step 4: Create check-in record
        timestamp = datetime.utcnow().isoformat() + 'Z'
        check_in_id = str(uuid.uuid4())
        
        # Get checked-in-by from request context (JWT authorizer)
        checked_in_by = event.get('requestContext', {}).get(
            'authorizer', {}
        ).get('jwt', {}).get('claims', {}).get('sub', 'system')
        
        checkin = CheckIn(
            check_in_id=check_in_id,
            rider_id=rider_id,
            ride_id=ride_id,
            stage_number=stage_number,
            stage_id=stage_id,
            timestamp=timestamp,
            checked_in_by=checked_in_by,
            method=CheckInMethod(method),
            is_not_riding=is_not_riding,
            is_quit_riding=is_quit_riding,
            is_manual_entry=(method == CheckInMethod.MANUAL.value),
            notes=notes
        )
        
        # Save to tour-specific CheckIn table
        put_tour_item(
            table_type='CheckIn',
            tour_id=tour_id,
            item=checkin.to_dynamodb_item()
        )
        
        logger.info(f"Check-in created successfully: {check_in_id}")
        return success_response(checkin.to_dict(), status_code=201)
    
    except json.JSONDecodeError:
        return bad_request_response("Invalid JSON in request body")
    except Exception as e:
        logger.error(f"Error creating check-in: {str(e)}", exc_info=True)
        return internal_error_response("Failed to create check-in")
