import sys

sys.path.insert(0, "src/layers/common")

from self_checkin import (
    effective_not_riding_allowed,
    effective_quit_riding_allowed,
    effective_self_checkin_allowed,
)


def test_stage_permission_precedence_and_defaults():
    tour = {}
    ride = {"selfCheckInAllowed": False}
    assert effective_self_checkin_allowed(tour, ride, {"type": "START"}) is False
    assert effective_self_checkin_allowed(tour, {}, {"type": "START"}) is True
    assert effective_self_checkin_allowed(tour, {}, {"type": "PIT_STOP"}) is False
    assert effective_self_checkin_allowed(
        tour, {"selfCheckInAllowed": False}, {"type": "PIT_STOP", "selfCheckInAllowed": True}
    ) is True


def test_quit_riding_ride_override_wins_over_tour():
    assert effective_quit_riding_allowed({"selfQuitRidingAllowed": True}, {}) is True
    assert effective_quit_riding_allowed(
        {"selfQuitRidingAllowed": True}, {"selfQuitRidingAllowed": False}
    ) is False


def test_not_riding_is_start_only():
    assert effective_not_riding_allowed({"type": "START", "selfNotRidingAllowed": True})
    assert not effective_not_riding_allowed({"type": "PIT_STOP", "selfNotRidingAllowed": True})
