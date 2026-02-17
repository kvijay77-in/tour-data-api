"""
Lambda function to create a new ride for a tour

Uses tour-specific Ride-{tourId} table and shared Tour table.
Route: POST /v1/tours/{tourId}/rides
"""

import json
import sys
from datetime import datetime

sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import (
    success_response, bad_request_response, conflict_response,
    not_found_response, internal_error_response
)
from validation import (
    validate_tour_id, validate_required_fields, validate_iso_date,
    ValidationError
)
from dynamodb_utils import get_item, get_tour_item, put_tour_item
from models import RideStatus, TourStatus

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Create a new ride for a tour
    
    Path parameter: tourId (e.g., India-Coast-2026)
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
        "description": "Optional description"
    }
    
    Returns:
    - 201: Ride created successfully
    - 400: Invalid input
    - 404: Tour not found
    - 409: Ride already exists
    - 500: Server error
    """
    try:
        # Extract tour ID from path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        
        if not tour_id:
            return bad_request_response("tourId is required in path")
        
        # Validate tour ID
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
        required_fields = ['rideId', 'date', 'rideNo', 'name', 'startLocation', 'finishLocation', 'totalDistance', 'flagOffTime', 'stages']
        try:
            validate_required_fields(body, required_fields)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Validate date
        try:
            validate_iso_date(body['date'], 'date')
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Validate numeric fields
        if not isinstance(body['totalDistance'], (int, float)) or body['totalDistance'] <= 0:
            return bad_request_response("totalDistance must be a positive number")
        
        if not isinstance(body['rideNo'], int) or body['rideNo'] < 1:
            return bad_request_response("rideNo must be a positive integer")
        
        # Validate stages
        if not isinstance(body['stages'], list) or len(body['stages']) == 0:
            return bad_request_response("stages must be a non-empty array")
        
        # Check if tour exists and is in the right status
        logger.info(f"Checking if tour exists: {tour_id}")
        tour = get_item(
            table_name_env='TOUR_TABLE',
            key={'PK': f'TOUR#{tour_id}'}
        )
        
        if not tour:
            return not_found_response("Tour", tour_id)
        
        tour_status = tour.get('status')
        if tour_status not in [TourStatus.PLANNING.value, TourStatus.ACTIVE.value]:
            return bad_request_response(
                f"Cannot create rides for tour in {tour_status} status. "
                "Tour must be in PLANNING or ACTIVE status."
            )
        
        ride_id = body['rideId']
        
        # Check if ride already exists
        existing_ride = get_tour_item(
            table_type='Ride',
            tour_id=tour_id,
            key={'PK': f'RIDE#{ride_id}'}
        )
        
        if existing_ride:
            return conflict_response(f"Ride '{ride_id}' already exists in tour '{tour_id}'")
        
        # Create ride object
        now = datetime.utcnow().isoformat() + 'Z'
        ride = {
            'PK': f'RIDE#{ride_id}',
            'rideId': ride_id,
            'date': body['date'],
            'rideNo': body['rideNo'],
            'name': body['name'],
            'startLocation': body['startLocation'],
            'finishLocation': body['finishLocation'],
            'totalDistance': body['totalDistance'],
            'flagOffTime': body['flagOffTime'],
            'stages': body['stages'],
            'status': RideStatus.PLANNED.value,
            'description': body.get('description'),
            'createdAt': now,
            'updatedAt': now
        }
        
        # Remove None values
        ride = {k: v for k, v in ride.items() if v is not None}
        
        # Save to tour-specific Ride table
        logger.info(f"Creating ride: {ride_id} in tour {tour_id}")
        put_tour_item(table_type='Ride', tour_id=tour_id, item=ride)
        
        logger.info(f"Successfully created ride: {ride_id}")
        return success_response(ride, status_code=201)
        
    except Exception as e:
        logger.error(f"Error creating ride: {str(e)}", exc_info=True)
        return internal_error_response("Failed to create ride")
