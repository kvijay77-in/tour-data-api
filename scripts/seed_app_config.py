#!/usr/bin/env python3
"""Seed AppConfig table with platform defaults."""

import argparse
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# Runtime-tunable config: seeded once, never overwritten by later deploys.
INSERT_ONLY_CONFIG_TYPES = {'HOTEL_UPLOAD', 'RIDER_PROFILE_SECTION', 'RIDER_PROFILE_ATTRIBUTE', 'LOV'}


def utc_now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _build_profile_sections(now, updated_by):
    section_ids = ['personal', 'contact', 'address', 'emergency', 'medical', 'preferences', 'organizer']
    return [
        {
            'configType': 'RIDER_PROFILE_SECTION',
            'configId': section_id,
            'enabled': True,
            'description': f'Rider profile section: {section_id}',
            'version': 1,
            'updatedAt': now,
            'updatedBy': updated_by,
            'config': {'label': section_id.replace('-', ' ').title(), 'order': idx + 1},
        }
        for idx, section_id in enumerate(section_ids)
    ]


def _build_lov(now, updated_by, lov_id, label, items, parent_lov_id=None):
    return {
        'configType': 'LOV',
        'configId': lov_id,
        'enabled': True,
        'description': f'LOV for {label}',
        'version': 1,
        'updatedAt': now,
        'updatedBy': updated_by,
        'config': {
            'label': label,
            'parentLovId': parent_lov_id,
            'items': items,
        },
    }


