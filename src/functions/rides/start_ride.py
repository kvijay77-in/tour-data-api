"""
Lambda function to mark today's ride as STARTED for a tour.

Uses tour-specific Ride-{tourId} table with DateIndex GSI.
Route: POST /v1/tours/{tourId}/rides/start
"""

import sys

sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, error_response, bad_request_response, internal_error_response
from validation import validate_tour_id, ValidationError
from dynamodb_utils import query_tour_items, put_tour_item
from models import utc_today_iso, utc_now_iso
from notification_service import notify
from rbac import require_permission, Permission

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Update today's ride status to STARTED.

    Path parameters:
    - tourId: Tour identifier (e.g., TOT-2026)

    Returns:
    - 200: Today's ride marked as STARTED successfully
    - 400: Invalid input or ride already STARTED
    - 404: No ride found for today
    - 500: Server error
    """
    try:
        # Enforce RBAC - only RIDE_MANAGE permission may start rides
        deny = require_permission(event, Permission.RIDE_MANAGE)
        if deny:
            return deny

        # Extract and validate path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        if not tour_id:
            return bad_request_response("tourId is required in path")

        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        # Resolve today's ride using DateIndex
        today = utc_today_iso()
        logger.info(f"Finding today's ride for start operation: {tour_id} on {today}")
        rides = query_tour_items(
            table_type='Ride',
            tour_id=tour_id,
            key_condition_expression='#date = :date',
            expression_values={':date': today},
            expression_names={'#date': 'date'},
            index_name='DateIndex'
        )

        if not rides:
            return error_response(
                error_code="NO_ACTIVE_RIDE",
                message="No ride found for today",
                status_code=404
            )

        # Keep behavior aligned with existing get_todays_ride endpoint
        ride = rides[0]
        if ride.get('status') == 'STARTED':
            return bad_request_response("Today's ride is already STARTED")

        now = utc_now_iso()
        ride['status'] = 'STARTED'
        ride['startedAt'] = now
        ride['updatedAt'] = now

        logger.info(f"Starting today's ride: {ride.get('rideId')}")
        put_tour_item(table_type='Ride', tour_id=tour_id, item=ride)

        logger.info(f"Successfully started today's ride: {ride.get('rideId')}")
        notify(
            rule_id='RIDE_STARTED',
            tour_id=tour_id,
            context={'rideId': ride.get('rideId'), 'rideName': ride.get('name', '')},
            actor=event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {}).get('sub'),
        )
        return success_response(ride)

    except Exception as e:
        logger.error(f"Error starting today's ride: {str(e)}", exc_info=True)
        return internal_error_response("Failed to start today's ride")
