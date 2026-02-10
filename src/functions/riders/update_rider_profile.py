"""
Lambda function to update a rider profile
"""
import json
import os
import sys
from datetime import datetime

# Add common layer to path
sys.path.insert(0, '/opt/python')

from logger import get_logger
from response import success_response, not_found_response, error_response, bad_request_response
from validation import validate_rider_id, validate_email, validate_required_fields, ValidationError
from dynamodb_utils import get_item, put_item

logger = get_logger(__name__)

RIDER_PROFILE_TABLE = os.environ['RIDER_PROFILE_TABLE']
S3_BUCKET = os.environ['S3_BUCKET']


def lambda_handler(event, context):
    """
    Update a rider profile
    
    Path parameter: riderId (e.g., R1, R42)
    Body: JSON with fields to update (name, email, phoneNumber, emergencyContact)
    
    Returns:
    - 200: Rider profile updated
    - 400: Invalid input
    - 404: Rider not found
    - 500: Server error
    """
    try:
        # Extract rider ID from path parameters
        rider_id = event.get('pathParameters', {}).get('riderId')
        
        if not rider_id:
            return bad_request_response("riderId is required in path")
        
        # Validate rider ID format
        try:
            validate_rider_id(rider_id)
        except ValidationError as e:
            logger.warning(f"Invalid rider ID format: {rider_id}", exc_info=True)
            return bad_request_response(str(e))
        
        # Parse request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return bad_request_response("Invalid JSON in request body")
        
        # Get existing rider profile
        logger.info(f"Fetching existing rider profile: {rider_id}")
        existing_rider = get_item(
            table_name=RIDER_PROFILE_TABLE,
            key={'riderId': rider_id}
        )
        
        if not existing_rider:
            logger.info(f"Rider not found: {rider_id}")
            return not_found_response(f"Rider {rider_id} not found")
        
        # Validate updatable fields
        updatable_fields = ['name', 'email', 'phoneNumber', 'emergencyContact']
        updates = {k: v for k, v in body.items() if k in updatable_fields}
        
        if not updates:
            return bad_request_response("No valid fields to update")
        
        # Validate email if provided
        if 'email' in updates:
            try:
                validate_email(updates['email'])
            except ValidationError as e:
                return bad_request_response(f"Invalid email: {str(e)}")
        
        # Validate emergency contact if provided
        if 'emergencyContact' in updates:
            contact = updates['emergencyContact']
            if not isinstance(contact, dict):
                return bad_request_response("emergencyContact must be an object")
            
            required_contact_fields = ['name', 'relationship', 'phone']
            try:
                validate_required_fields(contact, required_contact_fields)
            except ValidationError as e:
                return bad_request_response(f"Invalid emergency contact: {str(e)}")
        
        # Update rider profile
        updated_rider = {**existing_rider, **updates}
        updated_rider['updatedAt'] = datetime.utcnow().isoformat() + 'Z'
        
        logger.info(f"Updating rider profile: {rider_id}")
        put_item(table_name=RIDER_PROFILE_TABLE, item=updated_rider)
        
        logger.info(f"Successfully updated rider profile: {rider_id}")
        return success_response(updated_rider)
        
    except Exception as e:
        logger.error(f"Error updating rider profile: {str(e)}", exc_info=True)
        return error_response(f"Failed to update rider profile: {str(e)}")
