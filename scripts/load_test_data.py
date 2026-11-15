#!/usr/bin/env python3
"""
Load JSON data into a DynamoDB table using batch_writer.

Usage:
    # Load rider profiles
    python scripts/load_test_data.py --file temp/rider_profiles.json --table-name dev-RiderProfile

    # Specify region
    python scripts/load_test_data.py --file temp/rider_profiles.json --table-name dev-RiderProfile --region ap-south-1
"""

import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError


def load_data(file_path, table_name, region=None):
    """
    Load JSON array from file into a DynamoDB table.

    Args:
        file_path: Path to JSON file containing array of items
        table_name: DynamoDB table name
        region: AWS region (optional)
    """
    # Read JSON file
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            items = json.load(f)
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in '{file_path}': {e}")
        sys.exit(1)

    if not isinstance(items, list):
        print("Error: JSON file must contain an array of items.")
        sys.exit(1)

    print(f"\nLoading {len(items)} items from '{file_path}' into '{table_name}'...")

    # Connect to DynamoDB
    session_kwargs = {}
    if region:
        session_kwargs["region_name"] = region
    session = boto3.Session(**session_kwargs)
    dynamodb = session.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # Verify table exists
    try:
        table.load()
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"Error: Table '{table_name}' not found.")
            sys.exit(1)
        raise

    # Upload using batch_writer
    loaded = 0
    failed = 0
    with table.batch_writer() as batch:
        for i, item in enumerate(items, 1):
            try:
                batch.put_item(Item=item)
                loaded += 1
            except ClientError as e:
                failed += 1
                print(f"  Failed item {i}: {e.response['Error']['Message']}")

            if i % 50 == 0:
                print(f"  Progress: {i}/{len(items)}...")

    print(f"\nDone! Loaded: {loaded}, Failed: {failed}")

    if failed:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Load JSON data into a DynamoDB table"
    )
    parser.add_argument(
        "--file", required=True,
        help="Path to JSON file containing array of items"
    )
    parser.add_argument(
        "--table-name", required=True,
        help="DynamoDB table name (e.g., dev-RiderProfile)"
    )
    parser.add_argument(
        "--region", default=None,
        help="AWS region (default: from AWS config)"
    )

    args = parser.parse_args()
    load_data(args.file, args.table_name, args.region)


if __name__ == "__main__":
    main()
