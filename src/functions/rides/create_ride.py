"""
Lambda function to create a new ride for a tour
"""
import json
import os
import sys
from datetime import datetime

# Add common layer to path
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, error_response, bad_request_response, conflict_response
from validation import validate_tour_id, validate_required_fields, validate_date, validate_stage_number, ValidationError
from dynamodb_utils import get_item, put_item, query_items
from models import RideStatus

logger = get_logger(__name__)

RIDE_TABLE = os.environ['RIDE_TABLE']
TOUR_TABLE = os.environ['TOUR_TABLE']


def lambda_handler(event, context):
    """
    Create a new ride for a tour
    
    Path parameter: tourId (e.g., TOUR2026)
    Body: JSON with ride details
    {
        "rideDate": "2026-06-15",
        "stageNumber": 1,
        "routeName": "Geneva to Lausanne",
        "distanceKm": 65.5,
        "elevationGainM": 450,
        "startLocation": "Geneva Central",
        "endLocation": "Lausanne",
        "startTime": "08:00",
        "estimatedEndTime": "12:00"
    }
    
    Returns:
    - 200: Ride created successfully
    - 400: Invalid input
    - 404: Tour not found
    - 409: Ride already exists for this date/stage
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
            logger.warning(f"Invalid tour ID format: {tour_id}", exc_info=True)
            return bad_request_response(str(e))
        
        # Parse request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")
        
        # Validate required fields
        required_fields = ['rideDate', 'stageNumber', 'routeName', 'distanceKm', 'startLocation', 'endLocation']
        try:
            validate_required_fields(body, required_fields)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Validate individual fields
        try:
            validate_date(body['rideDate'])
            validate_stage_number(body['stageNumber'])
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Validate numeric fields
        if not isinstance(body['distanceKm'], (int, float)) or body['distanceKm'] <= 0:
            return bad_request_response("distanceKm must be a positive number")
        
        if 'elevationGainM' in body:
            if not isinstance(body['elevationGainM'], (int, float)) or body['elevationGainM'] < 0:
                return bad_request_response("elevationGainM must be a non-negative number")
        
        # Check if tour exists
        logger.info(f"Checking if tour exists: {tour_id}")
        tour = get_item(
            table_name=TOUR_TABLE,
            key={'tourId': tour_id}
        )
        
        if not tour:
            return bad_request_response(f"Tour {tour_id} not found")
        
        # Generate ride ID: tourId#rideDate#stageNumber
        ride_id = f"{tour_id}#{body['rideDate']}#{body['stageNumber']}"
        
        # Check if ride already exists
        existing_ride = get_item(
            table_name=RIDE_TABLE,
            key={'tourId': tour_id, 'rideId': ride_id}
        )
        
        if existing_ride:
            logger.info(f"Ride already exists: {ride_id}")
            return conflict_response(f"Ride already exists for {body['rideDate']} stage {body['stageNumber']}")
        
        # Create ride object
        now = datetime.utcnow().isoformat() + 'Z'
        ride = {
            'tourId': tour_id,
            'rideId': ride_id,
            'rideDate': body['rideDate'],
            'stageNumber': body['stageNumber'],
            'routeName': body['routeName'],
            'distanceKm': body['distanceKm'],
            'elevationGainM': body.get('elevationGainM', 0),
            'startLocation': body['startLocation'],
            'endLocation': body['endLocation'],
            'startTime': body.get('startTime'),
            'estimatedEndTime': body.get('estimatedEndTime'),
            'status': RideStatus.SCHEDULED.value,
            'createdAt': now,
            'updatedAt': now
        }
        
        # Save to DynamoDB
        logger.info(f"Creating ride: {ride_id}")
        put_item(table_name=RIDE_TABLE, item=ride)
        
        logger.info(f"Successfully created ride: {ride_id}")
        return success_response(ride)
        
    except Exception as e:
        logger.error(f"Error creating ride: {str(e)}", exc_info=True)
        return error_response(f"Failed to create ride: {str(e)}")
