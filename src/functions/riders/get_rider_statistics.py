"""
Get rider statistics Lambda function

Computes aggregated statistics for a rider's tour participation
from existing check-in and ride data.
Route: GET /v1/tours/{tourId}/riders/{riderId}/statistics
"""

import sys

from logger import get_logger, log_event
from response import (
    success_response, bad_request_response, not_found_response,
    internal_error_response
)
from dynamodb_utils import get_tour_item, scan_tour_items, query_tour_items
from validation import (
    validate_tour_id, validate_rider_id, ValidationError
)

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get aggregated statistics for a rider in a tour

    Path Parameters:
        tourId: Tour identifier
        riderId: Rider identifier

    Returns:
    - 200: Rider statistics
    - 400: Invalid input
    - 404: Rider not found in tour
    - 500: Server error
    """
    try:
        log_event(logger, event)

        # Extract path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        rider_id = event.get('pathParameters', {}).get('riderId')

        if not tour_id:
            return bad_request_response("tourId is required in path")
        if not rider_id:
            return bad_request_response("riderId is required in path")

        try:
            validate_tour_id(tour_id)
            validate_rider_id(rider_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        # Verify rider is registered for the tour
        tour_rider = get_tour_item(
            table_type='TourRider',
            tour_id=tour_id,
            key={'riderId': rider_id}
        )

        if not tour_rider:
            return not_found_response("TourRider", rider_id)

        logger.info("Computing statistics for rider %s in tour %s", rider_id, tour_id)

        # Get all rides for the tour
        all_rides = scan_tour_items(
            table_type='Ride',
            tour_id=tour_id
        )

        # Get all check-ins for this rider using RiderIdIndex
        rider_checkins = query_tour_items(
            table_type='CheckIn',
            tour_id=tour_id,
            key_condition_expression='riderId = :rid',
            expression_values={':rid': rider_id},
            index_name='RiderIdIndex'
        )

        # Compute statistics
        total_rides = len(all_rides)
        completed_rides = set()
        not_riding_rides = set()
        quit_riding = False
        total_distance = 0.0
        total_checkins = 0

        # Build ride lookup for distance info
        ride_lookup = {ride['rideId']: ride for ride in all_rides}

        # Build set of completed rides (those with status COMPLETED or CLOSED)
        completed_ride_ids = {
            ride['rideId'] for ride in all_rides
            if ride.get('status') in ['COMPLETED', 'CLOSED']
        }

        for checkin in rider_checkins:
            ride_id = checkin.get('rideId')

            if checkin.get('isQuitRiding'):
                quit_riding = True
                continue

            if checkin.get('isNotRiding'):
                not_riding_rides.add(ride_id)
                continue

            # Normal check-in
            total_checkins += 1
            completed_rides.add(ride_id)

        # Calculate total distance from rides the rider completed
        for ride_id in completed_rides:
            ride = ride_lookup.get(ride_id)
            if ride:
                distance = ride.get('totalDistance', 0)
                try:
                    total_distance += float(distance)
                except (ValueError, TypeError):
                    pass

        # Calculate current streak (consecutive rides completed)
        sorted_rides = sorted(all_rides, key=lambda r: r.get('date', ''))
        current_streak = 0
        for ride in sorted_rides:
            ride_id = ride['rideId']
            if ride_id not in completed_ride_ids:
                continue
            if ride_id in completed_rides:
                current_streak += 1
            elif ride_id in not_riding_rides:
                current_streak = 0
            else:
                # Ride not yet completed by anyone, stop counting
                break

        rides_completed = len(completed_rides)
        rides_not_completed = len(not_riding_rides)

        statistics = {
            'riderId': rider_id,
            'tourId': tour_id,
            'totalRides': total_rides,
            'ridesCompleted': rides_completed,
            'ridesNotCompleted': rides_not_completed,
            'currentStreak': current_streak,
            'totalDistance': round(total_distance, 2),
            'totalCheckins': total_checkins,
            'quitRiding': quit_riding
        }

        logger.info("Statistics computed for rider %s: %s rides completed", rider_id, rides_completed)
        return success_response(statistics)

    except Exception as e:
        logger.error("Error computing rider statistics: %s", e, exc_info=True)
        return internal_error_response("Failed to compute rider statistics")
