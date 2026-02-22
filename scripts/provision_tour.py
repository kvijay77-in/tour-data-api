#!/usr/bin/env python3
"""
Tour provisioning CLI script

Provisions a new tour by creating a Tour record in the shared Tour table
and creating 4 tour-specific DynamoDB tables (TourRider, Ride, CheckIn, User).

This script provides the deployment-time method for tour provisioning,
complementing the API method (POST /v1/tours) used by external apps.

Usage:
    python scripts/provision_tour.py \\
        --stack-name tour-data-api \\
        --tour-id India-Coast-2026 \\
        --name "India Coastal Ride 2026" \\
        --start-date 2026-02-10 \\
        --end-date 2026-02-17 \\
        --description "Annual coastal cycling tour" \\
        --environment dev

Prerequisites:
    - AWS CLI configured with valid credentials
    - Stack must be deployed (shared Tour table must exist)
    - Python packages: boto3
"""

import argparse
import os
import sys
from datetime import datetime, timezone

# Add common layer to path for shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'layers', 'common'))

import boto3
from botocore.exceptions import ClientError

from validation import validate_tour_id, validate_iso_date, ValidationError
from models import TourStatus, TOUR_TABLE_TYPES
from tour_provisioning import provision_tour_tables


def get_tour_table_name_from_stack(stack_name):
    """
    Get the Tour table name from CloudFormation stack outputs

    Args:
        stack_name: CloudFormation stack name

    Returns:
        Tour table name
    """
    cf_client = boto3.client('cloudformation')
    try:
        response = cf_client.describe_stacks(StackName=stack_name)
        outputs = response['Stacks'][0].get('Outputs', [])
        for output in outputs:
            if output['OutputKey'] == 'TourTableName':
                return output['OutputValue']
    except ClientError as e:
        print(f"Error: Could not describe stack '{stack_name}': {e}")
        sys.exit(1)

    # Fallback to naming convention
    return f"{stack_name}-Tour"


