"""
Lambda function to get today's ride for a tour

Uses tour-specific Ride-{tourId} table with DateIndex GSI.
Route: GET /v1/tours/{tourId}/rides/today
"""

import sys

sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, error_response, bad_request_response, internal_error_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import get_item, query_tour_items
from self_service_policy import build_ride_self_service
from models import utc_today_iso

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get today's ride for a tour
    
    Path parameter: tourId (e.g., TOT-2026)
    
    Returns:
    - 200: Today's ride found, with the calculated read-only ``selfService`` permissions
    - 400: Invalid tour ID
    - 404: No ride scheduled for today
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
        
        # Get today's date in ISO format (UTC-aware)
        today = utc_today_iso()
        
        # Query rides for today using DateIndex GSI
        logger.info(f"Querying rides for tour {tour_id} on {today}")
        rides = query_tour_items(
            table_type='Ride',
            tour_id=tour_id,
            key_condition_expression='#date = :date',
            expression_values={':date': today},
            expression_names={'#date': 'date'},
            index_name='DateIndex'
        )
        
        if not rides:
            logger.info(f"No ride found for tour {tour_id} on {today}")
            return error_response(
                error_code="NO_ACTIVE_RIDE",
                message="No active ride found for today",
                status_code=404
            )
        
        # Return first ride for today
        todays_ride = rides[0]
        tour = get_item(table_name_env='TOUR_MASTER_TABLE', key={'tourId': tour_id})
        todays_ride['selfService'] = build_ride_self_service(todays_ride, tour)
        
        logger.info(f"Successfully retrieved today's ride: {todays_ride.get('rideId')}")
        return success_response(todays_ride)
        
    except Exception as e:
        logger.error(f"Error getting today's ride: {str(e)}", exc_info=True)
        return internal_error_response("Failed to get today's ride")
