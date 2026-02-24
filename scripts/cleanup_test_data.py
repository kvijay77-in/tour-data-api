#!/usr/bin/env python3
"""
Clean up test data from tour-specific DynamoDB tables.

Scans and deletes ALL items from the tour-specific tables for a given tour.
Tables themselves are NOT deleted — only their contents are removed.

Tour-specific tables affected:
    {stack_name}-TourRider-{tourId}
    {stack_name}-Ride-{tourId}
    {stack_name}-CheckIn-{tourId}
    {stack_name}-User-{tourId}

Optionally cleans up generated rider profiles from the shared RiderProfile table.

Usage:
    # Dry run (default) — show what would be deleted
    python scripts/cleanup_test_data.py --stack-name dev --tour-id TOT-2026

    # Actually delete data
    python scripts/cleanup_test_data.py --stack-name dev --tour-id TOT-2026 --confirm

    # Also clean up rider profiles from shared table
    python scripts/cleanup_test_data.py --stack-name dev --tour-id TOT-2026 \\
        --include-profiles --confirm

    # Specify region
    python scripts/cleanup_test_data.py --stack-name dev --tour-id TOT-2026 \\
        --region ap-south-1 --confirm

Prerequisites:
    - AWS CLI configured with valid credentials
    - Tour-specific tables must exist
    - Python packages: boto3
"""

import argparse
import sys

import boto3
from botocore.exceptions import ClientError


# Tour-specific table types and their key attributes
TOUR_TABLE_KEYS = {
    'TourRider': ['riderId'],
    'Ride': ['rideId'],
    'CheckIn': ['rideId', 'checkInId'],
    'User': ['userId'],
}


def _get_table(dynamodb, table_name):
    """Get and verify a DynamoDB table exists. Returns table or None."""
    table = dynamodb.Table(table_name)
    try:
        table.load()
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            return None
        raise
    return table


def count_items(table):
    """Get the approximate item count for a table."""
    return table.item_count


def scan_all_keys(table, key_attrs):
    """
    Scan table and return all primary key values.

    Args:
        table: DynamoDB Table resource
        key_attrs: List of key attribute names

    Returns:
        List of key dicts for deletion
    """
    projection = ', '.join(key_attrs)
    keys = []

    response = table.scan(ProjectionExpression=projection)
    for item in response.get('Items', []):
        keys.append({attr: item[attr] for attr in key_attrs})

    while 'LastEvaluatedKey' in response:
        response = table.scan(
            ProjectionExpression=projection,
            ExclusiveStartKey=response['LastEvaluatedKey'],
        )
        for item in response.get('Items', []):
            keys.append({attr: item[attr] for attr in key_attrs})

    return keys


def delete_items(table, keys, table_name):
    """
    Delete items from table using batch writer.

    Args:
        table: DynamoDB Table resource
        keys: List of primary key dicts
        table_name: Table name for display

    Returns:
        tuple: (deleted_count, failed_count)
    """
    deleted = 0
    failed = 0

    with table.batch_writer() as batch:
        for i, key in enumerate(keys, 1):
            try:
                batch.delete_item(Key=key)
                deleted += 1
            except ClientError as e:
                failed += 1
                print(f"    Failed: {e.response['Error']['Message']}")
            if i % 100 == 0:
                print(f"    Progress: {i}/{len(keys)}...")

    return deleted, failed


def cleanup_tour_table(dynamodb, table_name, key_attrs, confirm):
    """
    Clean up a single tour-specific table.

    Args:
        dynamodb: boto3 DynamoDB resource
        table_name: Full table name
        key_attrs: List of key attribute names
        confirm: If True, actually delete; otherwise dry run

    Returns:
        tuple: (item_count, deleted_count, failed_count)
    """
    table = _get_table(dynamodb, table_name)
    if not table:
        print(f"  {table_name}: NOT FOUND (skipped)")
        return 0, 0, 0

    # Scan all keys
    keys = scan_all_keys(table, key_attrs)
    item_count = len(keys)

    if item_count == 0:
        print(f"  {table_name}: empty (0 items)")
        return 0, 0, 0

    if not confirm:
        print(f"  {table_name}: {item_count} items (would be deleted)")
        return item_count, 0, 0

    # Delete
    print(f"  {table_name}: deleting {item_count} items...")
    deleted, failed = delete_items(table, keys, table_name)
    print(f"    Deleted: {deleted}, Failed: {failed}")
    return item_count, deleted, failed


def cleanup_rider_profiles(dynamodb, stack_name, tour_id, confirm):
    """
    Clean up rider profiles linked to tour riders.

    Finds all profileIds from TourRider table, then deletes matching
    profiles from the shared RiderProfile table.

    Args:
        dynamodb: boto3 DynamoDB resource
        stack_name: Stack name prefix
        tour_id: Tour identifier
        confirm: If True, actually delete

    Returns:
        tuple: (item_count, deleted_count, failed_count)
    """
    # Get profileIds from TourRider table
    rider_tbl_name = f"{stack_name}-TourRider-{tour_id}"
    rider_table = _get_table(dynamodb, rider_tbl_name)
    if not rider_table:
        print(f"  Cannot find TourRider table — skipping profile cleanup")
        return 0, 0, 0

    # Scan for profileIds
    profile_ids = set()
    response = rider_table.scan(ProjectionExpression='profileId')
    for item in response.get('Items', []):
        if 'profileId' in item:
            profile_ids.add(item['profileId'])
    while 'LastEvaluatedKey' in response:
        response = rider_table.scan(
            ProjectionExpression='profileId',
            ExclusiveStartKey=response['LastEvaluatedKey'],
        )
        for item in response.get('Items', []):
            if 'profileId' in item:
                profile_ids.add(item['profileId'])

    if not profile_ids:
        print(f"  RiderProfile: no linked profiles found")
        return 0, 0, 0

    profile_tbl_name = f"{stack_name}-RiderProfile"
    profile_table = _get_table(dynamodb, profile_tbl_name)
    if not profile_table:
        print(f"  RiderProfile table '{profile_tbl_name}' not found — skipping")
        return 0, 0, 0

    keys = [{'profileId': pid} for pid in sorted(profile_ids)]

    if not confirm:
        print(f"  {profile_tbl_name}: {len(keys)} profiles linked to tour riders "
              f"(would be deleted)")
        return len(keys), 0, 0

    print(f"  {profile_tbl_name}: deleting {len(keys)} profiles...")
    deleted, failed = delete_items(profile_table, keys, profile_tbl_name)
    print(f"    Deleted: {deleted}, Failed: {failed}")
    return len(keys), deleted, failed


