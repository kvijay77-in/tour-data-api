"""
Get dashboard data Lambda function

This function retrieves all data needed for the Check-In App dashboard:
- Ride details with stages
- All tour riders with profile data
- All check-ins for the ride
- Summary statistics
"""

import sys
sys.path.insert(0, '/opt/python')

from logger import get_logger, log_event
from response import success_response, not_found_response, internal_error_response, error_response
from dynamodb_utils import get_item, query_items, batch_get_items
from validation import validate_ride_id, ValidationError
from models import CheckInStatus

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get complete dashboard data for a ride
    
    Path Parameters:
        rideId: Ride identifier (e.g., RIDE001)
    """
    try:
        log_event(logger, event)
        
        # Extract ride ID from path parameters
        ride_id = event.get('pathParameters', {}).get('rideId')
        
        if not ride_id:
            return error_response(
                error_code="MISSING_PARAMETER",
                message="Missing required parameter: rideId",
                status_code=400
            )
        
        # Validate ride ID format
        try:
            validate_ride_id(ride_id)
        except ValidationError as e:
            return error_response(
                error_code="VALIDATION_ERROR",
                message=str(e),
                status_code=400,
                details=e.details
            )
        
        logger.info(f"Getting dashboard data for ride: {ride_id}")
        
        # Step 1: Get ride details
        # Note: We need to query since we only have rideId, not the PK (tourId)
        rides = query_items(
            table_name_env='RIDE_TABLE',
            key_condition_expression='SK = :sk',
            expression_values={':sk': f"RIDE#{ride_id}"},
            index_name='RideIdIndex'  # Note: This would require adding a GSI
        )
        
        if not rides:
            return not_found_response("Ride", ride_id)
        
        ride = rides[0]
        tour_id = ride.get('tourId')
        
        logger.info(f"Found ride: {ride_id} for tour: {tour_id}")
        
        # Step 2: Get all riders for this tour
        tour_riders = query_items(
            table_name_env='TOUR_RIDER_TABLE',
            key_condition_expression='PK = :pk',
            expression_values={':pk': f"TOUR#{tour_id}"}
        )
        
        logger.info(f"Found {len(tour_riders)} riders for tour: {tour_id}")
        
        # Step 3: Get rider profiles in batch
        profile_keys = [{'PK': f"PROFILE#{tr['profileId']}"} for tr in tour_riders]
        profiles = batch_get_items('RIDER_PROFILE_TABLE', profile_keys) if profile_keys else []
        
        # Create profile lookup map
        profile_map = {p['profileId']: p for p in profiles}
        
        # Merge rider data with profiles
        riders_with_profiles = []
        for tr in tour_riders:
            profile_id = tr.get('profileId')
            profile = profile_map.get(profile_id, {})
            
            riders_with_profiles.append({
                'riderId': tr.get('riderId'),
                'tourId': tr.get('tourId'),
                'profileId': profile_id,
                'status': tr.get('status'),
                'name': profile.get('name'),
                'email': profile.get('email'),
                'phone': profile.get('phone'),
                'emergencyContactName': profile.get('emergencyContactName'),
                'emergencyContactPhone': profile.get('emergencyContactPhone'),
                'photoS3Key': profile.get('photoS3Key')
            })
        
        # Step 4: Get all check-ins for this ride
        check_ins = query_items(
            table_name_env='CHECKIN_TABLE',
            key_condition_expression='PK = :pk',
            expression_values={':pk': f"RIDE#{ride_id}"}
        )
        
        logger.info(f"Found {len(check_ins)} check-ins for ride: {ride_id}")
        
        # Step 5: Calculate summary stats
        rider_ids = {tr['riderId'] for tr in tour_riders}
        checked_in_riders = set()
        not_riding_riders = set()
        quit_riding_riders = set()
        
        for checkin in check_ins:
            rider_id = checkin.get('riderId')
            if checkin.get('isNotRiding'):
                not_riding_riders.add(rider_id)
            elif checkin.get('isQuitRiding'):
                quit_riding_riders.add(rider_id)
            else:
                checked_in_riders.add(rider_id)
        
        summary = {
            'totalRiders': len(rider_ids),
            'checkedIn': len(checked_in_riders),
            'notRiding': len(not_riding_riders),
            'quitRiding': len(quit_riding_riders),
            'notCheckedIn': len(rider_ids) - len(checked_in_riders) - len(not_riding_riders) - len(quit_riding_riders)
        }
        
        # Prepare response
        dashboard_data = {
            'ride': ride,
            'riders': riders_with_profiles,
            'checkIns': check_ins,
            'summary': summary
        }
        
        logger.info(f"Dashboard data prepared successfully for ride: {ride_id}")
        return success_response(dashboard_data)
    
    except Exception as e:
        logger.error(f"Error getting dashboard data: {str(e)}", exc_info=True)
        return internal_error_response("Failed to retrieve dashboard data")
