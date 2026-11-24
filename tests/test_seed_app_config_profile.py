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


def test_all_seed_item_types_are_insert_only():
    items = seed_app_config.build_seed_items('test-user')
    seed_types = {item['configType'] for item in items}
    assert seed_types.issubset(seed_app_config.INSERT_ONLY_CONFIG_TYPES)


def test_main_seeds_items_without_overwriting_existing(monkeypatch):
    import boto3
    from moto import mock_aws

    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
        table = dynamodb.create_table(
            TableName='test-AppConfig',
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

        # Pre-populate custom config items across platform and profile types
        table.put_item(
            Item={
                'configType': 'ID_CODE_FORMAT',
                'configId': 'SUBSTRING',
                'customField': 'custom_substring_value',
                'version': 99,
            }
        )
        table.put_item(
            Item={
                'configType': 'HOTEL_CSV_FILE',
                'configId': 'MAX-SIZE',
                'customField': 'custom_max_size',
                'version': 99,
            }
        )
        table.put_item(
            Item={
                'configType': 'LOV',
                'configId': 'GENDER',
                'customField': 'custom_gender_lov',
                'version': 99,
            }
        )

        monkeypatch.setattr(
            sys,
            'argv',
            ['seed_app_config.py', '--table-name', 'test-AppConfig', '--region', 'ap-south-1'],
        )
        seed_app_config.main()

        # Existing items must NOT be overwritten
        item1 = table.get_item(Key={'configType': 'ID_CODE_FORMAT', 'configId': 'SUBSTRING'})['Item']
        assert item1.get('customField') == 'custom_substring_value'
        assert item1.get('version') == 99

        item2 = table.get_item(Key={'configType': 'HOTEL_CSV_FILE', 'configId': 'MAX-SIZE'})['Item']
        assert item2.get('customField') == 'custom_max_size'
        assert item2.get('version') == 99

        item3 = table.get_item(Key={'configType': 'LOV', 'configId': 'GENDER'})['Item']
        assert item3.get('customField') == 'custom_gender_lov'
        assert item3.get('version') == 99

        # Items that did not exist should be inserted
        item4 = table.get_item(Key={'configType': 'ARTIFACTS', 'configId': 'ride-plan'})['Item']
        assert item4['configType'] == 'ARTIFACTS'
        assert item4['configId'] == 'ride-plan'

        # Running again must not fail or overwrite anything
        seed_app_config.main()
        item1_after = table.get_item(Key={'configType': 'ID_CODE_FORMAT', 'configId': 'SUBSTRING'})['Item']
        assert item1_after.get('customField') == 'custom_substring_value'


def test_main_force_profile_config_overwrites_only_profile_types(monkeypatch):
    import boto3
    from moto import mock_aws

    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
        table = dynamodb.create_table(
            TableName='test-AppConfig',
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

        # Pre-populate custom config items
        table.put_item(
            Item={
                'configType': 'ID_CODE_FORMAT',
                'configId': 'SUBSTRING',
                'customField': 'keep_this',
                'version': 99,
            }
        )
        table.put_item(
            Item={
                'configType': 'LOV',
                'configId': 'GENDER',
                'customField': 'overwrite_this',
                'version': 99,
            }
        )

        monkeypatch.setattr(
            sys,
            'argv',
            ['seed_app_config.py', '--table-name', 'test-AppConfig', '--region', 'ap-south-1', '--force-profile-config'],
        )
        seed_app_config.main()

        # Non-profile item is still not overwritten
        id_code_item = table.get_item(Key={'configType': 'ID_CODE_FORMAT', 'configId': 'SUBSTRING'})['Item']
        assert id_code_item.get('customField') == 'keep_this'

        # Profile item is overwritten when force-profile-config is passed
        gender_item = table.get_item(Key={'configType': 'LOV', 'configId': 'GENDER'})['Item']
        assert 'customField' not in gender_item
        assert gender_item['version'] == 1


# ---- --config-type / --config-id / --dry-run ----

BASE_ARGV = ['seed_app_config.py', '--table-name', 'test-AppConfig', '--region', 'ap-south-1']


def _create_table():
    import boto3

    return boto3.resource('dynamodb', region_name='ap-south-1').create_table(
        TableName='test-AppConfig',
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


def _keys(table):
    return {(i['configType'], i['configId']) for i in table.scan()['Items']}


def test_config_id_without_config_type_is_error(monkeypatch):
    import pytest

    monkeypatch.setattr(sys, 'argv', BASE_ARGV + ['--config-id', 'GENDER'])
    with pytest.raises(SystemExit) as exc:
        seed_app_config.parse_args()
    assert exc.value.code != 0


def test_config_id_list_rejects_empty_entries_and_spaces(monkeypatch):
    import pytest

    for bad in ('a,,b', 'a,b,', 'a, b'):
        monkeypatch.setattr(
            sys, 'argv', BASE_ARGV + ['--config-type', 'LOV', '--config-id', bad]
        )
        with pytest.raises(SystemExit):
            seed_app_config.parse_args()


def test_config_id_list_is_deduplicated(monkeypatch):
    monkeypatch.setattr(
        sys, 'argv', BASE_ARGV + ['--config-type', 'LOV', '--config-id', 'A,B,A']
    )
    assert seed_app_config.parse_args().config_ids == ['A', 'B']


def test_select_items_unknown_type_or_id_raises():
    import pytest

    items = seed_app_config.build_seed_items('t')
    with pytest.raises(ValueError, match='Unknown --config-type'):
        seed_app_config.select_items(items, 'lov')  # case-sensitive
    with pytest.raises(ValueError, match='NOPE'):
        seed_app_config.select_items(items, 'LOV', ['GENDER', 'NOPE'])


def test_main_config_type_and_ids_seed_only_selection(monkeypatch):
    from moto import mock_aws

    with mock_aws():
        table = _create_table()

        monkeypatch.setattr(sys, 'argv', BASE_ARGV + ['--config-type', 'LOV', '--config-id', 'GENDER,BLOOD_GROUP'])
        seed_app_config.main()
        assert _keys(table) == {('LOV', 'GENDER'), ('LOV', 'BLOOD_GROUP')}

        monkeypatch.setattr(sys, 'argv', BASE_ARGV + ['--config-type', 'HOTEL_UPLOAD'])
        seed_app_config.main()
        assert ('HOTEL_UPLOAD', 'PROCESSING') in _keys(table)


def test_main_unmatched_id_stops_before_any_write(monkeypatch):
    import pytest
    from moto import mock_aws

    with mock_aws():
        table = _create_table()
        monkeypatch.setattr(sys, 'argv', BASE_ARGV + ['--config-type', 'LOV', '--config-id', 'GENDER,NOPE'])
        with pytest.raises(SystemExit) as exc:
            seed_app_config.main()
        assert exc.value.code != 0
        assert _keys(table) == set()


def test_main_filtered_run_is_insert_only_without_force(monkeypatch):
    from moto import mock_aws

    with mock_aws():
        table = _create_table()
        table.put_item(Item={'configType': 'LOV', 'configId': 'GENDER', 'customField': 'keep', 'version': 99})

        monkeypatch.setattr(sys, 'argv', BASE_ARGV + ['--config-type', 'LOV', '--config-id', 'GENDER'])
        seed_app_config.main()
        assert table.get_item(Key={'configType': 'LOV', 'configId': 'GENDER'})['Item']['customField'] == 'keep'


def test_main_force_with_filter_overwrites_only_selected(monkeypatch):
    from moto import mock_aws

    with mock_aws():
        table = _create_table()
        for cid in ('GENDER', 'BLOOD_GROUP'):
            table.put_item(Item={'configType': 'LOV', 'configId': cid, 'customField': 'old', 'version': 99})

        monkeypatch.setattr(
            sys, 'argv',
            BASE_ARGV + ['--config-type', 'LOV', '--config-id', 'GENDER', '--force-profile-config'],
        )
        seed_app_config.main()
        assert 'customField' not in table.get_item(Key={'configType': 'LOV', 'configId': 'GENDER'})['Item']
        assert table.get_item(Key={'configType': 'LOV', 'configId': 'BLOOD_GROUP'})['Item']['customField'] == 'old'


def test_main_force_with_non_overwritable_type_is_error(monkeypatch):
    import pytest
    from moto import mock_aws

    with mock_aws():
        table = _create_table()
        monkeypatch.setattr(
            sys, 'argv', BASE_ARGV + ['--config-type', 'ARTIFACTS', '--force-profile-config']
        )
        with pytest.raises(SystemExit) as exc:
            seed_app_config.main()
        assert exc.value.code != 0
        assert _keys(table) == set()


def test_main_dry_run_writes_nothing_and_reports(monkeypatch, capsys):
    from moto import mock_aws

    with mock_aws():
        table = _create_table()
        table.put_item(Item={'configType': 'LOV', 'configId': 'GENDER', 'customField': 'old', 'version': 99})
        table.put_item(Item={'configType': 'LOV', 'configId': 'COUNTRY', 'customField': 'old', 'version': 99})

        # Without force: existing item is reported as kept, missing as inserted
        monkeypatch.setattr(sys, 'argv', BASE_ARGV + ['--config-type', 'LOV', '--config-id', 'GENDER,BLOOD_GROUP', '--dry-run'])
        seed_app_config.main()
        out = capsys.readouterr().out
        assert '[DRY RUN] Would keep existing LOV / GENDER' in out
        assert '[DRY RUN] Would insert LOV / BLOOD_GROUP' in out

        # With force: existing item is reported as overwritten
        monkeypatch.setattr(sys, 'argv', BASE_ARGV + ['--config-type', 'LOV', '--config-id', 'GENDER', '--force-profile-config', '--dry-run'])
        seed_app_config.main()
        assert '[DRY RUN] Would overwrite LOV / GENDER' in capsys.readouterr().out

        # Nothing was written or changed
        assert _keys(table) == {('LOV', 'GENDER'), ('LOV', 'COUNTRY')}
        assert table.get_item(Key={'configType': 'LOV', 'configId': 'GENDER'})['Item']['customField'] == 'old'
