"""
Lambda function to close a ride (mark as completed)

Uses tour-specific Ride-{tourId} table.
Route: POST /v1/tours/{tourId}/rides/{rideId}/close
"""

import sys

from logger import get_logger
from response import success_response, not_found_response, bad_request_response, internal_error_response
from validation import validate_tour_id, validate_ride_id, ValidationError
from dynamodb_utils import get_tour_item, put_tour_item
from models import RideStatus, utc_now_iso
from notification_service import notify
from rbac import require_permission, Permission


sys.path.insert(0, '/opt/python')
logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Close a ride (mark it as CLOSED)
    Once a ride is closed, no more check-ins can be created for it.
    
    Path parameters:
    - tourId: Tour identifier (e.g., TOT-2026)
    - rideId: Ride identifier (e.g., RIDE001)
    
    Returns:
    - 200: Ride closed successfully
    - 400: Invalid input or ride already closed
    - 404: Ride not found
    - 500: Server error
    """
    try:
        # Enforce RBAC — only RIDE_MANAGE permission may close rides
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
        
        # Get existing ride from tour-specific table
        logger.info("Fetching ride to close: %s/%s", tour_id, ride_id)
        ride = get_tour_item(
            table_type='Ride',
            tour_id=tour_id,
            key={'rideId': ride_id}
        )
        
        if not ride:
            return not_found_response("Ride", ride_id)
        
        # Check if ride is already closed
        if ride.get('status') == RideStatus.CLOSED.value:
            return bad_request_response("Ride is already closed")
        
        # Close the ride
        now = utc_now_iso()
        ride['status'] = RideStatus.CLOSED.value
        ride['closedAt'] = now
        ride['updatedAt'] = now
        
        logger.info("Closing ride: %s", ride_id)
        put_tour_item(table_type='Ride', tour_id=tour_id, item=ride)
        
        logger.info("Successfully closed ride: %s", ride_id)
        notify(
            rule_id='RIDE_CLOSED',
            tour_id=tour_id,
            context={'rideId': ride_id, 'rideName': ride.get('name', '')},
            actor=event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {}).get('sub'),
        )
        return success_response(ride)
        
    except Exception as e:
        logger.error("Error closing ride: %s", e, exc_info=True)
        return internal_error_response("Failed to close ride")
