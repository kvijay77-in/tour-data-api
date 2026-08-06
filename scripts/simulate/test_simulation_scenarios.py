"""Focused tests for simulation scenario contracts and helper utilities."""

from pathlib import Path
import importlib.util

import pytest
import yaml


MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'simulate' / 'generate_data.py'
SCENARIO_DIR = Path(__file__).resolve().parents[1] / 'scripts' / 'simulate' / 'scenarios'


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