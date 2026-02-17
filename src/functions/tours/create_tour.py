"""
Create and provision a new tour Lambda function

Creates the Tour record in the shared Tour table and provisions
4 tour-specific DynamoDB tables: TourRider, Ride, CheckIn, User.
"""

import sys
sys.path.insert(0, '/opt/python')

import json
import os
import time
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from logger import get_logger, log_event
from response import (
    success_response, error_response, bad_request_response,
    conflict_response, internal_error_response
)
from dynamodb_utils import get_item, put_item, get_tour_table_name
from validation import validate_tour_id, validate_iso_date, validate_required_fields, ValidationError
from models import TourStatus, TOUR_TABLE_TYPES

logger = get_logger(__name__)

dynamodb_client = boto3.client('dynamodb')

# Table definitions for tour-specific tables
TOUR_TABLE_DEFINITIONS = {
    'TourRider': {
        'AttributeDefinitions': [
            {'AttributeName': 'PK', 'AttributeType': 'S'},
            {'AttributeName': 'profileId', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'PK', 'KeyType': 'HASH'},
        ],
        'GlobalSecondaryIndexes': [
            {
                'IndexName': 'ProfileIdIndex',
                'KeySchema': [
                    {'AttributeName': 'profileId', 'KeyType': 'HASH'},
                ],
                'Projection': {'ProjectionType': 'ALL'},
            },
        ],
    },
    'Ride': {
        'AttributeDefinitions': [
            {'AttributeName': 'PK', 'AttributeType': 'S'},
            {'AttributeName': 'date', 'AttributeType': 'S'},
            {'AttributeName': 'status', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'PK', 'KeyType': 'HASH'},
        ],
        'GlobalSecondaryIndexes': [
            {
                'IndexName': 'DateIndex',
                'KeySchema': [
                    {'AttributeName': 'date', 'KeyType': 'HASH'},
                ],
                'Projection': {'ProjectionType': 'ALL'},
            },
            {
                'IndexName': 'StatusIndex',
                'KeySchema': [
                    {'AttributeName': 'status', 'KeyType': 'HASH'},
                    {'AttributeName': 'date', 'KeyType': 'RANGE'},
                ],
                'Projection': {'ProjectionType': 'ALL'},
            },
        ],
    },
    'CheckIn': {
        'AttributeDefinitions': [
            {'AttributeName': 'PK', 'AttributeType': 'S'},
            {'AttributeName': 'SK', 'AttributeType': 'S'},
            {'AttributeName': 'riderId', 'AttributeType': 'S'},
            {'AttributeName': 'timestamp', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'PK', 'KeyType': 'HASH'},
            {'AttributeName': 'SK', 'KeyType': 'RANGE'},
        ],
        'GlobalSecondaryIndexes': [
            {
                'IndexName': 'RiderIdIndex',
                'KeySchema': [
                    {'AttributeName': 'riderId', 'KeyType': 'HASH'},
                    {'AttributeName': 'timestamp', 'KeyType': 'RANGE'},
                ],
                'Projection': {'ProjectionType': 'ALL'},
            },
        ],
    },
    'User': {
        'AttributeDefinitions': [
            {'AttributeName': 'PK', 'AttributeType': 'S'},
            {'AttributeName': 'email', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'PK', 'KeyType': 'HASH'},
        ],
        'GlobalSecondaryIndexes': [
            {
                'IndexName': 'EmailIndex',
                'KeySchema': [
                    {'AttributeName': 'email', 'KeyType': 'HASH'},
                ],
                'Projection': {'ProjectionType': 'ALL'},
            },
        ],
    },
}


def _build_tags(tour_id):
    """Build tags for tour-specific tables"""
    tags = [
        {'Key': 'Project', 'Value': 'tour-data-api'},
        {'Key': 'Application', 'Value': 'TourManagement'},
        {'Key': 'ManagedBy', 'Value': 'Lambda'},
        {'Key': 'tourId', 'Value': tour_id},
    ]
    
    environment = os.environ.get('ENVIRONMENT', 'dev')
    tags.append({'Key': 'Environment', 'Value': environment})
    
    subscription_id = os.environ.get('SUBSCRIPTION_ID', '')
    if subscription_id:
        tags.append({'Key': 'SubscriptionId', 'Value': subscription_id})
    
    return tags


