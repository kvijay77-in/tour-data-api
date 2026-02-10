"""
Lambda function to close a ride (mark as completed)
"""
import json
import os
import sys
from datetime import datetime

# Add common layer to path
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, error_response, bad_request_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import get_item, put_item
from models import RideStatus

logger = get_logger(__name__)

RIDE_TABLE = os.environ['RIDE_TABLE']


def lambda_handler(event, context):
    """
    Close a ride (mark it as CLOSED)
    Once a ride is closed, no more check-ins can be created for it.
    
    Path parameters:
    - tourId (e.g., TOUR2026)
    - rideId (e.g., TOUR2026#2026-06-15#1)
    
    Returns:
    - 200: Ride closed successfully
    - 400: Invalid input or ride already closed
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
        
        # Get existing ride
        logger.info(f"Fetching ride to close: {ride_id}")
        ride = get_item(
            table_name=RIDE_TABLE,
            key={'tourId': tour_id, 'rideId': ride_id}
        )
        
        if not ride:
            logger.info(f"Ride not found: {ride_id}")
            return not_found_response(f"Ride {ride_id} not found")
        
        # Check if ride is already closed
        if ride.get('status') == RideStatus.CLOSED.value:
            logger.info(f"Ride already closed: {ride_id}")
            return bad_request_response("Ride is already closed")
        
        # Close the ride
        ride['status'] = RideStatus.CLOSED.value
        ride['closedAt'] = datetime.utcnow().isoformat() + 'Z'
        ride['updatedAt'] = datetime.utcnow().isoformat() + 'Z'
        
        logger.info(f"Closing ride: {ride_id}")
        put_item(table_name=RIDE_TABLE, item=ride)
        
        logger.info(f"Successfully closed ride: {ride_id}")
        return success_response(ride)
        
    except Exception as e:
        logger.error(f"Error closing ride: {str(e)}", exc_info=True)
        return error_response(f"Failed to close ride: {str(e)}")
