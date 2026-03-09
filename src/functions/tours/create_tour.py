"""
Create and provision a new tour Lambda function

Creates the Tour record in the shared TourMaster table and provisions
4 tour-specific DynamoDB tables: TourRider, Ride, CheckIn, User.
"""

import sys
sys.path.insert(0, '/opt/python')

import json
import os

import boto3

from logger import get_logger, log_event
from response import (
    success_response, error_response, bad_request_response,
    conflict_response, internal_error_response
)
from dynamodb_utils import get_item, put_item
from validation import validate_tour_id, validate_iso_date, validate_required_fields, ValidationError
from models import TourStatus, TOUR_TABLE_TYPES, utc_now_iso
from tour_provisioning import provision_tour_tables
from rbac import require_groups, ADMINISTRATOR

logger = get_logger(__name__)

dynamodb_client = boto3.client('dynamodb')


def lambda_handler(event, context):
    """
    Create and provision a new tour
    
    Body:
        tourId: Free-form tour identifier (required, 3-50 chars)
        name: Tour name (required)
        startDate: ISO 8601 date (required)
        endDate: ISO 8601 date (required)
        description: Tour description (optional)
    
    Creates:
        1. Tour record in shared TourMaster table (status: PROVISIONING)
        2. Four tour-specific DynamoDB tables
        3. Updates Tour status to PLANNING once tables are active
    """
    try:
        log_event(logger, event)
        
        # Enforce RBAC — only ADMINISTRATOR may create tours
        deny = require_groups(event, [ADMINISTRATOR])
        if deny:
            return deny
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        
        # Validate required fields
        try:
            validate_required_fields(body, ['tourId', 'name', 'startDate', 'endDate'])
        except ValidationError as e:
            return bad_request_response(str(e))
        
        tour_id = body['tourId']
        
        # Validate tour ID format
        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Validate dates
        try:
            validate_iso_date(body['startDate'], 'startDate')
            validate_iso_date(body['endDate'], 'endDate')
        except ValidationError as e:
            return bad_request_response(str(e))
        
        if body['endDate'] < body['startDate']:
            return bad_request_response("endDate must be on or after startDate")
        
        # Check tourId uniqueness
        existing = get_item(
            table_name_env='TOUR_MASTER_TABLE',
            key={'tourId': tour_id}
        )
        
        if existing:
            return conflict_response(f"Tour '{tour_id}' already exists")
        
        # Create Tour record with PROVISIONING status
        now = utc_now_iso()
        tour_item = {
            'tourId': tour_id,
            'name': body['name'],
            'startDate': body['startDate'],
            'endDate': body['endDate'],
            'status': TourStatus.PROVISIONING.value,
            'createdAt': now,
            'updatedAt': now,
        }
        
        if body.get('description'):
            tour_item['description'] = body['description']
        
        put_item('TOUR_MASTER_TABLE', tour_item)
        logger.info(f"Tour record created: {tour_id} (status: PROVISIONING)")
        
        # Provision tour-specific tables
        created_tables = []
        try:
            created_tables = provision_tour_tables(dynamodb_client, tour_id)
            
        except Exception as e:
            logger.error(f"Error provisioning tables for tour {tour_id}: {str(e)}")
            # Update tour status to indicate failure
            tour_item['status'] = TourStatus.PLANNING.value
            tour_item['updatedAt'] = utc_now_iso()
            tour_item['provisioningError'] = str(e)
            put_item('TOUR_MASTER_TABLE', tour_item)
            return internal_error_response(f"Tour created but table provisioning failed: {str(e)}")
        
        # Update tour status to PLANNING
        tour_item['status'] = TourStatus.PLANNING.value
        tour_item['provisionedAt'] = utc_now_iso()
        tour_item['updatedAt'] = utc_now_iso()
        put_item('TOUR_MASTER_TABLE', tour_item)
        
        logger.info(f"Tour {tour_id} provisioned successfully with {len(created_tables)} tables")
        
        return success_response(tour_item, status_code=201)
    
    except json.JSONDecodeError:
        return bad_request_response("Invalid JSON in request body")
    except Exception as e:
        logger.error(f"Error creating tour: {str(e)}", exc_info=True)
        return internal_error_response("Failed to create tour")