def provision_tour(args):
    """
    Provision a new tour with tour-specific tables

    Args:
        args: Parsed command-line arguments
    """
    stack_name = args.stack_name
    tour_id = args.tour_id
    name = args.name
    start_date = args.start_date
    end_date = args.end_date
    description = args.description
    environment = args.environment
    region = args.region
    subscription_id = args.subscription_id

    # Validate inputs
    try:
        validate_tour_id(tour_id)
    except ValidationError as e:
        print(f"Error: {e}")
        sys.exit(1)

    try:
        validate_iso_date(start_date, 'start-date')
        validate_iso_date(end_date, 'end-date')
    except ValidationError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if end_date < start_date:
        print("Error: end-date must be on or after start-date")
        sys.exit(1)

    # Set environment variables for shared utilities
    os.environ['STACK_NAME'] = stack_name
    os.environ['ENVIRONMENT'] = environment
    if subscription_id:
        os.environ['SUBSCRIPTION_ID'] = subscription_id

    # Initialize AWS clients
    session = boto3.Session(region_name=region) if region else boto3.Session()
    dynamodb_client = session.client('dynamodb')
    dynamodb_resource = session.resource('dynamodb')

    # Resolve Tour table name from stack
    tour_table_name = get_tour_table_name_from_stack(stack_name)
    tour_table = dynamodb_resource.Table(tour_table_name)

    print(f"Provisioning tour: {tour_id}")
    print(f"  Stack: {stack_name}")
    print(f"  Tour table: {tour_table_name}")
    print(f"  Environment: {environment}")
    print()

    # Check if tour already exists
    try:
        response = tour_table.get_item(Key={'PK': f'TOUR#{tour_id}'})
        if 'Item' in response:
            existing = response['Item']
            print(f"Error: Tour '{tour_id}' already exists (status: {existing.get('status')})")
            sys.exit(1)
    except ClientError as e:
        print(f"Error checking tour existence: {e}")
        sys.exit(1)

    # Create Tour record with PROVISIONING status
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
    tour_item = {
        'PK': f'TOUR#{tour_id}',
        'tourId': tour_id,
        'name': name,
        'startDate': start_date,
        'endDate': end_date,
        'status': TourStatus.PROVISIONING.value,
        'createdAt': now,
        'updatedAt': now,
    }

    if description:
        tour_item['description'] = description

    try:
        tour_table.put_item(Item=tour_item)
        print(f"Tour record created: {tour_id} (status: PROVISIONING)")
    except ClientError as e:
        print(f"Error creating tour record: {e}")
        sys.exit(1)

    # Provision tour-specific tables
    print(f"\nCreating {len(TOUR_TABLE_TYPES)} tour-specific tables...")
    try:
        created_tables = provision_tour_tables(dynamodb_client, tour_id)

        for table_name in created_tables:
            print(f"  ✓ {table_name}")

    except Exception as e:
        print(f"\nError provisioning tables: {e}")
        # Update tour record with error
        tour_item['status'] = TourStatus.PLANNING.value
        tour_item['updatedAt'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
        tour_item['provisioningError'] = str(e)
        tour_table.put_item(Item=tour_item)
        print("Tour status updated to PLANNING with provisioning error")
        sys.exit(1)

    # Update tour status to PLANNING
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
    tour_item['status'] = TourStatus.PLANNING.value
    tour_item['provisionedAt'] = now
    tour_item['updatedAt'] = now

    try:
        tour_table.put_item(Item=tour_item)
    except ClientError as e:
        print(f"Warning: Tables created but failed to update tour status: {e}")

    print(f"\n✓ Tour '{tour_id}' provisioned successfully!")
    print(f"  Status: PLANNING")
    print(f"  Tables created: {len(created_tables)}")
    print(f"\nThe tour is ready for use. Tour-specific tables:")
    for table_type in TOUR_TABLE_TYPES:
        print(f"  - {stack_name}-{table_type}-{tour_id}")


def main():
    parser = argparse.ArgumentParser(
        description='Provision a new tour with tour-specific DynamoDB tables',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Provision a tour for the dev environment
  python scripts/provision_tour.py \\
    --stack-name tour-data-api \\
    --tour-id India-Coast-2026 \\
    --name "India Coastal Ride 2026" \\
    --start-date 2026-02-10 \\
    --end-date 2026-02-17

  # Provision with all options
  python scripts/provision_tour.py \\
    --stack-name tour-data-api-prod \\
    --tour-id TDF2026 \\
    --name "Tour de France 2026" \\
    --start-date 2026-07-01 \\
    --end-date 2026-07-23 \\
    --description "Annual summer tour" \\
    --environment prod \\
    --region eu-west-1 \\
    --subscription-id client-abc-123

This script is the deployment-time equivalent of POST /v1/tours API endpoint.
Both methods create the same Tour record and tour-specific tables.
        """
    )

    parser.add_argument(
        '--stack-name', required=True,
        help='CloudFormation stack name (e.g., tour-data-api, tour-data-api-prod)'
    )
    parser.add_argument(
        '--tour-id', required=True,
        help='Tour identifier (3-50 chars, alphanumeric with _.-)'
    )
    parser.add_argument(
        '--name', required=True,
        help='Tour display name'
    )
    parser.add_argument(
        '--start-date', required=True,
        help='Tour start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date', required=True,
        help='Tour end date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--description', default='',
        help='Tour description (optional)'
    )
    parser.add_argument(
        '--environment', default='dev',
        choices=['dev', 'test', 'prod'],
        help='Environment name for tagging (default: dev)'
    )
    parser.add_argument(
        '--region', default=None,
        help='AWS region (default: from AWS config)'
    )
    parser.add_argument(
        '--subscription-id', default='',
        help='Subscription ID for cost tracking (optional)'
    )

    args = parser.parse_args()
    provision_tour(args)


if __name__ == '__main__':
    main()
