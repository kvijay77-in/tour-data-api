#!/usr/bin/env python3
"""
Cleanup tour-specific DynamoDB tables

Finds and deletes all tour-specific DynamoDB tables created by provision_tour.py
or the POST /v1/tours API. These tables are not managed by CloudFormation and
are NOT removed by 'sam delete'.

Tour-specific tables follow the naming pattern:
    {stack_name}-{TableType}-{tourId}
where TableType is one of: TourRider, Ride, CheckIn, User, Notification, Artifacts

Detection strategy:
    1. Lists all DynamoDB tables in the region
    2. Matches tables with the prefix '{stack_name}-' and a known table type

Usage:
    # Dry run (default) — show what would be deleted
    python scripts/cleanup_tour_tables.py --stack-name dev

    # Actually delete the tables
    python scripts/cleanup_tour_tables.py --stack-name dev --confirm

    # Specify AWS region
    python scripts/cleanup_tour_tables.py --stack-name dev --region ap-south-1 --confirm

Prerequisites:
    - AWS CLI configured with valid credentials
    - Python packages: boto3
"""

import argparse
import re
import sys
import time

import boto3
from botocore.exceptions import ClientError

# Tour-specific table types (must match models.TOUR_TABLE_TYPES)
TOUR_TABLE_TYPES = ('TourRider', 'Ride', 'CheckIn', 'User', 'Notification', 'Artifacts')


def find_tour_tables(dynamodb_client, stack_name):
    """
    Find all tour-specific DynamoDB tables for a given stack.

    Scans all DynamoDB table names in the region and matches those that follow
    the pattern: {stack_name}-{TableType}-{tourId}

    Args:
        dynamodb_client: boto3 DynamoDB client
        stack_name: CloudFormation stack name prefix

    Returns:
        List of matching table names sorted alphabetically
    """
    # Build regex: {stack_name}-{TableType}-{tourId}
    types_pattern = '|'.join(re.escape(t) for t in TOUR_TABLE_TYPES)
    pattern = re.compile(rf'^{re.escape(stack_name)}-({types_pattern})-.+$')

    matching_tables = []
    paginator = dynamodb_client.get_paginator('list_tables')

    for page in paginator.paginate():
        for table_name in page.get('TableNames', []):
            if pattern.match(table_name):
                matching_tables.append(table_name)

    return sorted(matching_tables)


def delete_table(dynamodb_client, table_name):
    """
    Delete a single DynamoDB table.

    Args:
        dynamodb_client: boto3 DynamoDB client
        table_name: Name of the table to delete

    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        dynamodb_client.delete_table(TableName=table_name)
        return True
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ResourceNotFoundException':
            print(f"  Warning: Table '{table_name}' not found (already deleted?)")
            return True
        print(f"  Error deleting '{table_name}': {e.response['Error']['Message']}")
        return False


def wait_for_deletions(dynamodb_client, table_names, max_wait=120):
    """
    Wait for tables to be fully deleted.

    Args:
        dynamodb_client: boto3 DynamoDB client
        table_names: List of table names being deleted
        max_wait: Maximum wait time in seconds
    """
    start = time.time()
    pending = set(table_names)

    while pending and (time.time() - start) < max_wait:
        for table_name in list(pending):
            try:
                dynamodb_client.describe_table(TableName=table_name)
                # Table still exists, keep waiting
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    pending.discard(table_name)
        if pending:
            time.sleep(3)

    if pending:
        print(f"\n  Warning: {len(pending)} table(s) still deleting after {max_wait}s:")
        for t in sorted(pending):
            print(f"    - {t}")
        print("  They will continue deleting in the background.")


def group_tables_by_tour(table_names, stack_name):
    """
    Group table names by tour ID for readable display.

    Args:
        table_names: List of table names
        stack_name: Stack name prefix

    Returns:
        Dict mapping tour_id to list of table names
    """
    tours = {}
    prefix = f"{stack_name}-"
    for table_name in table_names:
        # Remove prefix, then split on first '-' to get table_type and tour_id
        remainder = table_name[len(prefix):]
        for table_type in TOUR_TABLE_TYPES:
            type_prefix = f"{table_type}-"
            if remainder.startswith(type_prefix):
                tour_id = remainder[len(type_prefix):]
                tours.setdefault(tour_id, []).append(table_name)
                break
    return tours


def main():
    parser = argparse.ArgumentParser(
        description='Clean up tour-specific DynamoDB tables not managed by CloudFormation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run — see what would be deleted
  python scripts/cleanup_tour_tables.py --stack-name dev

  # Delete all tour tables for the dev stack
  python scripts/cleanup_tour_tables.py --stack-name dev --confirm

  # Specify region
  python scripts/cleanup_tour_tables.py --stack-name dev --region ap-south-1 --confirm
        """
    )

    parser.add_argument(
        '--stack-name', required=True,
        help='CloudFormation stack name (e.g., dev, test, prod)'
    )
    parser.add_argument(
        '--region', default=None,
        help='AWS region (default: from AWS config)'
    )
    parser.add_argument(
        '--confirm', action='store_true',
        help='Actually delete tables. Without this flag, performs a dry run.'
    )

    args = parser.parse_args()

    # Create session
    session_kwargs = {}
    if args.region:
        session_kwargs['region_name'] = args.region
    session = boto3.Session(**session_kwargs)
    dynamodb_client = session.client('dynamodb')
    region = session.region_name

    print("")
    print(f"=== Tour Table Cleanup — {args.stack_name} ({region}) ===")
    print("")

    # Find tour-specific tables
    print("Scanning for tour-specific tables...")
    tables = find_tour_tables(dynamodb_client, args.stack_name)

    if not tables:
        print("  No tour-specific tables found. Nothing to clean up.")
        print("")
        return

    # Display grouped by tour
    tours = group_tables_by_tour(tables, args.stack_name)
    print(f"\n  Found {len(tables)} tour-specific table(s) across {len(tours)} tour(s):\n")
    for tour_id in sorted(tours.keys()):
        print(f"  Tour: {tour_id}")
        for table_name in sorted(tours[tour_id]):
            print(f"    - {table_name}")
    print("")

    # Dry run or delete
    if not args.confirm:
        print("  DRY RUN — no tables deleted.")
        print("  Re-run with --confirm to delete these tables.")
        print("")
        return

    # Delete tables
    print("Deleting tables...")
    failed = []
    deleted = []
    for table_name in tables:
        print(f"  Deleting {table_name}...", end=" ")
        if delete_table(dynamodb_client, table_name):
            print("initiated")
            deleted.append(table_name)
        else:
            print("FAILED")
            failed.append(table_name)

    # Wait for deletions to complete
    if deleted:
        print("\nWaiting for deletions to complete...")
        wait_for_deletions(dynamodb_client, deleted)

    # Summary
    print("\n=== Cleanup Complete ===")
    print(f"  Deleted: {len(deleted)}")
    if failed:
        print(f"  Failed:  {len(failed)}")
        for t in failed:
            print(f"    - {t}")
    print("")

    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