def _create_tour_table(table_type, tour_id):
    """Create a single tour-specific DynamoDB table"""
    table_name = get_tour_table_name(table_type, tour_id)
    definition = TOUR_TABLE_DEFINITIONS[table_type]
    
    create_params = {
        'TableName': table_name,
        'AttributeDefinitions': definition['AttributeDefinitions'],
        'KeySchema': definition['KeySchema'],
        'BillingMode': 'PAY_PER_REQUEST',
        'SSESpecification': {'Enabled': True},
        'Tags': _build_tags(tour_id),
    }
    
    if definition.get('GlobalSecondaryIndexes'):
        create_params['GlobalSecondaryIndexes'] = definition['GlobalSecondaryIndexes']
    
    logger.info(f"Creating table: {table_name}")
    dynamodb_client.create_table(**create_params)
    return table_name


def _wait_for_tables(table_names, max_wait=90):
    """Wait for all tables to become ACTIVE"""
    start = time.time()
    pending = set(table_names)
    
    while pending and (time.time() - start) < max_wait:
        for table_name in list(pending):
            try:
                resp = dynamodb_client.describe_table(TableName=table_name)
                status = resp['Table']['TableStatus']
                if status == 'ACTIVE':
                    logger.info(f"Table {table_name} is ACTIVE")
                    pending.discard(table_name)
            except ClientError:
                pass  # Table may not exist yet
        
        if pending:
            time.sleep(3)
    
    if pending:
        raise TimeoutError(f"Tables did not become ACTIVE within {max_wait}s: {pending}")


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
        1. Tour record in shared Tour table (status: PROVISIONING)
        2. Four tour-specific DynamoDB tables
        3. Updates Tour status to PLANNING once tables are active
    """
    try:
        log_event(logger, event)
        
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
            table_name_env='TOUR_TABLE',
            key={'PK': f'TOUR#{tour_id}'}
        )
        
        if existing:
            return conflict_response(f"Tour '{tour_id}' already exists")
        
        # Create Tour record with PROVISIONING status
        now = datetime.utcnow().isoformat() + 'Z'
        tour_item = {
            'PK': f'TOUR#{tour_id}',
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
        
        put_item('TOUR_TABLE', tour_item)
        logger.info(f"Tour record created: {tour_id} (status: PROVISIONING)")
        
        # Provision tour-specific tables
        created_tables = []
        try:
            for table_type in TOUR_TABLE_TYPES:
                table_name = _create_tour_table(table_type, tour_id)
                created_tables.append(table_name)
            
            # Wait for all tables to become ACTIVE
            _wait_for_tables(created_tables)
            
        except Exception as e:
            logger.error(f"Error provisioning tables for tour {tour_id}: {str(e)}")
            # Update tour status to indicate failure
            tour_item['status'] = TourStatus.PLANNING.value
            tour_item['updatedAt'] = datetime.utcnow().isoformat() + 'Z'
            tour_item['provisioningError'] = str(e)
            put_item('TOUR_TABLE', tour_item)
            return internal_error_response(f"Tour created but table provisioning failed: {str(e)}")
        
        # Update tour status to PLANNING
        tour_item['status'] = TourStatus.PLANNING.value
        tour_item['provisionedAt'] = datetime.utcnow().isoformat() + 'Z'
        tour_item['updatedAt'] = datetime.utcnow().isoformat() + 'Z'
        put_item('TOUR_TABLE', tour_item)
        
        logger.info(f"Tour {tour_id} provisioned successfully with {len(created_tables)} tables")
        
        return success_response(tour_item, status_code=201)
    
    except json.JSONDecodeError:
        return bad_request_response("Invalid JSON in request body")
    except Exception as e:
        logger.error(f"Error creating tour: {str(e)}", exc_info=True)
        return internal_error_response("Failed to create tour")
