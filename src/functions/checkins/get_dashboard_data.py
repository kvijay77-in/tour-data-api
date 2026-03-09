"""
Get dashboard data Lambda function

Retrieves all data needed for the Check-In App dashboard:
- Ride details with stages
- All tour riders with profile data
- All check-ins for the ride
- Summary statistics
- ETag support for conditional requests (304 Not Modified)

Uses tour-specific tables: Ride-{tourId}, TourRider-{tourId}, CheckIn-{tourId}
and shared RiderProfile table.
Route: GET /v1/tours/{tourId}/rides/{rideId}/dashboard
"""

import sys
sys.path.insert(0, '/opt/python')

import hashlib
import json

from logger import get_logger, log_event
from response import (
    success_response, not_found_response, bad_request_response,
    internal_error_response, not_modified_response, DecimalEncoder
)
from dynamodb_utils import (
    get_tour_item, query_tour_items, scan_tour_items, batch_get_items
)
from validation import validate_tour_id, validate_ride_id, ValidationError
from rbac import require_groups, ADMINISTRATOR, SUPER_USER, PIT_STOP_CREW, GUEST

logger = get_logger(__name__)


def lambda_handler(event, context):
    """
    Get complete dashboard data for a ride
    
    Path Parameters:
        tourId: Tour identifier (e.g., TOT-2026)
        rideId: Ride identifier (e.g., RIDE001)
    """
    try:
        log_event(logger, event)
        
        # Enforce RBAC — HOTEL_STAFF may not access dashboard data
        deny = require_groups(event, [ADMINISTRATOR, SUPER_USER, PIT_STOP_CREW, GUEST])
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
        
        logger.info(f"Getting dashboard data for ride: {tour_id}/{ride_id}")
        
        # Step 1: Get ride details from tour-specific Ride table
        ride = get_tour_item(
            table_type='Ride',
            tour_id=tour_id,
            key={'rideId': ride_id}
        )
        
        if not ride:
            return not_found_response("Ride", ride_id)
        
        logger.info(f"Found ride: {ride_id}")
        
        # Step 2: Get all riders from tour-specific TourRider table
        tour_riders = scan_tour_items(
            table_type='TourRider',
            tour_id=tour_id
        )
        
        logger.info(f"Found {len(tour_riders)} riders for tour: {tour_id}")
        
        # Step 3: Get rider profiles in batch from shared RiderProfile table
        profile_keys = [
            {'profileId': tr['profileId']}
            for tr in tour_riders
            if tr.get('profileId')
        ]
        profiles = batch_get_items('RIDER_PROFILE_TABLE', profile_keys) if profile_keys else []
        
        # Create profile lookup map
        profile_map = {p.get('profileId'): p for p in profiles}
        
        # Merge rider data with profiles
        riders_with_profiles = []
        for tr in tour_riders:
            profile_id = tr.get('profileId')
            profile = profile_map.get(profile_id, {})
            
            riders_with_profiles.append({
                'riderId': tr.get('riderId'),
                'profileId': profile_id,
                'status': tr.get('status'),
                'name': profile.get('name'),
                'email': profile.get('email'),
                'phone': profile.get('phone'),
                'emergencyContactName': profile.get('emergencyContactName'),
                'emergencyContactPhone': profile.get('emergencyContactPhone'),
                'photoS3Key': profile.get('photoS3Key')
            })
        
        # Step 4: Get all check-ins for this ride from tour-specific CheckIn table
        check_ins = query_tour_items(
            table_type='CheckIn',
            tour_id=tour_id,
            key_condition_expression='rideId = :rid',
            expression_values={':rid': ride_id}
        )
        
        logger.info(f"Found {len(check_ins)} check-ins for ride: {ride_id}")
        
        # Step 5: Calculate summary stats
        rider_ids = {tr.get('riderId') for tr in tour_riders}
        checked_in_riders = set()
        not_riding_riders = set()
        quit_riding_riders = set()
        
        for checkin in check_ins:
            crid = checkin.get('riderId')
            if checkin.get('isNotRiding'):
                not_riding_riders.add(crid)
            elif checkin.get('isQuitRiding'):
                quit_riding_riders.add(crid)
            else:
                checked_in_riders.add(crid)
        
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
        
        # ETag support: compute hash of response data for conditional requests
        data_json = json.dumps(dashboard_data, sort_keys=True, cls=DecimalEncoder)
        etag = f'"{hashlib.md5(data_json.encode()).hexdigest()}"'
        
        # Check If-None-Match header for conditional request
        request_headers = event.get('headers', {})
        if_none_match = request_headers.get('if-none-match') or request_headers.get('If-None-Match')
        
        if if_none_match and if_none_match == etag:
            logger.info(f"ETag match — returning 304 Not Modified for ride: {ride_id}")
            response = not_modified_response()
            response['headers']['ETag'] = etag
            return response
        
        logger.info(f"Dashboard data prepared successfully for ride: {ride_id}")
        response = success_response(dashboard_data)
        response['headers']['ETag'] = etag
        return response
    
    except Exception as e:
        logger.error(f"Error getting dashboard data: {str(e)}", exc_info=True)
        return internal_error_response("Failed to retrieve dashboard data")
