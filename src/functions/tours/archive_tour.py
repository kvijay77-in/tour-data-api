"""
Archive tour Lambda function

Archives a completed tour by optionally exporting data to S3
and deleting tour-specific DynamoDB tables.
"""

import sys
sys.path.insert(0, '/opt/python')

import json
import os
import time

import boto3
from botocore.exceptions import ClientError

from logger import get_logger, log_event
from response import (
    success_response, error_response, bad_request_response,
    not_found_response, internal_error_response
)
from dynamodb_utils import get_item, put_item, get_tour_table_name
from validation import validate_tour_id, ValidationError
from models import TourStatus, TOUR_TABLE_TYPES, utc_now_iso
from rbac import require_groups, ADMINISTRATOR

logger = get_logger(__name__)

dynamodb_client = boto3.client('dynamodb')
s3_client = boto3.client('s3')


def _export_table_to_s3(table_name, tour_id, table_type):
    """Export table data to S3 as JSON (simple scan-based export)"""
    bucket = os.environ.get('PHOTOS_BUCKET')
    if not bucket:
        logger.warning("PHOTOS_BUCKET not set, skipping S3 export")
        return None
    
    try:
        # Scan all items from the table
        paginator = dynamodb_client.get_paginator('scan')
        items = []
        for page in paginator.paginate(TableName=table_name):
            items.extend(page.get('Items', []))
        
        if not items:
            logger.info(f"No items to export from {table_name}")
            return None
        
        # Write to S3
        key = f"archives/{tour_id}/{table_type}.json"
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(items, default=str),
            ContentType='application/json'
        )
        
        logger.info(f"Exported {len(items)} items from {table_name} to s3://{bucket}/{key}")
        return key
    
    except ClientError as e:
        logger.error(f"Error exporting {table_name} to S3: {e}")
        return None


def _delete_table(table_name):
    """Delete a DynamoDB table"""
    try:
        dynamodb_client.delete_table(TableName=table_name)
        logger.info(f"Delete initiated for table: {table_name}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            logger.warning(f"Table {table_name} does not exist, skipping")
        else:
            raise


def _wait_for_table_deletion(table_names, max_wait=90):
    """Wait for all tables to be deleted"""
    start = time.time()
    pending = set(table_names)
    
    while pending and (time.time() - start) < max_wait:
        for table_name in list(pending):
            try:
                dynamodb_client.describe_table(TableName=table_name)
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    logger.info(f"Table {table_name} deleted")
                    pending.discard(table_name)
        
        if pending:
            time.sleep(3)
    
    if pending:
        logger.warning(f"Tables still pending deletion after {max_wait}s: {pending}")


def lambda_handler(event, context):
    """
    Archive a completed tour
    
    Path Parameters:
        tourId: Tour identifier
    
    Query Parameters:
        exportToS3: Whether to export data to S3 before deletion (default: true)
        deleteTables: Whether to delete tour-specific tables (default: true)
    
    Steps:
        1. Verify tour exists and status is COMPLETED or ACTIVE
        2. Optionally export tour-specific table data to S3
        3. Optionally delete tour-specific DynamoDB tables
        4. Update Tour status to ARCHIVED
    """
    try:
        log_event(logger, event)
        
        # Enforce RBAC — only ADMINISTRATOR may archive tours
        deny = require_groups(event, [ADMINISTRATOR])
        if deny:
            return deny
        
        # Extract tour ID from path parameters
        tour_id = event.get('pathParameters', {}).get('tourId')
        
        if not tour_id:
            return bad_request_response("tourId is required in path")
        
        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))
        
        # Parse query parameters
        query_params = event.get('queryStringParameters') or {}
        export_to_s3 = query_params.get('exportToS3', 'true').lower() == 'true'
        delete_tables = query_params.get('deleteTables', 'true').lower() == 'true'
        
        # Get tour record
        tour = get_item(
            table_name_env='TOUR_MASTER_TABLE',
            key={'tourId': tour_id}
        )
        
        if not tour:
            return not_found_response("Tour", tour_id)
        
        # Validate tour status (allow archiving from COMPLETED or ACTIVE)
        current_status = tour.get('status')
        if current_status == TourStatus.ARCHIVED.value:
            return bad_request_response(f"Tour '{tour_id}' is already archived")
        
        if current_status not in [TourStatus.ACTIVE.value, TourStatus.COMPLETED.value]:
            return bad_request_response(
                f"Tour '{tour_id}' must be in ACTIVE or COMPLETED status to archive. "
                f"Current status: {current_status}"
            )
        
        logger.info(f"Archiving tour: {tour_id} (export={export_to_s3}, delete={delete_tables})")
        
        # Export to S3 if requested
        exported_keys = {}
        if export_to_s3:
            for table_type in TOUR_TABLE_TYPES:
                table_name = get_tour_table_name(table_type, tour_id)
                key = _export_table_to_s3(table_name, tour_id, table_type)
                if key:
                    exported_keys[table_type] = key
        
        # Delete tour-specific tables if requested
        deleted_tables = []
        if delete_tables:
            for table_type in TOUR_TABLE_TYPES:
                table_name = get_tour_table_name(table_type, tour_id)
                _delete_table(table_name)
                deleted_tables.append(table_name)
            
            if deleted_tables:
                _wait_for_table_deletion(deleted_tables)
        
        # Update tour status to ARCHIVED
        now = utc_now_iso()
        tour['status'] = TourStatus.ARCHIVED.value
        tour['archivedAt'] = now
        tour['updatedAt'] = now
        
        if exported_keys:
            tour['archiveExportKeys'] = exported_keys
        
        put_item('TOUR_MASTER_TABLE', tour)
        
        logger.info(f"Tour {tour_id} archived successfully")
        
        return success_response({
            'tour': tour,
            'exportedTables': list(exported_keys.keys()) if exported_keys else [],
            'deletedTables': len(deleted_tables)
        })
    
    except Exception as e:
        logger.error(f"Error archiving tour: {str(e)}", exc_info=True)
        return internal_error_response("Failed to archive tour")
