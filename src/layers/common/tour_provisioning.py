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
- Notification-{tourId}: Tour rider notifications
- Artifacts-{tourId}: Tour and ride artifact metadata
- Event-{tourId}: Event definitions
- EventOccurrence-{tourId}: Event occurrences
- EventActivityLogs-{tourId}: Event activity records
- Hotel-{tourId}: Hotel master data
- RoomAllocation-{tourId}: Per-night room allocation data
"""

import os
import time

import boto3
from botocore.exceptions import ClientError

from dynamodb_utils import get_tour_table_name
from models import TOUR_TABLE_TYPES


TABLE_ALREADY_EXISTS_CODE = 'ResourceInUseException'


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
    'Notification': {
        'AttributeDefinitions': [
            {'AttributeName': 'audience', 'AttributeType': 'S'},
            {'AttributeName': 'sk', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'audience', 'KeyType': 'HASH'},
            {'AttributeName': 'sk', 'KeyType': 'RANGE'},
        ],
        'TimeToLiveSpecification': {
            'AttributeName': 'expiresAt',
            'Enabled': True,
        },
        'StreamSpecification': {
            'StreamEnabled': True,
            'StreamViewType': 'NEW_IMAGE',
        },
    },
    'Artifacts': {
        'AttributeDefinitions': [
            {'AttributeName': 'artifactFor', 'AttributeType': 'S'},
            {'AttributeName': 'artifactId', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'artifactFor', 'KeyType': 'HASH'},
            {'AttributeName': 'artifactId', 'KeyType': 'RANGE'},
        ],
    },
    'Event': {
        'AttributeDefinitions': [
            {'AttributeName': 'eventId', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'eventId', 'KeyType': 'HASH'},
        ],
    },
    'EventOccurrence': {
        'AttributeDefinitions': [
            {'AttributeName': 'eventId', 'AttributeType': 'S'},
            {'AttributeName': 'dateSeq', 'AttributeType': 'S'},
            {'AttributeName': 'date', 'AttributeType': 'S'},
            {'AttributeName': 'status', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'eventId', 'KeyType': 'HASH'},
            {'AttributeName': 'dateSeq', 'KeyType': 'RANGE'},
        ],
        'GlobalSecondaryIndexes': [
            {
                'IndexName': 'DateIndex',
                'KeySchema': [
                    {'AttributeName': 'date', 'KeyType': 'HASH'},
                    {'AttributeName': 'eventId', 'KeyType': 'RANGE'},
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
    'EventActivityLogs': {
        'AttributeDefinitions': [
            {'AttributeName': 'occurrenceId', 'AttributeType': 'S'},
            {'AttributeName': 'recordId', 'AttributeType': 'S'},
            {'AttributeName': 'riderId', 'AttributeType': 'S'},
            {'AttributeName': 'timestamp', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'occurrenceId', 'KeyType': 'HASH'},
            {'AttributeName': 'recordId', 'KeyType': 'RANGE'},
        ],
        'GlobalSecondaryIndexes': [
            {
                'IndexName': 'RiderTimestampIndex',
                'KeySchema': [
                    {'AttributeName': 'riderId', 'KeyType': 'HASH'},
                    {'AttributeName': 'timestamp', 'KeyType': 'RANGE'},
                ],
                'Projection': {'ProjectionType': 'ALL'},
            },
        ],
    },
    'Hotel': {
        'AttributeDefinitions': [
            {'AttributeName': 'hotelId', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'hotelId', 'KeyType': 'HASH'},
        ],
    },
    'RoomAllocation': {
        'AttributeDefinitions': [
            {'AttributeName': 'stayDate', 'AttributeType': 'S'},
            {'AttributeName': 'riderId', 'AttributeType': 'S'},
            {'AttributeName': 'hotelId', 'AttributeType': 'S'},
        ],
        'KeySchema': [
            {'AttributeName': 'stayDate', 'KeyType': 'HASH'},
            {'AttributeName': 'riderId', 'KeyType': 'RANGE'},
        ],
        'GlobalSecondaryIndexes': [
            {
                'IndexName': 'RiderIdIndex',
                'KeySchema': [
                    {'AttributeName': 'riderId', 'KeyType': 'HASH'},
                    {'AttributeName': 'stayDate', 'KeyType': 'RANGE'},
                ],
                'Projection': {'ProjectionType': 'ALL'},
            },
            {
                'IndexName': 'HotelDateIndex',
                'KeySchema': [
                    {'AttributeName': 'hotelId', 'KeyType': 'HASH'},
                    {'AttributeName': 'stayDate', 'KeyType': 'RANGE'},
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


def create_tour_table(dynamodb_client, table_type, tour_id, ignore_existing=False):
    """
    Create a single tour-specific DynamoDB table

    Args:
        dynamodb_client: boto3 DynamoDB client
        table_type: Tour-specific table type
        tour_id: Tour identifier
        ignore_existing: When true, existing tables are returned without error

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
    if definition.get('StreamSpecification'):
        create_params['StreamSpecification'] = definition['StreamSpecification']

    def _is_new_notification_schema(description):
        key_schema = description.get('Table', {}).get('KeySchema', [])
        keys = [(k.get('AttributeName'), k.get('KeyType')) for k in key_schema]
        return keys == [('audience', 'HASH'), ('sk', 'RANGE')]

    try:
        dynamodb_client.create_table(**create_params)
    except ClientError as e:
        if ignore_existing and e.response['Error']['Code'] == TABLE_ALREADY_EXISTS_CODE:
            if table_type != 'Notification':
                if definition.get('TimeToLiveSpecification'):
                    try:
                        dynamodb_client.update_time_to_live(
                            TableName=table_name,
                            TimeToLiveSpecification=definition['TimeToLiveSpecification'],
                        )
                    except ClientError:
                        pass

                return table_name

            current = dynamodb_client.describe_table(TableName=table_name)
            if _is_new_notification_schema(current):
                return table_name

            scan = dynamodb_client.scan(TableName=table_name, Limit=1)
            if scan.get('Items'):
                return table_name

            dynamodb_client.delete_table(TableName=table_name)
            waiter = dynamodb_client.get_waiter('table_not_exists')
            waiter.wait(TableName=table_name)
            dynamodb_client.create_table(**create_params)
            return table_name
        raise

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


