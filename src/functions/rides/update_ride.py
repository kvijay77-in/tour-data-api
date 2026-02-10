"""
Lambda function to update a ride
"""
import json
import os
import sys
from datetime import datetime

# Add common layer to path
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, error_response, bad_request_response
from validation import validate_tour_id, validate_date, ValidationError
from dynamodb_utils import get_item, put_item
from models import RideStatus

logger = get_logger(__name__)

RIDE_TABLE = os.environ['RIDE_TABLE']


def lambda_handler(event, context):
    """
    Update a ride's details
    
    Path parameters:
    - tourId (e.g., TOUR2026)
    - rideId (e.g., TOUR2026#2026-06-15#1)
    
    Body: JSON with fields to update
    {
        "routeName": "Updated Route Name",
        "distanceKm": 70.5,
        "elevationGainM": 500,
        "startTime": "07:30",
        "estimatedEndTime": "11:30",
        "status": "ACTIVE"
    }
    
    Returns:
    - 200: Ride updated successfully
    - 400: Invalid input
    - 404: Ride not found
    - 500: Server error
    """
    try:
        # Extract path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        ride_id = event.get('pathParameters', {}).get('rideId')
        
        if not tour_id or not ride_id:
            return bad_request_response("tourId and rideId are required in path")
        
        # Validate tour ID
        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            logger.warning(f"Invalid tour ID format: {tour_id}", exc_info=True)
            return bad_request_response(str(e))
        
        # Parse request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")
        
        # Get existing ride
        logger.info(f"Fetching existing ride: {ride_id}")
        existing_ride = get_item(
            table_name=RIDE_TABLE,
            key={'tourId': tour_id, 'rideId': ride_id}
        )
        
        if not existing_ride:
            logger.info(f"Ride not found: {ride_id}")
            return not_found_response(f"Ride {ride_id} not found")
        
        # Validate updatable fields
        updatable_fields = [
            'routeName', 'distanceKm', 'elevationGainM', 
            'startLocation', 'endLocation', 'startTime', 
            'estimatedEndTime', 'status'
        ]
        updates = {k: v for k, v in body.items() if k in updatable_fields}
        
        if not updates:
            return bad_request_response("No valid fields to update")
        
        # Validate numeric fields if provided
        if 'distanceKm' in updates:
            if not isinstance(updates['distanceKm'], (int, float)) or updates['distanceKm'] <= 0:
                return bad_request_response("distanceKm must be a positive number")
        
        if 'elevationGainM' in updates:
            if not isinstance(updates['elevationGainM'], (int, float)) or updates['elevationGainM'] < 0:
                return bad_request_response("elevationGainM must be a non-negative number")
        
        # Validate status if provided
        if 'status' in updates:
            valid_statuses = [s.value for s in RideStatus]
            if updates['status'] not in valid_statuses:
                return bad_request_response(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        
        # Update ride
        updated_ride = {**existing_ride, **updates}
        updated_ride['updatedAt'] = datetime.utcnow().isoformat() + 'Z'
        
        logger.info(f"Updating ride: {ride_id}")
        put_item(table_name=RIDE_TABLE, item=updated_ride)
        
        logger.info(f"Successfully updated ride: {ride_id}")
        return success_response(updated_ride)
        
    except Exception as e:
        logger.error(f"Error updating ride: {str(e)}", exc_info=True)
        return error_response(f"Failed to update ride: {str(e)}")
