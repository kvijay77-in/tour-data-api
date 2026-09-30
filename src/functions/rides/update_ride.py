"""
Lambda function to update a ride

Uses tour-specific Ride-{tourId} table.
Route: PUT /v1/tours/{tourId}/rides/{rideId}
"""

import json
import sys

sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, bad_request_response, internal_error_response
from validation import (
    validate_tour_id, validate_ride_id, validate_iso_date,
    validate_time_hhmm, validate_ride_stages, validate_ride_floats, ValidationError
)
from dynamodb_utils import get_tour_item, put_tour_item
from models import RideStatus, utc_now_iso
from rbac import require_permission, Permission

logger = get_logger(__name__)


def _merge_stage_runtime_fields(existing_stages, updated_stages):
    """Preserve system-managed pit-stop runtime fields during stage updates."""
    existing_stages_by_id = {
        stage.get('stageId'): stage for stage in (existing_stages or []) if stage.get('stageId')
    }

    merged_stages = []
    for stage in updated_stages:
        existing_stage = existing_stages_by_id.get(stage.get('stageId'), {})
        merged_stage = dict(stage)
        for field_name in ('pitStopStatus', 'openedAt', 'closedAt'):
            if existing_stage.get(field_name) is not None:
                merged_stage[field_name] = existing_stage[field_name]
        merged_stages.append(merged_stage)
    return merged_stages


def lambda_handler(event, context):
    """
    Update a ride's details
    
    Path parameters:
    - tourId: Tour identifier (e.g., TOT-2026)
    - rideId: Ride identifier (e.g., RIDE001)
    
    Body: JSON with fields to update
    
    Returns:
    - 200: Ride updated successfully
    - 400: Invalid input
    - 404: Ride not found
    - 500: Server error
    """
    try:
        # Enforce RBAC — only RIDE_MANAGE permission may update rides
        deny = require_permission(event, Permission.RIDE_MANAGE)
        if deny:
            return deny

        # Extract path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        ride_id = event.get('pathParameters', {}).get('rideId')
        
        if not tour_id or not ride_id:
            return bad_request_response("tourId and rideId are required in path")
        
        # Validate IDs
        try:
            validate_tour_id(tour_id)
            validate_ride_id(ride_id)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Parse request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")
        
        # Get existing ride
        logger.info(f"Fetching existing ride: {tour_id}/{ride_id}")
        existing_ride = get_tour_item(
            table_type='Ride',
            tour_id=tour_id,
            key={'rideId': ride_id}
        )
        
        if not existing_ride:
            return not_found_response("Ride", ride_id)
        
        # Validate updatable fields
        updatable_fields = [
            'name', 'date', 'rideNo', 'startLocation', 'finishLocation',
            'totalDistance', 'flagOffTime', 'stages', 'floats', 'description', 'status',
            'openTime', 'closeTime'
            , 'selfQuitRidingAllowed', 'selfCheckInAllowed'
        ]
        updates = {k: v for k, v in body.items() if k in updatable_fields}
        
        if not updates:
            return bad_request_response("No valid fields to update")
        
        # Validate date if provided
        if 'date' in updates:
            try:
                validate_iso_date(updates['date'], 'date')
            except ValidationError as e:
                return bad_request_response(str(e))
        
        # Validate numeric fields if provided
        if 'totalDistance' in updates:
            if not isinstance(updates['totalDistance'], (int, float)) or updates['totalDistance'] <= 0:
                return bad_request_response("totalDistance must be a positive number")
        
        # Validate flagOffTime if provided
        if 'flagOffTime' in updates:
            try:
                validate_time_hhmm(updates['flagOffTime'], 'flagOffTime')
            except ValidationError as e:
                return bad_request_response(str(e))

        if 'openTime' in updates and updates['openTime'] is not None:
            try:
                validate_time_hhmm(updates['openTime'], 'openTime')
            except ValidationError as e:
                return bad_request_response(str(e))

        if 'closeTime' in updates and updates['closeTime'] is not None:
            try:
                validate_time_hhmm(updates['closeTime'], 'closeTime')
            except ValidationError as e:
                return bad_request_response(str(e))
        
        # Validate status if provided
        if 'status' in updates:
            valid_statuses = [s.value for s in RideStatus]
            if updates['status'] not in valid_statuses:
                return bad_request_response(
                    f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                )

        for field_name in ('selfQuitRidingAllowed', 'selfCheckInAllowed'):
            if field_name in updates and not isinstance(updates[field_name], bool):
                return bad_request_response(f"{field_name} must be a boolean")

        if 'stages' in updates:
            try:
                normalized_stages = validate_ride_stages(updates['stages'])
            except ValidationError as e:
                return bad_request_response(str(e))
            updates['stages'] = _merge_stage_runtime_fields(
                existing_ride.get('stages', []),
                normalized_stages
            )

        if 'floats' in updates:
            stages_for_float_validation = updates.get('stages', existing_ride.get('stages', []))
            try:
                updates['floats'] = validate_ride_floats(updates['floats'], len(stages_for_float_validation))
            except ValidationError as e:
                return bad_request_response(str(e))
        
        # Update ride
        updated_ride = {**existing_ride, **updates}
        updated_ride['updatedAt'] = utc_now_iso()
        
        logger.info(f"Updating ride: {ride_id}")
        put_tour_item(table_type='Ride', tour_id=tour_id, item=updated_ride)
        
        logger.info(f"Successfully updated ride: {ride_id}")
        return success_response(updated_ride)
        
    except Exception as e:
        logger.error(f"Error updating ride: {str(e)}", exc_info=True)
        return internal_error_response("Failed to update ride")