def _build_profile_attributes(now, updated_by):
    attrs = [
        {
            'configId': 'name',
            'sectionId': 'personal',
            'type': 'TEXT',
            'storage': {'scope': 'CORE', 'path': 'name'},
            'required': True,
            'system': True,
            'order': 1,
            'label': 'Name',
        },
        {
            'configId': 'email',
            'sectionId': 'contact',
            'type': 'EMAIL',
            'handler': 'COGNITO_EMAIL',
            'storage': {'scope': 'CORE', 'path': 'email'},
            'required': True,
            'adminOnly': True,
            'system': True,
            'order': 1,
            'label': 'Email',
        },
        {
            'configId': 'phone',
            'sectionId': 'contact',
            'type': 'PHONE',
            'storage': {'scope': 'CORE', 'path': 'phone'},
            'required': True,
            'system': True,
            'order': 2,
            'label': 'Phone',
        },
        {
            'configId': 'photo',
            'sectionId': 'personal',
            'type': 'IMAGE',
            'handler': 'PROFILE_PHOTO',
            'storage': {'scope': 'CORE', 'path': 'photoS3Key'},
            'required': True,
            'system': True,
            'order': 2,
            'label': 'Photo',
            'validation': {'allowedMimeTypes': ['image/jpeg', 'image/png'], 'maxFileSizeBytes': 5242880},
        },
        {
            'configId': 'personalCode',
            'sectionId': 'organizer',
            'type': 'TEXT',
            'handler': 'PERSONAL_CODE',
            'storage': {'scope': 'CORE', 'path': 'personalCode'},
            'adminOnly': True,
            'system': True,
            'order': 1,
            'label': 'Personal Code',
        },
        {
            'configId': 'dateOfBirth',
            'sectionId': 'personal',
            'type': 'DATE',
            'storage': {'scope': 'CORE', 'path': 'dateOfBirth'},
            'required': True,
            'order': 3,
            'label': 'Date of Birth',
            'validation': {'maxDate': '-18y'},
        },
        {
            'configId': 'gender',
            'sectionId': 'personal',
            'type': 'SELECT',
            'storage': {'scope': 'CORE', 'path': 'gender'},
            'required': True,
            'order': 4,
            'label': 'Gender',
            'lovId': 'GENDER',
        },
        {
            'configId': 'address',
            'sectionId': 'address',
            'type': 'GROUP',
            'storage': {'scope': 'CORE', 'path': 'address'},
            'required': True,
            'order': 1,
            'label': 'Address',
            'fields': [
                {'key': 'line1', 'type': 'TEXT', 'required': True},
                {'key': 'line2', 'type': 'TEXT', 'required': False},
                {'key': 'city', 'type': 'TEXT', 'required': True},
                {'key': 'country', 'type': 'SELECT', 'required': True, 'lovId': 'COUNTRY'},
                {'key': 'state', 'type': 'SELECT', 'required': True, 'lovId': 'STATE', 'dependsOn': 'country', 'fallbackToText': True},
                {'key': 'postalCode', 'type': 'TEXT', 'required': True},
            ],
        },
        {
            'configId': 'emergencyContact',
            'sectionId': 'emergency',
            'type': 'GROUP',
            'storage': {'scope': 'CORE', 'path': 'emergencyContact'},
            'required': True,
            'order': 1,
            'label': 'Emergency Contact',
            'fields': [
                {'key': 'name', 'type': 'TEXT', 'required': True},
                {'key': 'relation', 'type': 'SELECT', 'required': True, 'lovId': 'RELATIONSHIP'},
                {'key': 'phone', 'type': 'PHONE', 'required': True},
            ],
        },
        {
            'configId': 'dietaryPreference',
            'sectionId': 'preferences',
            'type': 'SELECT',
            'storage': {'scope': 'ATTRIBUTES'},
            'order': 1,
            'label': 'Dietary Preference',
            'lovId': 'DIETARY_PREFERENCE',
            'visibleToAllMgmtUsers': True,
        },
        {
            'configId': 'bloodGroup',
            'sectionId': 'medical',
            'type': 'SELECT',
            'storage': {'scope': 'ATTRIBUTES'},
            'order': 1,
            'label': 'Blood Group',
            'lovId': 'BLOOD_GROUP',
            'sensitive': True,
            'visibleToAllMgmtUsers': False,
        },
        {
            'configId': 'hasMedicalCondition',
            'sectionId': 'medical',
            'type': 'BOOLEAN',
            'storage': {'scope': 'ATTRIBUTES'},
            'order': 2,
            'label': 'Has Medical Condition',
            'sensitive': True,
            'visibleToAllMgmtUsers': False,
        },
        {
            'configId': 'medicalConditions',
            'sectionId': 'medical',
            'type': 'TEXTAREA',
            'storage': {'scope': 'ATTRIBUTES'},
            'order': 3,
            'label': 'Medical Conditions',
            'sensitive': True,
            'visibleToAllMgmtUsers': False,
            'validation': {'maxLength': 1000},
            'visibleWhen': {'attribute': 'hasMedicalCondition', 'op': 'EQ', 'value': True},
        },
    ]

    items = []
    for attr in attrs:
        cfg = {
            'label': attr['label'],
            'sectionId': attr['sectionId'],
            'order': attr.get('order', 1),
            'type': attr['type'],
            'storage': attr['storage'],
            'required': bool(attr.get('required', False)),
            'adminOnly': bool(attr.get('adminOnly', False)),
            'sensitive': bool(attr.get('sensitive', False)),
            'visibleToAllMgmtUsers': bool(attr.get('visibleToAllMgmtUsers', True)),
            'system': bool(attr.get('system', False)),
            'validation': attr.get('validation', {}),
        }
        if attr.get('handler'):
            cfg['handler'] = attr['handler']
        if attr.get('lovId'):
            cfg['lovId'] = attr['lovId']
        if attr.get('fields'):
            cfg['fields'] = attr['fields']
        if attr.get('visibleWhen'):
            cfg['visibleWhen'] = attr['visibleWhen']

        items.append(
            {
                'configType': 'RIDER_PROFILE_ATTRIBUTE',
                'configId': attr['configId'],
                'enabled': True,
                'description': f"Rider profile attribute: {attr['configId']}",
                'version': 1,
                'updatedAt': now,
                'updatedBy': updated_by,
                'config': cfg,
            }
        )
    return items


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
            'config': {'method': 'SUBSTRING', 'idCode': {'startPosition': 12, 'length': 5}, 'idCodeType': {'startPosition': 1, 'length': 1}, 'personalCode': {'startPosition': 2, 'length': 4}},
        },
        {
            'configType': 'ID_CODE_FORMAT',
            'configId': 'REGEX',
            'enabled': False,
            'description': 'Regex based extraction fallback',
            'version': 1,
            'updatedAt': now,
            'updatedBy': updated_by,
            'config': {'method': 'REGEX', 'idCode': {'pattern': 'TICKET:VID:([0-9A-Z]{5});', 'flags': '', 'group': 1}, 'idCodeType': {'pattern': '^(.)', 'flags': '', 'group': 1}, 'personalCode': {'pattern': '^.(.{4})$', 'flags': '', 'group': 1}},
        },
        {
            'configType': 'HOTEL_CSV_FILE',
            'configId': 'MAX-SIZE',
            'enabled': True,
            'description': 'Hotel room allocation CSV File Maximum Size',
            'version': 1,
            'updatedAt': now,
            'updatedBy': updated_by,
            'config': {'maxSize': '5', 'maxSizeUnit': 'MB'},
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
        items.append({'configType': 'ID_CODE_TYPE', 'configId': code, 'enabled': enabled, 'description': f'ID code type mapping for code {code}', 'version': 1, 'updatedAt': now, 'updatedBy': updated_by, 'config': config})

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
        items.append({'configType': 'ARTIFACTS', 'configId': artifact_id, 'enabled': True, 'description': description, 'version': 1, 'updatedAt': now, 'updatedBy': updated_by, 'config': {'category': category}})

    items.append({'configType': 'HOTEL_UPLOAD', 'configId': 'PROCESSING', 'enabled': True, 'description': 'Hotel allocation CSV processing limits', 'version': 1, 'updatedAt': now, 'updatedBy': updated_by, 'config': {'maxFileSizeBytes': 1048576, 'maxDataRows': 500, 'maxStayDates': 31, 'maxStoredErrors': 200, 'timeReserveSeconds': 20}})

    country_items = [
        {'value': 'IN', 'label': 'India', 'order': 1, 'enabled': True, 'meta': {'callingCode': '91'}},
        {'value': 'US', 'label': 'United States', 'order': 2, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'GB', 'label': 'United Kingdom', 'order': 3, 'enabled': True, 'meta': {'callingCode': '44'}},
        {'value': 'AU', 'label': 'Australia', 'order': 4, 'enabled': True, 'meta': {'callingCode': '61'}},
        {'value': 'SG', 'label': 'Singapore', 'order': 5, 'enabled': True, 'meta': {'callingCode': '65'}},
    ]
    state_values = [
        'AN', 'AP', 'AR', 'AS', 'BR', 'CG', 'CH', 'DH', 'DL', 'GA', 'GJ', 'HR', 'HP', 'JK', 'JH',
        'KA', 'KL', 'LA', 'LD', 'MP', 'MH', 'MN', 'ML', 'MZ', 'NL', 'OR', 'PY', 'PB', 'RJ', 'SK',
        'TN', 'TS', 'TR', 'UP', 'UK', 'WB'
    ]
    state_items = [{'value': code, 'label': code, 'order': idx + 1, 'enabled': True, 'parent': 'IN'} for idx, code in enumerate(state_values)]

    items.extend([
        _build_lov(now, updated_by, 'COUNTRY', 'Country', country_items),
        _build_lov(now, updated_by, 'STATE', 'State', state_items, parent_lov_id='COUNTRY'),
        _build_lov(now, updated_by, 'GENDER', 'Gender', [
            {'value': 'Male', 'label': 'Male', 'order': 1, 'enabled': True},
            {'value': 'Female', 'label': 'Female', 'order': 2, 'enabled': True},
            {'value': 'Other', 'label': 'Other', 'order': 3, 'enabled': True},
            {'value': 'Prefer not to say', 'label': 'Prefer not to say', 'order': 4, 'enabled': True},
        ]),
        _build_lov(now, updated_by, 'DIETARY_PREFERENCE', 'Dietary Preference', [
            {'value': 'VEG', 'label': 'Vegetarian', 'order': 1, 'enabled': True},
            {'value': 'NON_VEG', 'label': 'Non Vegetarian', 'order': 2, 'enabled': True},
            {'value': 'VEGAN', 'label': 'Vegan', 'order': 3, 'enabled': True},
            {'value': 'EGGETARIAN', 'label': 'Eggetarian', 'order': 4, 'enabled': True},
            {'value': 'JAIN', 'label': 'Jain', 'order': 5, 'enabled': True},
        ]),
        _build_lov(now, updated_by, 'BLOOD_GROUP', 'Blood Group', [
            {'value': 'A+', 'label': 'A+', 'order': 1, 'enabled': True},
            {'value': 'A-', 'label': 'A-', 'order': 2, 'enabled': True},
            {'value': 'B+', 'label': 'B+', 'order': 3, 'enabled': True},
            {'value': 'B-', 'label': 'B-', 'order': 4, 'enabled': True},
            {'value': 'AB+', 'label': 'AB+', 'order': 5, 'enabled': True},
            {'value': 'AB-', 'label': 'AB-', 'order': 6, 'enabled': True},
            {'value': 'O+', 'label': 'O+', 'order': 7, 'enabled': True},
            {'value': 'O-', 'label': 'O-', 'order': 8, 'enabled': True},
        ]),
        _build_lov(now, updated_by, 'RELATIONSHIP', 'Relationship', [
            {'value': 'PARENT', 'label': 'Parent', 'order': 1, 'enabled': True},
            {'value': 'SPOUSE', 'label': 'Spouse', 'order': 2, 'enabled': True},
            {'value': 'SIBLING', 'label': 'Sibling', 'order': 3, 'enabled': True},
            {'value': 'FRIEND', 'label': 'Friend', 'order': 4, 'enabled': True},
            {'value': 'OTHER', 'label': 'Other', 'order': 5, 'enabled': True},
        ]),
    ])

    items.extend(_build_profile_sections(now, updated_by))
    items.extend(_build_profile_attributes(now, updated_by))

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
            if item['configType'] in INSERT_ONLY_CONFIG_TYPES:
                table.put_item(Item=item, ConditionExpression='attribute_not_exists(configType)')
            else:
                table.put_item(Item=item)
            print(f"Upserted {item['configType']} / {item['configId']}")
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                print(f"Kept existing {item['configType']} / {item['configId']}")
                continue
            print(f"Failed to upsert {item['configType']} / {item['configId']}: {exc}")
            raise

    print(f'Seeded {len(items)} AppConfig items into {args.table_name}')


if __name__ == '__main__':
    main()
