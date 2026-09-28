import sys

sys.path.insert(0, 'scripts')

import seed_app_config


def test_insert_only_types_include_profile_config_types():
    assert 'RIDER_PROFILE_SECTION' in seed_app_config.INSERT_ONLY_CONFIG_TYPES
    assert 'RIDER_PROFILE_ATTRIBUTE' in seed_app_config.INSERT_ONLY_CONFIG_TYPES
    assert 'LOV' in seed_app_config.INSERT_ONLY_CONFIG_TYPES


def test_seed_contains_profile_sections_lovs_and_attributes():
    items = seed_app_config.build_seed_items('test-user')
    by_type = {}
    for item in items:
        by_type.setdefault(item['configType'], set()).add(item['configId'])

    assert 'RIDER_PROFILE_SECTION' in by_type
    assert {'personal', 'contact', 'address', 'emergency', 'medical', 'preferences', 'organizer'}.issubset(by_type['RIDER_PROFILE_SECTION'])
    assert {'COUNTRY', 'STATE', 'GENDER', 'DIETARY_PREFERENCE', 'BLOOD_GROUP', 'RELATIONSHIP'}.issubset(by_type['LOV'])
    assert {'name', 'email', 'phone', 'photo', 'personalCode', 'dateOfBirth', 'gender', 'address', 'emergencyContact', 'dietaryPreference', 'bloodGroup', 'hasMedicalCondition', 'medicalConditions'}.issubset(by_type['RIDER_PROFILE_ATTRIBUTE'])


def test_country_lov_contains_full_iso_seed_with_india_first():
    items = seed_app_config.build_seed_items('test-user')
    country = next(item for item in items if item['configType'] == 'LOV' and item['configId'] == 'COUNTRY')
    country_items = country['config']['items']
    assert len(country_items) == 249
    assert country_items[0]['value'] == 'IN'
    assert country_items[0]['meta']['callingCode'] == '91'


def test_state_lov_uses_full_names_with_codes():
    items = seed_app_config.build_seed_items('test-user')
    state = next(item for item in items if item['configType'] == 'LOV' and item['configId'] == 'STATE')
    state_items = state['config']['items']
    tamil_nadu = next(item for item in state_items if item['value'] == 'TN')
    assert tamil_nadu['label'] == 'Tamil Nadu'


def test_emergency_contact_relation_seeded_as_text_field():
    items = seed_app_config.build_seed_items('test-user')
    emergency = next(item for item in items if item['configType'] == 'RIDER_PROFILE_ATTRIBUTE' and item['configId'] == 'emergencyContact')
    relation_field = next(field for field in emergency['config']['fields'] if field['key'] == 'relation')
    assert relation_field['type'] == 'TEXT'
