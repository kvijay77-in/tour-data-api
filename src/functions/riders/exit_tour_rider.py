"""
Lambda function to mark a rider as EXITED from a tour.

Special update behavior:
- updates existing TourRider row only
- sets status = EXITED
- captures previous status in prevStatus
- captures exitedAt and exitedBy audit attributes

Route: POST /v1/tours/{tourId}/riders/{riderId}/exit
"""

import sys

import json

from logger import get_logger
from response import (
    success_response,
    bad_request_response,
    not_found_response,
    conflict_response,
    error_response,
)
from handler_utils import api_handler
from validation import validate_tour_id, validate_rider_id, ValidationError
from models import BaggageStatus, TourRiderStatus, utc_now_iso
from dynamodb_utils import get_tour_item, update_tour_item
from notification_service import notify
from rbac import Permission, require_permission

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)


def _get_claim(event, key, default=""):
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
        .get(key, default)
    )


@api_handler("Failed to update rider exit status")
def lambda_handler(event, context):
    """Set tour rider status to EXITED and capture exit metadata."""
    deny = require_permission(event, Permission.RIDER_EXIT)
    if deny:
        return deny

    path_params = event.get("pathParameters", {})
    tour_id = path_params.get("tourId")
    rider_id = path_params.get("riderId")

    if not tour_id or not rider_id:
        return bad_request_response("tourId and riderId are required in path")

    try:
        validate_tour_id(tour_id)
        validate_rider_id(rider_id)
    except ValidationError as e:
        return bad_request_response(str(e))

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return bad_request_response("Invalid JSON in request body")

    baggage_disposition = body.get("baggageDisposition")
    if baggage_disposition not in {
        BaggageStatus.RETAINED.value,
        BaggageStatus.WITH_RIDER.value,
    }:
        return error_response(
            error_code="BAGGAGE_DISPOSITION_REQUIRED",
            message="Choose whether baggage is retained or released before exiting this rider.",
            status_code=400,
        )

    existing = get_tour_item(
        table_type="TourRider", tour_id=tour_id, key={"riderId": rider_id}
    )
    if not existing:
        return not_found_response("TourRider", rider_id)

    current_status = str(existing.get("status", "")).strip()
    if current_status == TourRiderStatus.EXITED.value:
        return conflict_response(
            f"Rider '{rider_id}' is already in EXITED status",
            error_code="RIDER_ALREADY_EXITED",
        )

    exited_by = _get_claim(event, "sub", "system")
    now = utc_now_iso()
    update_expression = (
        "SET #status = :status, "
        "prevStatus = :prevStatus, "
        "exitedAt = :exitedAt, "
        "exitedBy = :exitedBy, "
        "baggageStatus = :baggageStatus, "
        "baggageExitNote = :baggageExitNote, "
        "updatedAt = :updatedAt"
    )
    expression_values = {
        ":status": TourRiderStatus.EXITED.value,
        ":prevStatus": current_status,
        ":exitedAt": now,
        ":exitedBy": exited_by,
        ":baggageStatus": baggage_disposition,
        ":baggageExitNote": body.get("note"),
        ":updatedAt": now,
    }
    if baggage_disposition == BaggageStatus.RETAINED.value:
        update_expression += ", baggageExitedAt = :baggageExitedAt, baggageExitedBy = :baggageExitedBy REMOVE baggageReleasedAt, baggageReleasedBy"
        expression_values[":baggageExitedAt"] = now
        expression_values[":baggageExitedBy"] = exited_by
    else:
        update_expression += ", baggageReleasedAt = :baggageReleasedAt, baggageReleasedBy = :baggageReleasedBy REMOVE baggageExitedAt, baggageExitedBy"
        expression_values[":baggageReleasedAt"] = now
        expression_values[":baggageReleasedBy"] = exited_by

    updated = update_tour_item(
        table_type="TourRider",
        tour_id=tour_id,
        key={"riderId": rider_id},
        update_expression=update_expression,
        expression_values=expression_values,
        expression_names={"#status": "status"},
    )

    profile_id = existing.get("profileId")
    if profile_id:
        notify(
            rule_id="RIDER_EXITED",
            tour_id=tour_id,
            context={
                "riderId": rider_id,
                "profileId": profile_id,
                "baggageDisposition": baggage_disposition,
            },
            audience_override=[f"PROFILE#{profile_id}"],
            actor=exited_by,
        )

    return success_response(updated)
