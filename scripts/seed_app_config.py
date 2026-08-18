#!/usr/bin/env python3
"""Seed AppConfig table with ID code configuration defaults."""

import argparse
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


def utc_now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def build_seed_items(updated_by):
    now = utc_now_iso()

    items = [
        {
            'configType': 'ID_CODE_FORMAT',
            'configId': 'SUBSTRING',
            'enabled': True,
            'description': 'Substring based extraction for production QR payloads',
            'version': 1,
            'updatedAt': now,
            'updatedBy': updated_by,
            'config': {
                'method': 'SUBSTRING',
                'idCode': {'startPosition': 12, 'length': 5},
                'idCodeType': {'startPosition': 1, 'length': 1},
                'personalCode': {'startPosition': 2, 'length': 4},
            },
        },
        {
            'configType': 'ID_CODE_FORMAT',
            'configId': 'REGEX',
            'enabled': False,
            'description': 'Regex based extraction fallback',
            'version': 1,
            'updatedAt': now,
            'updatedBy': updated_by,
            'config': {
                'method': 'REGEX',
                'idCode': {'pattern': 'TICKET:VID:([0-9A-Z]{5});', 'flags': '', 'group': 1},
                'idCodeType': {'pattern': '^(.)', 'flags': '', 'group': 1},
                'personalCode': {'pattern': '^.(.{4})$', 'flags': '', 'group': 1},
            },
        },
    ]

    id_code_types = [
        ('0', False, {'code': '0', 'type': None, 'name': 'Blank', 'description': 'Disabled blank type'}),
        ('1', True, {'code': '1', 'type': 'RIDER', 'name': 'Personal', 'description': 'Rider personal code'}),
        ('2', True, {'code': '2', 'type': 'CYCLE', 'name': 'Cycle', 'description': 'Cycle code placeholder'}),
        ('3', True, {'code': '3', 'type': 'BAGGAGE', 'name': 'Baggage 1', 'description': 'Baggage type 1'}),
        ('4', True, {'code': '4', 'type': 'BAGGAGE', 'name': 'Baggage 2', 'description': 'Baggage type 2'}),
        ('5', True, {'code': '5', 'type': 'BAGGAGE', 'name': 'Backpack', 'description': 'Backpack type'}),
        ('6', True, {'code': '6', 'type': 'BAGGAGE', 'name': 'Heavy bag', 'description': 'Heavy bag type'}),
        ('7', True, {'code': '7', 'type': 'BAGGAGE', 'name': 'Carton Box', 'description': 'Carton box type'}),
        ('8', True, {'code': '8', 'type': 'BAGGAGE', 'name': 'Gunny Bag', 'description': 'Gunny bag type'}),
        ('9', False, {'code': '9', 'type': None, 'name': 'Others', 'description': 'Disabled other type'}),
    ]

    for code, enabled, config in id_code_types:
        items.append(
            {
                'configType': 'ID_CODE_TYPE',
                'configId': code,
                'enabled': enabled,
                'description': f'ID code type mapping for code {code}',
                'version': 1,
                'updatedAt': now,
                'updatedBy': updated_by,
                'config': config,
            }
        )

    artifact_types = [
        ('ride-plan', 'tour', 'Tour of Tamil Nadu - Ride Plan'),
        ('rider-docket', 'tour', 'Rider Docket'),
        ('tour-elevation', 'tour', 'Tour Elevation'),
        ('training-challenge', 'tour', 'Training Challenge'),
        ('ride-elevation', 'ride', 'Ride Elevation'),
        ('gpx-file', 'ride', 'Ride route GPX File'),
        ('cue-sheet', 'ride', 'Cue Sheet'),
    ]

    for artifact_id, category, description in artifact_types:
        items.append(
            {
                'configType': 'ARTIFACTS',
                'configId': artifact_id,
                'enabled': True,
                'description': description,
                'version': 1,
                'updatedAt': now,
                'updatedBy': updated_by,
                'config': {'category': category},
            }
        )

    return items


def parse_args():
    parser = argparse.ArgumentParser(description='Seed AppConfig table defaults')
    parser.add_argument('--table-name', required=True, help='AppConfig table name (e.g. dev-AppConfig)')
    parser.add_argument('--region', default='ap-south-1', help='AWS region')
    parser.add_argument('--updated-by', default='seed-script', help='Value for updatedBy attribute')
    return parser.parse_args()


def main():
    args = parse_args()
    dynamodb = boto3.resource('dynamodb', region_name=args.region)
    table = dynamodb.Table(args.table_name)

    items = build_seed_items(args.updated_by)

    for item in items:
        try:
            table.put_item(Item=item)
            print(f"Upserted {item['configType']} / {item['configId']}")
        except ClientError as exc:
            print(f"Failed to upsert {item['configType']} / {item['configId']}: {exc}")
            raise

    print(f'Seeded {len(items)} AppConfig items into {args.table_name}')


if __name__ == '__main__':
    main()
