"""Focused tests for simulation scenario contracts and helper utilities."""

from pathlib import Path
import importlib.util

import pytest
import yaml


SIMULATE_DIR = Path(__file__).resolve().parent
MODULE_PATH = SIMULATE_DIR / 'generate_data.py'
SCENARIO_DIR = SIMULATE_DIR / 'scenarios'


def _load_module():
    spec = importlib.util.spec_from_file_location('generate_data', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_yaml(path):
    with open(path) as handle:
        return yaml.safe_load(handle)


generate_data = _load_module()


def test_tot_2026_uses_explicit_tour_data_scenario_type():
    config = _load_yaml(SCENARIO_DIR / 'tot_2026.yaml')

    assert generate_data.get_scenario_type(config) == generate_data.SCENARIO_TYPE_TOUR_DATA
    assert generate_data.get_scenario_mode(config) == generate_data.SCENARIO_MODE_CREATE
    generate_data.validate_tour_data_scenario(config)


def test_personal_code_uses_standard_target_selection_payload_structure():
    config = _load_yaml(SCENARIO_DIR / 'personal_code.yaml')

    assert generate_data.get_scenario_type(config) == generate_data.SCENARIO_TYPE_PERSONAL_CODE
    assert generate_data.get_scenario_mode(config) == generate_data.SCENARIO_MODE_UPDATE
    assert generate_data.resolve_selection_limit(config['selection']['limit'], config) == len(
        config['payload']['personal_codes']
    )
    generate_data.validate_personal_code_scenario(config)


def test_selection_filter_requires_supported_filter_type():
    with pytest.raises(ValueError, match='selection.filter.type'):
        generate_data.resolve_selection_filter({'type': 'contains', 'attribute': 'personalCode'})


def test_build_table_name_supports_shared_and_tour_scoped_tables():
    assert generate_data.build_table_name('dev', 'RiderProfile') == 'dev-RiderProfile'
    assert generate_data.build_table_name('dev', 'CheckIn', tour_id='TOT-2026') == (
        'dev-CheckIn-TOT-2026'
    )


def test_event_simulation_emits_registration_and_self_service_fields():
    event = {
        'event_id': 'EVT-REG',
        'event_name': 'Registration',
        'event_type': 'SINGLE',
        'location': 'Venue',
        'sequence_enforced': True,
        'default_allowed_type_codes': ['1'],
        'registration_enabled': True,
        'self_service_allowed': True,
        'activities': [{
            'activity_id': 'ACT-001',
            'name': 'Register',
            'sequence_no': 0,
            'self_service_allowed': False,
        }],
    }

    item = generate_data.build_event_definition_item(event, 0)
    occurrence, _ = generate_data.build_occurrence_item(
        'EVT-REG',
        {'day_offset': 0, 'seq': 1, 'self_service_allowed': True},
        generate_data.date.today(),
        False,
    )

    assert item['registrationEnabled'] is True
    assert item['selfServiceAllowed'] is True
    assert item['activities'][0]['selfServiceAllowed'] is False
    assert occurrence['selfServiceAllowed'] is True
    assert 'allowSelfService' not in item
    assert 'selfServiceEnabled' not in occurrence


def test_ride_simulation_emits_tour_ride_and_stage_policy_fields():
    stage = generate_data._build_stage(
        {
            'type': 'START',
            'name': 'Start',
            'self_check_in_allowed': True,
            'self_not_riding_allowed': False,
        },
        0,
        '2026-02-10',
        '08:00',
        'PLANNED',
    )
    ride = generate_data._ride_to_dynamodb({
        'ride_id': 'RIDE001',
        'date': '2026-02-10',
        'ride_no': 1,
        'name': 'Ride',
        'start_location': 'A',
        'finish_location': 'B',
        'total_distance': 20,
        'flag_off_time': '08:00',
        'open_time': '07:30',
        'close_time': '10:00',
        'status': 'PLANNED',
        'stages': [stage],
        'created_at': '2026-02-01T00:00:00Z',
        'updated_at': '2026-02-01T00:00:00Z',
        'self_check_in_allowed': True,
        'self_quit_riding_allowed': False,
    })
    tour_config = _load_yaml(SCENARIO_DIR / 'tot_2026.yaml')['tour']

    assert tour_config['self_quit_riding_allowed'] is False
    assert ride['selfCheckInAllowed'] is True
    assert ride['selfQuitRidingAllowed'] is False
    assert ride['stages'][0]['selfCheckInAllowed'] is True
    assert ride['stages'][0]['selfNotRidingAllowed'] is False