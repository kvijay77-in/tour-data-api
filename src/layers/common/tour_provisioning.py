"""
Tour-specific DynamoDB table provisioning utilities

Provides table definitions and creation/deletion logic for tour-specific tables.
Used by both the create_tour Lambda function (API method) and the
provision_tour CLI script (deployment method).

Tour-specific tables:
- TourRider-{tourId}: Rider enrollment for the tour
- Ride-{tourId}: Daily ride configurations
- CheckIn-{tourId}: Check-in records
- User-{tourId}: Staff/crew user assignments
"""

import os
import time

import boto3
from botocore.exceptions import ClientError

from dynamodb_utils import get_tour_table_name
from models import TOUR_TABLE_TYPES


# Table definitions for tour-specific tables
TOUR_TABLE_DEFINITIONS = {
    'TourRider': {
        'AttributeDefinitions': [
            {'AttributeName': 'riderId', 'AttributeType': 'S'},
            {'AttributeName': 'profileId', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'riderId', 'KeyType': 'HASH'},
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
            {'AttributeName': 'rideId', 'AttributeType': 'S'},
            {'AttributeName': 'date', 'AttributeType': 'S'},
            {'AttributeName': 'status', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'rideId', 'KeyType': 'HASH'},
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
            {'AttributeName': 'rideId', 'AttributeType': 'S'},
            {'AttributeName': 'checkInId', 'AttributeType': 'S'},
            {'AttributeName': 'riderId', 'AttributeType': 'S'},
            {'AttributeName': 'timestamp', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'rideId', 'KeyType': 'HASH'},
            {'AttributeName': 'checkInId', 'KeyType': 'RANGE'},
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
            {'AttributeName': 'userId', 'AttributeType': 'S'},
            {'AttributeName': 'email', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'userId', 'KeyType': 'HASH'},
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


def build_tour_table_tags(tour_id):
    """
    Build tags for tour-specific tables

    Args:
        tour_id: Tour identifier

    Returns:
        List of tag dictionaries
    """
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


def create_tour_table(dynamodb_client, table_type, tour_id):
    """
    Create a single tour-specific DynamoDB table

    Args:
        dynamodb_client: boto3 DynamoDB client
        table_type: Table type (TourRider, Ride, CheckIn, User)
        tour_id: Tour identifier

    Returns:
        Created table name
    """
    table_name = get_tour_table_name(table_type, tour_id)
    definition = TOUR_TABLE_DEFINITIONS[table_type]

    create_params = {
        'TableName': table_name,
        'AttributeDefinitions': definition['AttributeDefinitions'],
        'KeySchema': definition['KeySchema'],
        'BillingMode': 'PAY_PER_REQUEST',
        'SSESpecification': {'Enabled': True},
        'Tags': build_tour_table_tags(tour_id),
    }

    if definition.get('GlobalSecondaryIndexes'):
        create_params['GlobalSecondaryIndexes'] = definition['GlobalSecondaryIndexes']

    dynamodb_client.create_table(**create_params)
    return table_name


def wait_for_tour_tables(dynamodb_client, table_names, max_wait=90):
    """
    Wait for all tables to become ACTIVE

    Args:
        dynamodb_client: boto3 DynamoDB client
        table_names: List of table names to wait for
        max_wait: Maximum wait time in seconds

    Raises:
        TimeoutError: If tables don't become ACTIVE within max_wait
    """
    start = time.time()
    pending = set(table_names)

    while pending and (time.time() - start) < max_wait:
        for table_name in list(pending):
            try:
                resp = dynamodb_client.describe_table(TableName=table_name)
                status = resp['Table']['TableStatus']
                if status == 'ACTIVE':
                    pending.discard(table_name)
            except ClientError:
                pass  # Table may not exist yet

        if pending:
            time.sleep(3)

    if pending:
        raise TimeoutError(f"Tables did not become ACTIVE within {max_wait}s: {pending}")


def provision_tour_tables(dynamodb_client, tour_id):
    """
    Provision all 4 tour-specific DynamoDB tables for a tour

    Args:
        dynamodb_client: boto3 DynamoDB client
        tour_id: Tour identifier

    Returns:
        List of created table names

    Raises:
        TimeoutError: If tables don't become ACTIVE within timeout
    """
    created_tables = []
    for table_type in TOUR_TABLE_TYPES:
        table_name = create_tour_table(dynamodb_client, table_type, tour_id)
        created_tables.append(table_name)

    wait_for_tour_tables(dynamodb_client, created_tables)
    return created_tables
