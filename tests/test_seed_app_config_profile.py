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
