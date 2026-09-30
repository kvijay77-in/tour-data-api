import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src/layers/common")
sys.path.insert(0, "src/functions/checkins")

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


def _self_checkin_event(body):
    return {
        "pathParameters": {"tourId": "TST-2026", "rideId": "RIDE001"},
        "requestContext": {
            "authorizer": {"jwt": {"claims": {"sub": "rider-sub", "cognito:groups": "RIDER"}}}
        },
        "body": json.dumps(body),
        "_self_service": True,
    }


def test_self_quit_riding_is_rejected_after_finish_checkin(monkeypatch):
    import create_checkin

    ride = {
        "rideId": "RIDE001",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "status": "STARTED",
        "selfQuitRidingAllowed": True,
        "stages": [
            {"stageNumber": 0, "stageId": "S000", "type": "START"},
            {"stageNumber": 1, "stageId": "S001", "type": "FINISH"},
        ],
    }

    monkeypatch.setattr(create_checkin, "require_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(create_checkin, "validate_tour_id", lambda value: None)
    monkeypatch.setattr(create_checkin, "resolve_profile_id_for_sub", lambda sub: "P001")
    monkeypatch.setattr(create_checkin, "get_item", lambda *args, **kwargs: {"status": "ACTIVE"})
    monkeypatch.setattr(
        create_checkin,
        "get_tour_item",
        lambda table_type, tour_id, key: ride if table_type == "Ride" else {"riderId": "R1", "status": "ACTIVE"},
    )
    monkeypatch.setattr(
        create_checkin,
        "query_tour_items",
        lambda table_type, *args, **kwargs: (
            [{"riderId": "R1"}]
            if table_type == "TourRider"
            else [{"stageNumber": 1, "isNotRiding": False, "isQuitRiding": False}]
        ),
    )
    monkeypatch.setattr(create_checkin, "get_user_pit_stop_stage_numbers", lambda event: set())

    response = create_checkin.lambda_handler(
        _self_checkin_event({"isQuitRiding": True}),
        None,
    )

    assert response["statusCode"] == 403
    assert json.loads(response["body"])["error"]["code"] == "SELF_CHECKIN_NOT_ALLOWED"


def test_exited_rider_cannot_self_check_in(monkeypatch):
    import create_checkin

    monkeypatch.setattr(create_checkin, "require_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(create_checkin, "validate_tour_id", lambda value: None)
    monkeypatch.setattr(create_checkin, "resolve_profile_id_for_sub", lambda sub: "P001")
    monkeypatch.setattr(create_checkin, "get_item", lambda *args, **kwargs: {"status": "ACTIVE"})
    monkeypatch.setattr(
        create_checkin,
        "get_tour_item",
        lambda table_type, tour_id, key: (
            {
                "rideId": "RIDE001",
                "date": datetime.now(timezone.utc).date().isoformat(),
                "status": "STARTED",
                "stages": [{"stageNumber": 0, "stageId": "S000", "type": "START"}],
            }
            if table_type == "Ride"
            else {"riderId": "R1", "status": "EXITED"}
        ),
    )
    monkeypatch.setattr(
        create_checkin,
        "query_tour_items",
        lambda *args, **kwargs: [{"riderId": "R1"}],
    )

    response = create_checkin.lambda_handler(
        _self_checkin_event({"stageNumber": 0}),
        None,
    )

    assert response["statusCode"] == 403
    assert json.loads(response["body"])["error"]["code"] == "RIDER_EXITED"