def provision_tour_tables(dynamodb_client, tour_id, ignore_existing=False):
    """
    Provision all tour-specific DynamoDB tables for a tour

    Args:
        dynamodb_client: boto3 DynamoDB client
        tour_id: Tour identifier
        ignore_existing: When true, existing tables are ignored for rerun provisioning

    Returns:
        List of created table names

    Raises:
        TimeoutError: If tables don't become ACTIVE within timeout
    """
    created_tables = []
    for table_type in TOUR_TABLE_TYPES:
        table_name = create_tour_table(
            dynamodb_client,
            table_type,
            tour_id,
            ignore_existing=ignore_existing,
        )
        created_tables.append(table_name)

    wait_for_tour_tables(dynamodb_client, created_tables)

    push_sender_arn = os.environ.get('PUSH_SENDER_FUNCTION_ARN')
    if push_sender_arn:
        try:
            notification_table = get_tour_table_name('Notification', tour_id)
            stream_arn = dynamodb_client.describe_table(TableName=notification_table)['Table'].get('LatestStreamArn')
            if stream_arn:
                lambda_client = boto3.client('lambda')
                existing = lambda_client.list_event_source_mappings(
                    FunctionName=push_sender_arn,
                    EventSourceArn=stream_arn,
                ).get('EventSourceMappings', [])
                if not existing:
                    lambda_client.create_event_source_mapping(
                        EventSourceArn=stream_arn,
                        FunctionName=push_sender_arn,
                        StartingPosition='LATEST',
                        BatchSize=100,
                        MaximumRetryAttempts=3,
                        FilterCriteria={
                            'Filters': [
                                {
                                    'Pattern': (
                                        '{\"eventName\":[\"INSERT\"],'
                                        '\"dynamodb\":{\"NewImage\":{\"push\":{\"BOOL\":[true]}}}}'
                                    )
                                }
                            ]
                        },
                    )
        except Exception:
            pass

    return created_tables
