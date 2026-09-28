import os
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, 'src/layers/common')
os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')

import dynamodb_utils
from profile_schema import clear_schema_cache, merge_profile_values, filter_profile_for_response, ensure_definitions_version, ProfileSchemaError, get_definitions_version


@pytest.fixture
def aws_credentials():
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture
def app_config_fixture(aws_credentials):
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamodb.create_table(
            TableName='test-app-config-table',
            KeySchema=[
                {'AttributeName': 'configType', 'KeyType': 'HASH'},
                {'AttributeName': 'configId', 'KeyType': 'RANGE'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'configType', 'AttributeType': 'S'},
                {'AttributeName': 'configId', 'AttributeType': 'S'},
            ],
            BillingMode='PAY_PER_REQUEST',
        )

        rows = [
            {'configType': 'RIDER_PROFILE_SECTION', 'configId': 'personal', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Personal', 'order': 1}},
            {'configType': 'RIDER_PROFILE_SECTION', 'configId': 'medical', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Medical', 'order': 2}},
            {'configType': 'LOV', 'configId': 'GENDER', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Gender', 'items': [{'value': 'Male', 'label': 'Male', 'enabled': True, 'order': 1}] }},
            {'configType': 'LOV', 'configId': 'COUNTRY', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Country', 'items': [{'value': 'IN', 'label': 'India', 'enabled': True, 'order': 1}] }},
            {'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'name', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Name', 'sectionId': 'personal', 'order': 1, 'type': 'TEXT', 'storage': {'scope': 'CORE', 'path': 'name'}, 'required': True}},
            {'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'gender', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Gender', 'sectionId': 'personal', 'order': 2, 'type': 'SELECT', 'lovId': 'GENDER', 'storage': {'scope': 'CORE', 'path': 'gender'}, 'required': True}},
            {'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'country', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Country', 'sectionId': 'personal', 'order': 3, 'type': 'SELECT', 'lovId': 'COUNTRY', 'storage': {'scope': 'CORE', 'path': 'country'}, 'required': False}},
            {'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'photo', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Photo', 'sectionId': 'personal', 'order': 4, 'type': 'IMAGE', 'handler': 'PROFILE_PHOTO', 'storage': {'scope': 'CORE', 'path': 'photoS3Key'}, 'required': False}},
            {'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'bloodGroup', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Blood Group', 'sectionId': 'medical', 'order': 1, 'type': 'TEXT', 'storage': {'scope': 'ATTRIBUTES'}, 'visibleToAllMgmtUsers': False, 'sensitive': True}},
            {'configType': 'RIDER_PROFILE_ATTRIBUTE', 'configId': 'personalCode', 'enabled': True, 'version': 1, 'updatedAt': '2026-01-01T00:00:00Z', 'config': {'label': 'Code', 'sectionId': 'personal', 'order': 3, 'type': 'TEXT', 'storage': {'scope': 'CORE', 'path': 'personalCode'}, 'adminOnly': True}},
        ]
        for row in rows:
            table.put_item(Item=row)

        os.environ['APP_CONFIG_TABLE'] = 'test-app-config-table'

        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        clear_schema_cache()
        yield


def _event(groups):
    return {
        'requestContext': {
            'authorizer': {
                'jwt': {
                    'claims': {
                        'sub': 'user-1',
                        'cognito:groups': ','.join(groups),
                    }
                }
            }
        }
    }


def test_unknown_attribute_rejected(app_config_fixture):
    with pytest.raises(ProfileSchemaError) as exc:
        merge_profile_values({'profileId': 'P1'}, {'name': 'A', 'gender': 'Male', 'attributes': {'unknownKey': 'x'}}, event=_event(['RIDER']))
    assert exc.value.code == 'UNKNOWN_OR_DISABLED_ATTRIBUTE'


def test_unknown_top_level_key_rejected(app_config_fixture):
    with pytest.raises(ProfileSchemaError) as exc:
        merge_profile_values({'profileId': 'P1'}, {'name': 'A', 'gender': 'Male', 'unknownTopLevel': 'x'}, event=_event(['RIDER']))
    assert exc.value.code == 'UNKNOWN_OR_DISABLED_ATTRIBUTE'


