#!/usr/bin/env python3
"""Seed default notification rules."""

import argparse
import os

import boto3

from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def main():
    parser = argparse.ArgumentParser(description='Seed default notification rule rows')
    parser.add_argument('--table-name', required=True, help='NotificationRule table name')
    parser.add_argument('--region', default=os.environ.get('AWS_REGION', 'ap-south-1'))
    args = parser.parse_args()

    table = boto3.resource('dynamodb', region_name=args.region).Table(args.table_name)

    existing = table.get_item(Key={'ruleId': 'ANNOUNCEMENT'}).get('Item')
    if existing:
        print('ANNOUNCEMENT rule already exists; skipping')
        return

    table.put_item(Item={
        'ruleId': 'ANNOUNCEMENT',
        'enabled': True,
        'category': 'ANNOUNCEMENT',
        'audiences': ['ALL'],
        'titleTemplate': '{title}',
        'bodyTemplate': '{message}',
        'push': True,
        'priority': 'NORMAL',
        'androidChannel': 'general',
        'target': {'screen': 'Notifications', 'paramKeys': []},
        'ttlHours': 168,
        'allowOverride': True,
        'version': 1,
        'updatedAt': utc_now_iso(),
        'updatedBy': 'seed-script',
    })
    print('Seeded ANNOUNCEMENT notification rule')


if __name__ == '__main__':
    main()
