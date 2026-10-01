import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'layers', 'common'))

from self_service_policy import (
    activity_self_service_allowed,
    build_ride_self_service,
    not_riding_allowed,
    quit_riding_allowed,
    stage_check_in_allowed,
)


def test_stage_permission_precedence_and_type_defaults():
    defaults = {'START': True, 'PIT_STOP': False, 'FINISH': True}
    for stage_type, expected in defaults.items():
        stage = {'type': stage_type}
        assert stage_check_in_allowed({}, stage) is expected
        assert stage_check_in_allowed({'selfCheckInAllowed': not expected}, stage) is not expected
        assert stage_check_in_allowed(
            {'selfCheckInAllowed': not expected},
            {**stage, 'selfCheckInAllowed': expected},
        ) is expected

        for ride_value in (False, True):
            assert stage_check_in_allowed({'selfCheckInAllowed': ride_value}, stage) is ride_value


def test_not_riding_permission_uses_only_start_stage_setting():
    assert not_riding_allowed({'stages': [{'type': 'START'}]}) is False
    assert not_riding_allowed({'stages': [{'type': 'START', 'selfNotRidingAllowed': True}]}) is True
    assert not_riding_allowed({
        'stages': [
            {'type': 'START', 'selfNotRidingAllowed': False},
            {'type': 'PIT_STOP', 'selfNotRidingAllowed': True},
        ],
    }) is False


def test_quit_riding_permission_ride_value_overrides_tour_value():
    assert quit_riding_allowed({}, None) is False
    assert quit_riding_allowed({}, {'selfQuitRidingAllowed': True}) is True
    assert quit_riding_allowed(
        {'selfQuitRidingAllowed': False}, {'selfQuitRidingAllowed': True}
    ) is False
    assert quit_riding_allowed(
        {'selfQuitRidingAllowed': True}, {'selfQuitRidingAllowed': False}
    ) is True


def test_event_permission_precedence_from_override_to_event():
    event = {'selfServiceAllowed': False}
    activity = {'selfServiceAllowed': True}
    occurrence = {'selfServiceAllowed': False}

    assert activity_self_service_allowed(event, {}, {}, None) is False
    assert activity_self_service_allowed(event, activity, {}, None) is True
    assert activity_self_service_allowed(event, activity, occurrence, None) is False
    assert activity_self_service_allowed(
        event, activity, occurrence, {'selfServiceAllowed': True}
    ) is True
    assert activity_self_service_allowed(
        {'selfServiceAllowed': True}, {}, {}, {'selfServiceAllowed': False}
    ) is False
    assert activity_self_service_allowed({}, {}, {}, {}) is False


def test_ride_response_contains_only_calculated_policy_fields():
    result = build_ride_self_service(
        {
            'selfQuitRidingAllowed': False,
            'selfCheckInAllowed': True,
            'stages': [
                {'stageNumber': 2, 'stageId': 'S002', 'type': 'FINISH'},
                {'stageNumber': 0, 'stageId': 'S000', 'type': 'START', 'selfNotRidingAllowed': True},
                {'stageNumber': 1, 'stageId': 'S001', 'type': 'PIT_STOP', 'selfCheckInAllowed': False},
            ],
        },
        {'selfQuitRidingAllowed': True},
    )

    assert set(result) == {'quitRidingAllowed', 'notRidingAllowed', 'stages'}
    assert result == {
        'quitRidingAllowed': False,
        'notRidingAllowed': True,
        'stages': [
            {'stageNumber': 0, 'stageId': 'S000', 'stageType': 'START', 'checkInAllowed': True},
            {'stageNumber': 1, 'stageId': 'S001', 'stageType': 'PIT_STOP', 'checkInAllowed': False},
            {'stageNumber': 2, 'stageId': 'S002', 'stageType': 'FINISH', 'checkInAllowed': True},
        ],
    }


def test_legacy_ride_without_policy_fields_uses_type_defaults():
    result = build_ride_self_service({
        'stages': [
            {'stageNumber': 0, 'stageId': 'S000', 'type': 'START'},
            {'stageNumber': 1, 'stageId': 'S001', 'type': 'PIT_STOP'},
            {'stageNumber': 2, 'stageId': 'S002', 'type': 'FINISH'},
        ],
    }, None)

    assert result['quitRidingAllowed'] is False
    assert result['notRidingAllowed'] is False
    assert [stage['checkInAllowed'] for stage in result['stages']] == [True, False, True]