def test_merge_keeps_unsent_attributes(app_config_fixture):
    existing = {'profileId': 'P1', 'name': 'Old', 'gender': 'Male', 'attributes': {'legacyRemoved': 'x', 'bloodGroup': 'A+'}}
    merged, _ = merge_profile_values(existing, {'name': 'New', 'gender': 'Male'}, event=_event(['RIDER']))
    assert merged['attributes']['legacyRemoved'] == 'x'
    assert merged['name'] == 'New'


def test_top_level_core_key_resolves_by_attribute_key(app_config_fixture):
    merged, _ = merge_profile_values({'profileId': 'P1', 'name': 'Old', 'gender': 'Male'}, {'name': 'New', 'gender': 'Male'}, event=_event(['RIDER']))
    assert merged['name'] == 'New'


def test_profile_photo_updates_with_storage_path_key(app_config_fixture):
    merged, _ = merge_profile_values(
        {'profileId': 'P1', 'name': 'Old', 'gender': 'Male'},
        {'name': 'New', 'gender': 'Male', 'photoS3Key': 'riders/P1/photo/profile.jpg'},
        event=_event(['RIDER']),
    )
    assert merged['photoS3Key'] == 'riders/P1/photo/profile.jpg'

    legacy, _ = merge_profile_values(
        {'profileId': 'P1', 'name': 'Old', 'gender': 'Male'},
        {'name': 'New', 'gender': 'Male', 'photoS3Key': 'profiles/P1/legacy-profile.jpg'},
        event=_event(['RIDER']),
    )
    assert legacy['photoS3Key'] == 'profiles/P1/legacy-profile.jpg'


def test_profile_photo_rejects_path_traversal(app_config_fixture):
    with pytest.raises(ProfileSchemaError) as exc:
        merge_profile_values(
            {'profileId': 'P1', 'name': 'Old', 'gender': 'Male'},
            {'name': 'Old', 'gender': 'Male', 'photoS3Key': 'riders/P1/photo/../../other/file.jpg'},
            event=_event(['RIDER']),
        )
    assert exc.value.code == 'VALIDATION_ERROR'


def test_optional_attribute_null_clears_value(app_config_fixture):
    merged, _ = merge_profile_values(
        {'profileId': 'P1', 'name': 'Old', 'gender': 'Male', 'attributes': {'bloodGroup': 'A+'}},
        {'name': 'Old', 'gender': 'Male', 'attributes': {'bloodGroup': None}},
        event=_event(['RIDER']),
    )
    assert 'bloodGroup' not in merged['attributes']


def test_select_accepts_label_and_normalizes_to_value(app_config_fixture):
    merged, _ = merge_profile_values(
        {'profileId': 'P1', 'name': 'Old', 'gender': 'Male'},
        {'name': 'Old', 'gender': 'Male', 'country': 'india'},
        event=_event(['RIDER']),
    )
    assert merged['country'] == 'IN'


def test_required_checked_on_merged_result(app_config_fixture):
    with pytest.raises(ProfileSchemaError) as exc:
        merge_profile_values({'profileId': 'P1', 'gender': 'Male'}, {'gender': 'Male'}, event=_event(['RIDER']))
    assert exc.value.code == 'VALIDATION_ERROR'


def test_admin_only_forbidden_to_rider(app_config_fixture):
    with pytest.raises(ProfileSchemaError) as exc:
        merge_profile_values({'profileId': 'P1', 'name': 'N', 'gender': 'Male'}, {'personalCode': 'abcd'}, event=_event(['RIDER']))
    assert exc.value.code == 'ADMIN_ONLY_ATTRIBUTE'


def test_definitions_version_conflict(app_config_fixture):
    with pytest.raises(ProfileSchemaError) as exc:
        ensure_definitions_version('stale')
    assert exc.value.code == 'PROFILE_DEFINITIONS_CHANGED'


def test_filtering_for_staff_roles(app_config_fixture):
    profile = {'profileId': 'P1', 'name': 'N', 'gender': 'Male', 'attributes': {'bloodGroup': 'A+', 'legacyRemoved': 'v'}}

    guest = filter_profile_for_response(profile, event=_event(['GUEST']), staff_mode=True)
    assert 'bloodGroup' not in guest['attributes']
    assert 'legacyRemoved' not in guest['attributes']

    admin = filter_profile_for_response(profile, event=_event(['ADMINISTRATOR']), staff_mode=True)
    assert admin['attributes']['bloodGroup'] == 'A+'
    assert 'bloodGroup' in admin.get('sensitiveKeys', [])
    assert admin['definitionsVersion'] == get_definitions_version()