def main():
    parser = argparse.ArgumentParser(
        description='Clean up test data from tour-specific DynamoDB tables '
                    '(tables are NOT deleted)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run — see what would be deleted
  python scripts/cleanup_test_data.py --stack-name dev --tour-id TOT-2026

  # Delete all test data from tour-specific tables
  python scripts/cleanup_test_data.py --stack-name dev --tour-id TOT-2026 --confirm

  # Also remove generated rider profiles from shared RiderProfile table
  python scripts/cleanup_test_data.py --stack-name dev --tour-id TOT-2026 \\
      --include-profiles --confirm

  # Specify AWS region
  python scripts/cleanup_test_data.py --stack-name dev --tour-id TOT-2026 \\
      --region ap-south-1 --confirm
        """
    )

    parser.add_argument(
        '--stack-name', required=True,
        help='CloudFormation stack name (e.g., dev, test)'
    )
    parser.add_argument(
        '--tour-id', required=True,
        help='Tour identifier (e.g., TOT-2026)'
    )
    parser.add_argument(
        '--region', default=None,
        help='AWS region (default: from AWS config)'
    )
    parser.add_argument(
        '--include-profiles', action='store_true',
        help='Also delete rider profiles linked to this tour from the shared '
             'RiderProfile table'
    )
    parser.add_argument(
        '--confirm', action='store_true',
        help='Actually delete data. Without this flag, performs a dry run.'
    )

    args = parser.parse_args()

    session = boto3.Session(region_name=args.region) if args.region else boto3.Session()
    dynamodb = session.resource('dynamodb')
    region = session.region_name

    print("")
    print(f"=== Test Data Cleanup — {args.tour_id} ({args.stack_name}, {region}) ===")
    print("")

    if not args.confirm:
        print("  MODE: DRY RUN (no data will be deleted)")
        print("")

    total_items = 0
    total_deleted = 0
    total_failed = 0

    # Collect profile IDs BEFORE cleaning TourRider table (needed for
    # --include-profiles since TourRider data is used to find linked profiles)
    profile_keys = []
    if args.include_profiles:
        rider_tbl_name = f"{args.stack_name}-TourRider-{args.tour_id}"
        rider_table = _get_table(dynamodb, rider_tbl_name)
        if rider_table:
            response = rider_table.scan(ProjectionExpression='profileId')
            pids = {item['profileId'] for item in response.get('Items', [])
                    if 'profileId' in item}
            while 'LastEvaluatedKey' in response:
                response = rider_table.scan(
                    ProjectionExpression='profileId',
                    ExclusiveStartKey=response['LastEvaluatedKey'],
                )
                pids.update(item['profileId'] for item in response.get('Items', [])
                            if 'profileId' in item)
            profile_keys = [{'profileId': pid} for pid in sorted(pids)]

    # Clean tour-specific tables
    for table_type, key_attrs in TOUR_TABLE_KEYS.items():
        table_name = f"{args.stack_name}-{table_type}-{args.tour_id}"
        items, deleted, failed = cleanup_tour_table(
            dynamodb, table_name, key_attrs, args.confirm
        )
        total_items += items
        total_deleted += deleted
        total_failed += failed

    # Clean rider profiles using pre-collected profile IDs
    if args.include_profiles and profile_keys:
        print("")
        profile_tbl_name = f"{args.stack_name}-RiderProfile"
        profile_table = _get_table(dynamodb, profile_tbl_name)
        if profile_table:
            if not args.confirm:
                print(f"  {profile_tbl_name}: {len(profile_keys)} profiles linked "
                      f"to tour riders (would be deleted)")
                total_items += len(profile_keys)
            else:
                print(f"  {profile_tbl_name}: deleting {len(profile_keys)} profiles...")
                deleted, failed = delete_items(
                    profile_table, profile_keys, profile_tbl_name
                )
                print(f"    Deleted: {deleted}, Failed: {failed}")
                total_items += len(profile_keys)
                total_deleted += deleted
                total_failed += failed
        else:
            print(f"  {profile_tbl_name}: NOT FOUND (skipped)")
    elif args.include_profiles:
        print("")
        print("  No linked rider profiles found to clean up.")

    # Summary
    print("")
    print(f"=== Cleanup {'Complete' if args.confirm else 'Summary (Dry Run)'} ===")
    if args.confirm:
        print(f"  Deleted : {total_deleted}")
        if total_failed:
            print(f"  Failed  : {total_failed}")
    else:
        print(f"  Items found : {total_items}")
        print("")
        print("  Re-run with --confirm to delete these items.")
    print("")

    if total_failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
