#!/usr/bin/env python3
"""Seed AppConfig table with platform defaults."""

import argparse
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# Runtime-tunable config: seeded once, never overwritten by later deploys.
INSERT_ONLY_CONFIG_TYPES = {'HOTEL_UPLOAD', 'RIDER_PROFILE_SECTION', 'RIDER_PROFILE_ATTRIBUTE', 'LOV'}
FORCE_OVERWRITE_PROFILE_CONFIG_TYPES = {'RIDER_PROFILE_SECTION', 'RIDER_PROFILE_ATTRIBUTE', 'LOV'}


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
                {'key': 'relation', 'type': 'TEXT', 'required': True},
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
        {'value': 'AF', 'label': 'Afghanistan', 'order': 2, 'enabled': True, 'meta': {'callingCode': '93'}},
        {'value': 'AL', 'label': 'Albania', 'order': 3, 'enabled': True, 'meta': {'callingCode': '355'}},
        {'value': 'DZ', 'label': 'Algeria', 'order': 4, 'enabled': True, 'meta': {'callingCode': '213'}},
        {'value': 'AS', 'label': 'American Samoa', 'order': 5, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'AD', 'label': 'Andorra', 'order': 6, 'enabled': True, 'meta': {'callingCode': '376'}},
        {'value': 'AO', 'label': 'Angola', 'order': 7, 'enabled': True, 'meta': {'callingCode': '244'}},
        {'value': 'AI', 'label': 'Anguilla', 'order': 8, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'AQ', 'label': 'Antarctica', 'order': 9, 'enabled': True, 'meta': {'callingCode': ''}},
        {'value': 'AG', 'label': 'Antigua and Barbuda', 'order': 10, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'AR', 'label': 'Argentina', 'order': 11, 'enabled': True, 'meta': {'callingCode': '54'}},
        {'value': 'AM', 'label': 'Armenia', 'order': 12, 'enabled': True, 'meta': {'callingCode': '374'}},
        {'value': 'AW', 'label': 'Aruba', 'order': 13, 'enabled': True, 'meta': {'callingCode': '297'}},
        {'value': 'AU', 'label': 'Australia', 'order': 14, 'enabled': True, 'meta': {'callingCode': '61'}},
        {'value': 'AT', 'label': 'Austria', 'order': 15, 'enabled': True, 'meta': {'callingCode': '43'}},
        {'value': 'AZ', 'label': 'Azerbaijan', 'order': 16, 'enabled': True, 'meta': {'callingCode': '994'}},
        {'value': 'BS', 'label': 'Bahamas', 'order': 17, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'BH', 'label': 'Bahrain', 'order': 18, 'enabled': True, 'meta': {'callingCode': '973'}},
        {'value': 'BD', 'label': 'Bangladesh', 'order': 19, 'enabled': True, 'meta': {'callingCode': '880'}},
        {'value': 'BB', 'label': 'Barbados', 'order': 20, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'BY', 'label': 'Belarus', 'order': 21, 'enabled': True, 'meta': {'callingCode': '375'}},
        {'value': 'BE', 'label': 'Belgium', 'order': 22, 'enabled': True, 'meta': {'callingCode': '32'}},
        {'value': 'BZ', 'label': 'Belize', 'order': 23, 'enabled': True, 'meta': {'callingCode': '501'}},
        {'value': 'BJ', 'label': 'Benin', 'order': 24, 'enabled': True, 'meta': {'callingCode': '229'}},
        {'value': 'BM', 'label': 'Bermuda', 'order': 25, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'BT', 'label': 'Bhutan', 'order': 26, 'enabled': True, 'meta': {'callingCode': '975'}},
        {'value': 'BO', 'label': 'Bolivia, Plurinational State of', 'order': 27, 'enabled': True, 'meta': {'callingCode': '591'}},
        {'value': 'BQ', 'label': 'Bonaire, Sint Eustatius and Saba', 'order': 28, 'enabled': True, 'meta': {'callingCode': '599'}},
        {'value': 'BA', 'label': 'Bosnia and Herzegovina', 'order': 29, 'enabled': True, 'meta': {'callingCode': '387'}},
        {'value': 'BW', 'label': 'Botswana', 'order': 30, 'enabled': True, 'meta': {'callingCode': '267'}},
        {'value': 'BV', 'label': 'Bouvet Island', 'order': 31, 'enabled': True, 'meta': {'callingCode': ''}},
        {'value': 'BR', 'label': 'Brazil', 'order': 32, 'enabled': True, 'meta': {'callingCode': '55'}},
        {'value': 'IO', 'label': 'British Indian Ocean Territory', 'order': 33, 'enabled': True, 'meta': {'callingCode': '246'}},
        {'value': 'BN', 'label': 'Brunei Darussalam', 'order': 34, 'enabled': True, 'meta': {'callingCode': '673'}},
        {'value': 'BG', 'label': 'Bulgaria', 'order': 35, 'enabled': True, 'meta': {'callingCode': '359'}},
        {'value': 'BF', 'label': 'Burkina Faso', 'order': 36, 'enabled': True, 'meta': {'callingCode': '226'}},
        {'value': 'BI', 'label': 'Burundi', 'order': 37, 'enabled': True, 'meta': {'callingCode': '257'}},
        {'value': 'CV', 'label': 'Cabo Verde', 'order': 38, 'enabled': True, 'meta': {'callingCode': '238'}},
        {'value': 'KH', 'label': 'Cambodia', 'order': 39, 'enabled': True, 'meta': {'callingCode': '855'}},
        {'value': 'CM', 'label': 'Cameroon', 'order': 40, 'enabled': True, 'meta': {'callingCode': '237'}},
        {'value': 'CA', 'label': 'Canada', 'order': 41, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'KY', 'label': 'Cayman Islands', 'order': 42, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'CF', 'label': 'Central African Republic', 'order': 43, 'enabled': True, 'meta': {'callingCode': '236'}},
        {'value': 'TD', 'label': 'Chad', 'order': 44, 'enabled': True, 'meta': {'callingCode': '235'}},
        {'value': 'CL', 'label': 'Chile', 'order': 45, 'enabled': True, 'meta': {'callingCode': '56'}},
        {'value': 'CN', 'label': 'China', 'order': 46, 'enabled': True, 'meta': {'callingCode': '86'}},
        {'value': 'CX', 'label': 'Christmas Island', 'order': 47, 'enabled': True, 'meta': {'callingCode': '61'}},
        {'value': 'CC', 'label': 'Cocos (Keeling) Islands', 'order': 48, 'enabled': True, 'meta': {'callingCode': '61'}},
        {'value': 'CO', 'label': 'Colombia', 'order': 49, 'enabled': True, 'meta': {'callingCode': '57'}},
        {'value': 'KM', 'label': 'Comoros', 'order': 50, 'enabled': True, 'meta': {'callingCode': '269'}},
        {'value': 'CG', 'label': 'Congo', 'order': 51, 'enabled': True, 'meta': {'callingCode': '242'}},
        {'value': 'CD', 'label': 'Congo, The Democratic Republic of the', 'order': 52, 'enabled': True, 'meta': {'callingCode': '243'}},
        {'value': 'CK', 'label': 'Cook Islands', 'order': 53, 'enabled': True, 'meta': {'callingCode': '682'}},
        {'value': 'CR', 'label': 'Costa Rica', 'order': 54, 'enabled': True, 'meta': {'callingCode': '506'}},
        {'value': 'HR', 'label': 'Croatia', 'order': 55, 'enabled': True, 'meta': {'callingCode': '385'}},
        {'value': 'CU', 'label': 'Cuba', 'order': 56, 'enabled': True, 'meta': {'callingCode': '53'}},
        {'value': 'CW', 'label': 'Curaçao', 'order': 57, 'enabled': True, 'meta': {'callingCode': '599'}},
        {'value': 'CY', 'label': 'Cyprus', 'order': 58, 'enabled': True, 'meta': {'callingCode': '357'}},
        {'value': 'CZ', 'label': 'Czechia', 'order': 59, 'enabled': True, 'meta': {'callingCode': '420'}},
        {'value': 'CI', 'label': 'Côte d\'Ivoire', 'order': 60, 'enabled': True, 'meta': {'callingCode': '225'}},
        {'value': 'DK', 'label': 'Denmark', 'order': 61, 'enabled': True, 'meta': {'callingCode': '45'}},
        {'value': 'DJ', 'label': 'Djibouti', 'order': 62, 'enabled': True, 'meta': {'callingCode': '253'}},
        {'value': 'DM', 'label': 'Dominica', 'order': 63, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'DO', 'label': 'Dominican Republic', 'order': 64, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'EC', 'label': 'Ecuador', 'order': 65, 'enabled': True, 'meta': {'callingCode': '593'}},
        {'value': 'EG', 'label': 'Egypt', 'order': 66, 'enabled': True, 'meta': {'callingCode': '20'}},
        {'value': 'SV', 'label': 'El Salvador', 'order': 67, 'enabled': True, 'meta': {'callingCode': '503'}},
        {'value': 'GQ', 'label': 'Equatorial Guinea', 'order': 68, 'enabled': True, 'meta': {'callingCode': '240'}},
        {'value': 'ER', 'label': 'Eritrea', 'order': 69, 'enabled': True, 'meta': {'callingCode': '291'}},
        {'value': 'EE', 'label': 'Estonia', 'order': 70, 'enabled': True, 'meta': {'callingCode': '372'}},
        {'value': 'SZ', 'label': 'Eswatini', 'order': 71, 'enabled': True, 'meta': {'callingCode': '268'}},
        {'value': 'ET', 'label': 'Ethiopia', 'order': 72, 'enabled': True, 'meta': {'callingCode': '251'}},
        {'value': 'FK', 'label': 'Falkland Islands (Malvinas)', 'order': 73, 'enabled': True, 'meta': {'callingCode': '500'}},
        {'value': 'FO', 'label': 'Faroe Islands', 'order': 74, 'enabled': True, 'meta': {'callingCode': '298'}},
        {'value': 'FJ', 'label': 'Fiji', 'order': 75, 'enabled': True, 'meta': {'callingCode': '679'}},
        {'value': 'FI', 'label': 'Finland', 'order': 76, 'enabled': True, 'meta': {'callingCode': '358'}},
        {'value': 'FR', 'label': 'France', 'order': 77, 'enabled': True, 'meta': {'callingCode': '33'}},
        {'value': 'GF', 'label': 'French Guiana', 'order': 78, 'enabled': True, 'meta': {'callingCode': '594'}},
        {'value': 'PF', 'label': 'French Polynesia', 'order': 79, 'enabled': True, 'meta': {'callingCode': '689'}},
        {'value': 'TF', 'label': 'French Southern Territories', 'order': 80, 'enabled': True, 'meta': {'callingCode': ''}},
        {'value': 'GA', 'label': 'Gabon', 'order': 81, 'enabled': True, 'meta': {'callingCode': '241'}},
        {'value': 'GM', 'label': 'Gambia', 'order': 82, 'enabled': True, 'meta': {'callingCode': '220'}},
        {'value': 'GE', 'label': 'Georgia', 'order': 83, 'enabled': True, 'meta': {'callingCode': '995'}},
        {'value': 'DE', 'label': 'Germany', 'order': 84, 'enabled': True, 'meta': {'callingCode': '49'}},
        {'value': 'GH', 'label': 'Ghana', 'order': 85, 'enabled': True, 'meta': {'callingCode': '233'}},
        {'value': 'GI', 'label': 'Gibraltar', 'order': 86, 'enabled': True, 'meta': {'callingCode': '350'}},
        {'value': 'GR', 'label': 'Greece', 'order': 87, 'enabled': True, 'meta': {'callingCode': '30'}},
        {'value': 'GL', 'label': 'Greenland', 'order': 88, 'enabled': True, 'meta': {'callingCode': '299'}},
        {'value': 'GD', 'label': 'Grenada', 'order': 89, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'GP', 'label': 'Guadeloupe', 'order': 90, 'enabled': True, 'meta': {'callingCode': '590'}},
        {'value': 'GU', 'label': 'Guam', 'order': 91, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'GT', 'label': 'Guatemala', 'order': 92, 'enabled': True, 'meta': {'callingCode': '502'}},
        {'value': 'GG', 'label': 'Guernsey', 'order': 93, 'enabled': True, 'meta': {'callingCode': '44'}},
        {'value': 'GN', 'label': 'Guinea', 'order': 94, 'enabled': True, 'meta': {'callingCode': '224'}},
        {'value': 'GW', 'label': 'Guinea-Bissau', 'order': 95, 'enabled': True, 'meta': {'callingCode': '245'}},
        {'value': 'GY', 'label': 'Guyana', 'order': 96, 'enabled': True, 'meta': {'callingCode': '592'}},
        {'value': 'HT', 'label': 'Haiti', 'order': 97, 'enabled': True, 'meta': {'callingCode': '509'}},
        {'value': 'HM', 'label': 'Heard Island and McDonald Islands', 'order': 98, 'enabled': True, 'meta': {'callingCode': ''}},
        {'value': 'VA', 'label': 'Holy See (Vatican City State)', 'order': 99, 'enabled': True, 'meta': {'callingCode': '39'}},
        {'value': 'HN', 'label': 'Honduras', 'order': 100, 'enabled': True, 'meta': {'callingCode': '504'}},
        {'value': 'HK', 'label': 'Hong Kong', 'order': 101, 'enabled': True, 'meta': {'callingCode': '852'}},
        {'value': 'HU', 'label': 'Hungary', 'order': 102, 'enabled': True, 'meta': {'callingCode': '36'}},
        {'value': 'IS', 'label': 'Iceland', 'order': 103, 'enabled': True, 'meta': {'callingCode': '354'}},
        {'value': 'ID', 'label': 'Indonesia', 'order': 104, 'enabled': True, 'meta': {'callingCode': '62'}},
        {'value': 'IR', 'label': 'Iran, Islamic Republic of', 'order': 105, 'enabled': True, 'meta': {'callingCode': '98'}},
        {'value': 'IQ', 'label': 'Iraq', 'order': 106, 'enabled': True, 'meta': {'callingCode': '964'}},
        {'value': 'IE', 'label': 'Ireland', 'order': 107, 'enabled': True, 'meta': {'callingCode': '353'}},
        {'value': 'IM', 'label': 'Isle of Man', 'order': 108, 'enabled': True, 'meta': {'callingCode': '44'}},
        {'value': 'IL', 'label': 'Israel', 'order': 109, 'enabled': True, 'meta': {'callingCode': '972'}},
        {'value': 'IT', 'label': 'Italy', 'order': 110, 'enabled': True, 'meta': {'callingCode': '39'}},
        {'value': 'JM', 'label': 'Jamaica', 'order': 111, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'JP', 'label': 'Japan', 'order': 112, 'enabled': True, 'meta': {'callingCode': '81'}},
        {'value': 'JE', 'label': 'Jersey', 'order': 113, 'enabled': True, 'meta': {'callingCode': '44'}},
        {'value': 'JO', 'label': 'Jordan', 'order': 114, 'enabled': True, 'meta': {'callingCode': '962'}},
        {'value': 'KZ', 'label': 'Kazakhstan', 'order': 115, 'enabled': True, 'meta': {'callingCode': '7'}},
        {'value': 'KE', 'label': 'Kenya', 'order': 116, 'enabled': True, 'meta': {'callingCode': '254'}},
        {'value': 'KI', 'label': 'Kiribati', 'order': 117, 'enabled': True, 'meta': {'callingCode': '686'}},
        {'value': 'KP', 'label': 'Korea, Democratic People\'s Republic of', 'order': 118, 'enabled': True, 'meta': {'callingCode': '850'}},
        {'value': 'KR', 'label': 'Korea, Republic of', 'order': 119, 'enabled': True, 'meta': {'callingCode': '82'}},
        {'value': 'KW', 'label': 'Kuwait', 'order': 120, 'enabled': True, 'meta': {'callingCode': '965'}},
        {'value': 'KG', 'label': 'Kyrgyzstan', 'order': 121, 'enabled': True, 'meta': {'callingCode': '996'}},
        {'value': 'LA', 'label': 'Lao People\'s Democratic Republic', 'order': 122, 'enabled': True, 'meta': {'callingCode': '856'}},
        {'value': 'LV', 'label': 'Latvia', 'order': 123, 'enabled': True, 'meta': {'callingCode': '371'}},
        {'value': 'LB', 'label': 'Lebanon', 'order': 124, 'enabled': True, 'meta': {'callingCode': '961'}},
        {'value': 'LS', 'label': 'Lesotho', 'order': 125, 'enabled': True, 'meta': {'callingCode': '266'}},
        {'value': 'LR', 'label': 'Liberia', 'order': 126, 'enabled': True, 'meta': {'callingCode': '231'}},
        {'value': 'LY', 'label': 'Libya', 'order': 127, 'enabled': True, 'meta': {'callingCode': '218'}},
        {'value': 'LI', 'label': 'Liechtenstein', 'order': 128, 'enabled': True, 'meta': {'callingCode': '423'}},
        {'value': 'LT', 'label': 'Lithuania', 'order': 129, 'enabled': True, 'meta': {'callingCode': '370'}},
        {'value': 'LU', 'label': 'Luxembourg', 'order': 130, 'enabled': True, 'meta': {'callingCode': '352'}},
        {'value': 'MO', 'label': 'Macao', 'order': 131, 'enabled': True, 'meta': {'callingCode': '853'}},
        {'value': 'MG', 'label': 'Madagascar', 'order': 132, 'enabled': True, 'meta': {'callingCode': '261'}},
        {'value': 'MW', 'label': 'Malawi', 'order': 133, 'enabled': True, 'meta': {'callingCode': '265'}},
        {'value': 'MY', 'label': 'Malaysia', 'order': 134, 'enabled': True, 'meta': {'callingCode': '60'}},
        {'value': 'MV', 'label': 'Maldives', 'order': 135, 'enabled': True, 'meta': {'callingCode': '960'}},
        {'value': 'ML', 'label': 'Mali', 'order': 136, 'enabled': True, 'meta': {'callingCode': '223'}},
        {'value': 'MT', 'label': 'Malta', 'order': 137, 'enabled': True, 'meta': {'callingCode': '356'}},
        {'value': 'MH', 'label': 'Marshall Islands', 'order': 138, 'enabled': True, 'meta': {'callingCode': '692'}},
        {'value': 'MQ', 'label': 'Martinique', 'order': 139, 'enabled': True, 'meta': {'callingCode': '596'}},
        {'value': 'MR', 'label': 'Mauritania', 'order': 140, 'enabled': True, 'meta': {'callingCode': '222'}},
        {'value': 'MU', 'label': 'Mauritius', 'order': 141, 'enabled': True, 'meta': {'callingCode': '230'}},
        {'value': 'YT', 'label': 'Mayotte', 'order': 142, 'enabled': True, 'meta': {'callingCode': '262'}},
        {'value': 'MX', 'label': 'Mexico', 'order': 143, 'enabled': True, 'meta': {'callingCode': '52'}},
        {'value': 'FM', 'label': 'Micronesia, Federated States of', 'order': 144, 'enabled': True, 'meta': {'callingCode': '691'}},
        {'value': 'MD', 'label': 'Moldova, Republic of', 'order': 145, 'enabled': True, 'meta': {'callingCode': '373'}},
        {'value': 'MC', 'label': 'Monaco', 'order': 146, 'enabled': True, 'meta': {'callingCode': '377'}},
        {'value': 'MN', 'label': 'Mongolia', 'order': 147, 'enabled': True, 'meta': {'callingCode': '976'}},
        {'value': 'ME', 'label': 'Montenegro', 'order': 148, 'enabled': True, 'meta': {'callingCode': '382'}},
        {'value': 'MS', 'label': 'Montserrat', 'order': 149, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'MA', 'label': 'Morocco', 'order': 150, 'enabled': True, 'meta': {'callingCode': '212'}},
        {'value': 'MZ', 'label': 'Mozambique', 'order': 151, 'enabled': True, 'meta': {'callingCode': '258'}},
        {'value': 'MM', 'label': 'Myanmar', 'order': 152, 'enabled': True, 'meta': {'callingCode': '95'}},
        {'value': 'NA', 'label': 'Namibia', 'order': 153, 'enabled': True, 'meta': {'callingCode': '264'}},
        {'value': 'NR', 'label': 'Nauru', 'order': 154, 'enabled': True, 'meta': {'callingCode': '674'}},
        {'value': 'NP', 'label': 'Nepal', 'order': 155, 'enabled': True, 'meta': {'callingCode': '977'}},
        {'value': 'NL', 'label': 'Netherlands', 'order': 156, 'enabled': True, 'meta': {'callingCode': '31'}},
        {'value': 'NC', 'label': 'New Caledonia', 'order': 157, 'enabled': True, 'meta': {'callingCode': '687'}},
        {'value': 'NZ', 'label': 'New Zealand', 'order': 158, 'enabled': True, 'meta': {'callingCode': '64'}},
        {'value': 'NI', 'label': 'Nicaragua', 'order': 159, 'enabled': True, 'meta': {'callingCode': '505'}},
        {'value': 'NE', 'label': 'Niger', 'order': 160, 'enabled': True, 'meta': {'callingCode': '227'}},
        {'value': 'NG', 'label': 'Nigeria', 'order': 161, 'enabled': True, 'meta': {'callingCode': '234'}},
        {'value': 'NU', 'label': 'Niue', 'order': 162, 'enabled': True, 'meta': {'callingCode': '683'}},
        {'value': 'NF', 'label': 'Norfolk Island', 'order': 163, 'enabled': True, 'meta': {'callingCode': '672'}},
        {'value': 'MK', 'label': 'North Macedonia', 'order': 164, 'enabled': True, 'meta': {'callingCode': '389'}},
        {'value': 'MP', 'label': 'Northern Mariana Islands', 'order': 165, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'NO', 'label': 'Norway', 'order': 166, 'enabled': True, 'meta': {'callingCode': '47'}},
        {'value': 'OM', 'label': 'Oman', 'order': 167, 'enabled': True, 'meta': {'callingCode': '968'}},
        {'value': 'PK', 'label': 'Pakistan', 'order': 168, 'enabled': True, 'meta': {'callingCode': '92'}},
        {'value': 'PW', 'label': 'Palau', 'order': 169, 'enabled': True, 'meta': {'callingCode': '680'}},
        {'value': 'PS', 'label': 'Palestine, State of', 'order': 170, 'enabled': True, 'meta': {'callingCode': '970'}},
        {'value': 'PA', 'label': 'Panama', 'order': 171, 'enabled': True, 'meta': {'callingCode': '507'}},
        {'value': 'PG', 'label': 'Papua New Guinea', 'order': 172, 'enabled': True, 'meta': {'callingCode': '675'}},
        {'value': 'PY', 'label': 'Paraguay', 'order': 173, 'enabled': True, 'meta': {'callingCode': '595'}},
        {'value': 'PE', 'label': 'Peru', 'order': 174, 'enabled': True, 'meta': {'callingCode': '51'}},
        {'value': 'PH', 'label': 'Philippines', 'order': 175, 'enabled': True, 'meta': {'callingCode': '63'}},
        {'value': 'PN', 'label': 'Pitcairn', 'order': 176, 'enabled': True, 'meta': {'callingCode': ''}},
        {'value': 'PL', 'label': 'Poland', 'order': 177, 'enabled': True, 'meta': {'callingCode': '48'}},
        {'value': 'PT', 'label': 'Portugal', 'order': 178, 'enabled': True, 'meta': {'callingCode': '351'}},
        {'value': 'PR', 'label': 'Puerto Rico', 'order': 179, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'QA', 'label': 'Qatar', 'order': 180, 'enabled': True, 'meta': {'callingCode': '974'}},
        {'value': 'RO', 'label': 'Romania', 'order': 181, 'enabled': True, 'meta': {'callingCode': '40'}},
        {'value': 'RU', 'label': 'Russian Federation', 'order': 182, 'enabled': True, 'meta': {'callingCode': '7'}},
        {'value': 'RW', 'label': 'Rwanda', 'order': 183, 'enabled': True, 'meta': {'callingCode': '250'}},
        {'value': 'RE', 'label': 'Réunion', 'order': 184, 'enabled': True, 'meta': {'callingCode': '262'}},
        {'value': 'BL', 'label': 'Saint Barthélemy', 'order': 185, 'enabled': True, 'meta': {'callingCode': '590'}},
        {'value': 'SH', 'label': 'Saint Helena, Ascension and Tristan da Cunha', 'order': 186, 'enabled': True, 'meta': {'callingCode': '290'}},
        {'value': 'KN', 'label': 'Saint Kitts and Nevis', 'order': 187, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'LC', 'label': 'Saint Lucia', 'order': 188, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'MF', 'label': 'Saint Martin (French part)', 'order': 189, 'enabled': True, 'meta': {'callingCode': '590'}},
        {'value': 'PM', 'label': 'Saint Pierre and Miquelon', 'order': 190, 'enabled': True, 'meta': {'callingCode': '508'}},
        {'value': 'VC', 'label': 'Saint Vincent and the Grenadines', 'order': 191, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'WS', 'label': 'Samoa', 'order': 192, 'enabled': True, 'meta': {'callingCode': '685'}},
        {'value': 'SM', 'label': 'San Marino', 'order': 193, 'enabled': True, 'meta': {'callingCode': '378'}},
        {'value': 'ST', 'label': 'Sao Tome and Principe', 'order': 194, 'enabled': True, 'meta': {'callingCode': '239'}},
        {'value': 'SA', 'label': 'Saudi Arabia', 'order': 195, 'enabled': True, 'meta': {'callingCode': '966'}},
        {'value': 'SN', 'label': 'Senegal', 'order': 196, 'enabled': True, 'meta': {'callingCode': '221'}},
        {'value': 'RS', 'label': 'Serbia', 'order': 197, 'enabled': True, 'meta': {'callingCode': '381'}},
        {'value': 'SC', 'label': 'Seychelles', 'order': 198, 'enabled': True, 'meta': {'callingCode': '248'}},
        {'value': 'SL', 'label': 'Sierra Leone', 'order': 199, 'enabled': True, 'meta': {'callingCode': '232'}},
        {'value': 'SG', 'label': 'Singapore', 'order': 200, 'enabled': True, 'meta': {'callingCode': '65'}},
        {'value': 'SX', 'label': 'Sint Maarten (Dutch part)', 'order': 201, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'SK', 'label': 'Slovakia', 'order': 202, 'enabled': True, 'meta': {'callingCode': '421'}},
        {'value': 'SI', 'label': 'Slovenia', 'order': 203, 'enabled': True, 'meta': {'callingCode': '386'}},
        {'value': 'SB', 'label': 'Solomon Islands', 'order': 204, 'enabled': True, 'meta': {'callingCode': '677'}},
        {'value': 'SO', 'label': 'Somalia', 'order': 205, 'enabled': True, 'meta': {'callingCode': '252'}},
        {'value': 'ZA', 'label': 'South Africa', 'order': 206, 'enabled': True, 'meta': {'callingCode': '27'}},
        {'value': 'GS', 'label': 'South Georgia and the South Sandwich Islands', 'order': 207, 'enabled': True, 'meta': {'callingCode': ''}},
        {'value': 'SS', 'label': 'South Sudan', 'order': 208, 'enabled': True, 'meta': {'callingCode': '211'}},
        {'value': 'ES', 'label': 'Spain', 'order': 209, 'enabled': True, 'meta': {'callingCode': '34'}},
        {'value': 'LK', 'label': 'Sri Lanka', 'order': 210, 'enabled': True, 'meta': {'callingCode': '94'}},
        {'value': 'SD', 'label': 'Sudan', 'order': 211, 'enabled': True, 'meta': {'callingCode': '249'}},
        {'value': 'SR', 'label': 'Suriname', 'order': 212, 'enabled': True, 'meta': {'callingCode': '597'}},
        {'value': 'SJ', 'label': 'Svalbard and Jan Mayen', 'order': 213, 'enabled': True, 'meta': {'callingCode': '47'}},
        {'value': 'SE', 'label': 'Sweden', 'order': 214, 'enabled': True, 'meta': {'callingCode': '46'}},
        {'value': 'CH', 'label': 'Switzerland', 'order': 215, 'enabled': True, 'meta': {'callingCode': '41'}},
        {'value': 'SY', 'label': 'Syrian Arab Republic', 'order': 216, 'enabled': True, 'meta': {'callingCode': '963'}},
        {'value': 'TW', 'label': 'Taiwan, Province of China', 'order': 217, 'enabled': True, 'meta': {'callingCode': '886'}},
        {'value': 'TJ', 'label': 'Tajikistan', 'order': 218, 'enabled': True, 'meta': {'callingCode': '992'}},
        {'value': 'TZ', 'label': 'Tanzania, United Republic of', 'order': 219, 'enabled': True, 'meta': {'callingCode': '255'}},
        {'value': 'TH', 'label': 'Thailand', 'order': 220, 'enabled': True, 'meta': {'callingCode': '66'}},
        {'value': 'TL', 'label': 'Timor-Leste', 'order': 221, 'enabled': True, 'meta': {'callingCode': '670'}},
        {'value': 'TG', 'label': 'Togo', 'order': 222, 'enabled': True, 'meta': {'callingCode': '228'}},
        {'value': 'TK', 'label': 'Tokelau', 'order': 223, 'enabled': True, 'meta': {'callingCode': '690'}},
        {'value': 'TO', 'label': 'Tonga', 'order': 224, 'enabled': True, 'meta': {'callingCode': '676'}},
        {'value': 'TT', 'label': 'Trinidad and Tobago', 'order': 225, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'TN', 'label': 'Tunisia', 'order': 226, 'enabled': True, 'meta': {'callingCode': '216'}},
        {'value': 'TM', 'label': 'Turkmenistan', 'order': 227, 'enabled': True, 'meta': {'callingCode': '993'}},
        {'value': 'TC', 'label': 'Turks and Caicos Islands', 'order': 228, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'TV', 'label': 'Tuvalu', 'order': 229, 'enabled': True, 'meta': {'callingCode': '688'}},
        {'value': 'TR', 'label': 'Türkiye', 'order': 230, 'enabled': True, 'meta': {'callingCode': '90'}},
        {'value': 'UG', 'label': 'Uganda', 'order': 231, 'enabled': True, 'meta': {'callingCode': '256'}},
        {'value': 'UA', 'label': 'Ukraine', 'order': 232, 'enabled': True, 'meta': {'callingCode': '380'}},
        {'value': 'AE', 'label': 'United Arab Emirates', 'order': 233, 'enabled': True, 'meta': {'callingCode': '971'}},
        {'value': 'GB', 'label': 'United Kingdom', 'order': 234, 'enabled': True, 'meta': {'callingCode': '44'}},
        {'value': 'US', 'label': 'United States', 'order': 235, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'UM', 'label': 'United States Minor Outlying Islands', 'order': 236, 'enabled': True, 'meta': {'callingCode': ''}},
        {'value': 'UY', 'label': 'Uruguay', 'order': 237, 'enabled': True, 'meta': {'callingCode': '598'}},
        {'value': 'UZ', 'label': 'Uzbekistan', 'order': 238, 'enabled': True, 'meta': {'callingCode': '998'}},
        {'value': 'VU', 'label': 'Vanuatu', 'order': 239, 'enabled': True, 'meta': {'callingCode': '678'}},
        {'value': 'VE', 'label': 'Venezuela, Bolivarian Republic of', 'order': 240, 'enabled': True, 'meta': {'callingCode': '58'}},
        {'value': 'VN', 'label': 'Viet Nam', 'order': 241, 'enabled': True, 'meta': {'callingCode': '84'}},
        {'value': 'VG', 'label': 'Virgin Islands, British', 'order': 242, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'VI', 'label': 'Virgin Islands, U.S.', 'order': 243, 'enabled': True, 'meta': {'callingCode': '1'}},
        {'value': 'WF', 'label': 'Wallis and Futuna', 'order': 244, 'enabled': True, 'meta': {'callingCode': '681'}},
        {'value': 'EH', 'label': 'Western Sahara', 'order': 245, 'enabled': True, 'meta': {'callingCode': '212'}},
        {'value': 'YE', 'label': 'Yemen', 'order': 246, 'enabled': True, 'meta': {'callingCode': '967'}},
        {'value': 'ZM', 'label': 'Zambia', 'order': 247, 'enabled': True, 'meta': {'callingCode': '260'}},
        {'value': 'ZW', 'label': 'Zimbabwe', 'order': 248, 'enabled': True, 'meta': {'callingCode': '263'}},
        {'value': 'AX', 'label': 'Åland Islands', 'order': 249, 'enabled': True, 'meta': {'callingCode': '358'}},
    ]
    state_items = [
        {'value': 'AN', 'label': 'Andaman and Nicobar Islands', 'order': 1, 'enabled': True, 'parent': 'IN'},
        {'value': 'AP', 'label': 'Andhra Pradesh', 'order': 2, 'enabled': True, 'parent': 'IN'},
        {'value': 'AR', 'label': 'Arunachal Pradesh', 'order': 3, 'enabled': True, 'parent': 'IN'},
        {'value': 'AS', 'label': 'Assam', 'order': 4, 'enabled': True, 'parent': 'IN'},
        {'value': 'BR', 'label': 'Bihar', 'order': 5, 'enabled': True, 'parent': 'IN'},
        {'value': 'CG', 'label': 'Chhattisgarh', 'order': 6, 'enabled': True, 'parent': 'IN'},
        {'value': 'CH', 'label': 'Chandigarh', 'order': 7, 'enabled': True, 'parent': 'IN'},
        {'value': 'DH', 'label': 'Dadra and Nagar Haveli and Daman and Diu', 'order': 8, 'enabled': True, 'parent': 'IN'},
        {'value': 'DL', 'label': 'Delhi', 'order': 9, 'enabled': True, 'parent': 'IN'},
        {'value': 'GA', 'label': 'Goa', 'order': 10, 'enabled': True, 'parent': 'IN'},
        {'value': 'GJ', 'label': 'Gujarat', 'order': 11, 'enabled': True, 'parent': 'IN'},
        {'value': 'HR', 'label': 'Haryana', 'order': 12, 'enabled': True, 'parent': 'IN'},
        {'value': 'HP', 'label': 'Himachal Pradesh', 'order': 13, 'enabled': True, 'parent': 'IN'},
        {'value': 'JK', 'label': 'Jammu and Kashmir', 'order': 14, 'enabled': True, 'parent': 'IN'},
        {'value': 'JH', 'label': 'Jharkhand', 'order': 15, 'enabled': True, 'parent': 'IN'},
        {'value': 'KA', 'label': 'Karnataka', 'order': 16, 'enabled': True, 'parent': 'IN'},
        {'value': 'KL', 'label': 'Kerala', 'order': 17, 'enabled': True, 'parent': 'IN'},
        {'value': 'LA', 'label': 'Ladakh', 'order': 18, 'enabled': True, 'parent': 'IN'},
        {'value': 'LD', 'label': 'Lakshadweep', 'order': 19, 'enabled': True, 'parent': 'IN'},
        {'value': 'MP', 'label': 'Madhya Pradesh', 'order': 20, 'enabled': True, 'parent': 'IN'},
        {'value': 'MH', 'label': 'Maharashtra', 'order': 21, 'enabled': True, 'parent': 'IN'},
        {'value': 'MN', 'label': 'Manipur', 'order': 22, 'enabled': True, 'parent': 'IN'},
        {'value': 'ML', 'label': 'Meghalaya', 'order': 23, 'enabled': True, 'parent': 'IN'},
        {'value': 'MZ', 'label': 'Mizoram', 'order': 24, 'enabled': True, 'parent': 'IN'},
        {'value': 'NL', 'label': 'Nagaland', 'order': 25, 'enabled': True, 'parent': 'IN'},
        {'value': 'OR', 'label': 'Odisha', 'order': 26, 'enabled': True, 'parent': 'IN'},
        {'value': 'PY', 'label': 'Puducherry', 'order': 27, 'enabled': True, 'parent': 'IN'},
        {'value': 'PB', 'label': 'Punjab', 'order': 28, 'enabled': True, 'parent': 'IN'},
        {'value': 'RJ', 'label': 'Rajasthan', 'order': 29, 'enabled': True, 'parent': 'IN'},
        {'value': 'SK', 'label': 'Sikkim', 'order': 30, 'enabled': True, 'parent': 'IN'},
        {'value': 'TN', 'label': 'Tamil Nadu', 'order': 31, 'enabled': True, 'parent': 'IN'},
        {'value': 'TS', 'label': 'Telangana', 'order': 32, 'enabled': True, 'parent': 'IN'},
        {'value': 'TR', 'label': 'Tripura', 'order': 33, 'enabled': True, 'parent': 'IN'},
        {'value': 'UP', 'label': 'Uttar Pradesh', 'order': 34, 'enabled': True, 'parent': 'IN'},
        {'value': 'UK', 'label': 'Uttarakhand', 'order': 35, 'enabled': True, 'parent': 'IN'},
        {'value': 'WB', 'label': 'West Bengal', 'order': 36, 'enabled': True, 'parent': 'IN'},
    ]

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
    parser.add_argument('--force-profile-config', action='store_true', help='Overwrite only RIDER_PROFILE_SECTION, RIDER_PROFILE_ATTRIBUTE, and LOV entries')
    return parser.parse_args()


def main():
    args = parse_args()
    dynamodb = boto3.resource('dynamodb', region_name=args.region)
    table = dynamodb.Table(args.table_name)

    items = build_seed_items(args.updated_by)

    for item in items:
        try:
            should_force_profile_config = args.force_profile_config and item['configType'] in FORCE_OVERWRITE_PROFILE_CONFIG_TYPES
            if item['configType'] in INSERT_ONLY_CONFIG_TYPES and not should_force_profile_config:
                table.put_item(Item=item, ConditionExpression='attribute_not_exists(configType) AND attribute_not_exists(configId)')
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
