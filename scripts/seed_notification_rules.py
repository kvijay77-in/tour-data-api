#!/usr/bin/env python3
"""Seed default notification rules."""

import argparse
import os
from datetime import datetime, timezone
import boto3


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _default_rules(now_iso: str):
    return [
        {
            'ruleId': 'ANNOUNCEMENT',
            'enabled': True,
            'category': 'ANNOUNCEMENT',
            'audiences': ['ALL'],
            'titleTemplate': '{title}',
            'messageTemplate': '{message}',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'Notifications', 'paramKeys': []},
            'ttlHours': 168,
            'allowOverride': True,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'RIDE_OPENED',
            'enabled': True,
            'category': 'SYSTEM',
            'audiences': ['TOUR#{tourId}#ALL'],
            'titleTemplate': 'Ride {rideId} is open',
            'messageTemplate': 'Ride check-in is now open for tour {tourId}.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'RideStatus', 'paramKeys': ['tourId', 'rideId']},
            'ttlHours': 48,
            'allowOverride': False,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'RIDE_STARTED',
            'enabled': True,
            'category': 'ALERT',
            'audiences': ['TOUR#{tourId}#ALL'],
            'titleTemplate': 'Ride {rideId} started',
            'messageTemplate': 'Ride has started. Proceed to your assigned check-in flow.',
            'push': True,
            'priority': 'URGENT',
            'androidChannel': 'urgent',
            'target': {'screen': 'RideStatus', 'paramKeys': ['tourId', 'rideId']},
            'ttlHours': 24,
            'allowOverride': False,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'RIDE_CLOSED',
            'enabled': True,
            'category': 'SYSTEM',
            'audiences': ['TOUR#{tourId}#ALL'],
            'titleTemplate': 'Ride {rideId} closed',
            'messageTemplate': 'Ride check-in is now closed.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'RideStatus', 'paramKeys': ['tourId', 'rideId']},
            'ttlHours': 24,
            'allowOverride': False,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'PIT_STOP_OPENED',
            'enabled': True,
            'category': 'SYSTEM',
            'audiences': ['TOUR#{tourId}#ALL'],
            'titleTemplate': 'Pit stop {stageNumber} opened',
            'messageTemplate': 'Pit stop {stageNumber} is open for ride {rideId}.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'RideStatus', 'paramKeys': ['tourId', 'rideId', 'stageNumber']},
            'ttlHours': 24,
            'allowOverride': False,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'PIT_STOP_CLOSED',
            'enabled': True,
            'category': 'SYSTEM',
            'audiences': ['TOUR#{tourId}#ALL'],
            'titleTemplate': 'Pit stop {stageNumber} closed',
            'messageTemplate': 'Pit stop {stageNumber} is now closed.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'RideStatus', 'paramKeys': ['tourId', 'rideId', 'stageNumber']},
            'ttlHours': 24,
            'allowOverride': False,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'CHECKIN_CREATED',
            'enabled': True,
            'category': 'PERSONAL',
            'audiences': ['TOUR#{tourId}#RIDER#{riderId}'],
            'titleTemplate': 'Check-in recorded',
            'messageTemplate': 'Your check-in for ride {rideId} has been recorded.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'RiderCheckIns', 'paramKeys': ['tourId', 'rideId', 'riderId']},
            'ttlHours': 72,
            'allowOverride': False,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'CHECKIN_CANCELLED',
            'enabled': True,
            'category': 'PERSONAL',
            'audiences': ['TOUR#{tourId}#RIDER#{riderId}'],
            'titleTemplate': 'Check-in cancelled',
            'messageTemplate': 'A check-in entry for ride {rideId} was cancelled.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'RiderCheckIns', 'paramKeys': ['tourId', 'rideId', 'riderId']},
            'ttlHours': 72,
            'allowOverride': False,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'EVENT_COMPLETED_BY_RIDER',
            'enabled': True,
            'category': 'PERSONAL',
            'audiences': ['TOUR#{tourId}#RIDER#{riderId}'],
            'titleTemplate': 'Event completion recorded',
            'messageTemplate': 'You have completed event {eventName}.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'EventProgress', 'paramKeys': ['tourId', 'eventId', 'occurrenceId']},
            'ttlHours': 72,
            'allowOverride': False,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'RIDE_CHECKIN_REMINDER',
            'enabled': True,
            'category': 'ALERT',
            'audiences': ['TOUR#{tourId}#RIDER#{riderId}'],
            'titleTemplate': 'Ride check-in reminder',
            'messageTemplate': 'Please complete your ride check-in for ride {rideId}.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'RideStatus', 'paramKeys': ['tourId', 'rideId']},
            'ttlHours': 24,
            'allowOverride': True,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'EVENT_CHECKIN_REMINDER',
            'enabled': True,
            'category': 'ALERT',
            'audiences': ['TOUR#{tourId}#RIDER#{riderId}'],
            'titleTemplate': 'Event check-in reminder',
            'messageTemplate': 'Please complete your event check-in.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'EventProgress', 'paramKeys': ['tourId', 'eventId', 'occurrenceId']},
            'ttlHours': 24,
            'allowOverride': True,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'RIDER_EXITED',
            'enabled': True,
            'category': 'PERSONAL',
            'audiences': ['PROFILE#{profileId}'],
            'titleTemplate': 'Tour status updated',
            'messageTemplate': 'Your rider status for tour {tourId} is now {status}.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'RiderTours', 'paramKeys': ['tourId']},
            'ttlHours': 168,
            'allowOverride': False,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'REGISTRATION_STATUS_CHANGED',
            'enabled': True,
            'category': 'PERSONAL',
            'audiences': ['PROFILE#{profileId}'],
            'titleTemplate': 'Registration status changed',
            'messageTemplate': 'Your registration status for tour {tourId} is now {status}.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'RiderTours', 'paramKeys': ['tourId']},
            'ttlHours': 168,
            'allowOverride': False,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
        {
            'ruleId': 'HOTEL_ALLOCATION_PUBLISHED',
            'enabled': True,
            'category': 'SYSTEM',
            'audiences': ['TOUR#{tourId}#APP#RIDER'],
            'titleTemplate': 'Hotel allocation updated',
            'messageTemplate': 'Hotel stay allocation for tour {tourId} has been updated.',
            'push': True,
            'priority': 'NORMAL',
            'androidChannel': 'general',
            'target': {'screen': 'HotelStays', 'paramKeys': ['tourId']},
            'ttlHours': 168,
            'allowOverride': False,
            'version': 1,
            'updatedAt': now_iso,
            'updatedBy': 'seed-script',
        },
    ]


def main():
    parser = argparse.ArgumentParser(description='Seed default notification rule rows')
    parser.add_argument('--table-name', required=True, help='NotificationRule table name')
    parser.add_argument('--region', default=os.environ.get('AWS_REGION', 'ap-south-1'))
    args = parser.parse_args()

    table = boto3.resource('dynamodb', region_name=args.region).Table(args.table_name)

    rules = _default_rules(utc_now_iso())
    seeded = 0
    skipped = 0
    for rule in rules:
        rule_id = rule['ruleId']
        existing = table.get_item(Key={'ruleId': rule_id}).get('Item')
        if existing:
            skipped += 1
            print(f'{rule_id} already exists; skipping')
            continue
        table.put_item(Item=rule)
        seeded += 1
        print(f'Seeded {rule_id}')

    print(f'Done. Seeded={seeded}, Skipped={skipped}, Total={len(rules)}')


if __name__ == '__main__':
    main()
