"""
Lambda function to release a retained rider baggage back to the rider.

Route: POST /v1/tours/{tourId}/riders/{riderId}/baggage/release
"""

import sys

import json

from logger import get_logger
from response import (
    bad_request_response,
    error_response,
    not_found_response,
    success_response,
)
from handler_utils import api_handler
from validation import ValidationError, validate_rider_id, validate_tour_id
from models import BaggageStatus, utc_now_iso
from dynamodb_utils import get_tour_item, update_tour_item
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


@api_handler("Failed to release rider baggage")
def lambda_handler(event, context):
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
    except ValidationError as exc:
        return bad_request_response(str(exc))

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return bad_request_response("Invalid JSON in request body")

    rider = get_tour_item("TourRider", tour_id, {"riderId": rider_id})
    if not rider:
        return not_found_response("TourRider", rider_id)

    if rider.get("baggageStatus") != BaggageStatus.RETAINED.value:
        return error_response(
            error_code="BAGGAGE_NOT_RETAINED",
            message="Baggage release is valid only when baggageStatus is RETAINED.",
            status_code=409,
        )

    now = utc_now_iso()
    updated = update_tour_item(
        table_type="TourRider",
        tour_id=tour_id,
        key={"riderId": rider_id},
        update_expression=(
            "SET baggageStatus = :baggageStatus, "
            "baggageReleasedAt = :baggageReleasedAt, "
            "baggageReleasedBy = :baggageReleasedBy, "
            "baggageExitNote = :baggageExitNote, "
            "updatedAt = :updatedAt"
        ),
        expression_values={
            ":baggageStatus": BaggageStatus.WITH_RIDER.value,
            ":baggageReleasedAt": now,
            ":baggageReleasedBy": _get_claim(event, "sub", "system"),
            ":baggageExitNote": body.get("note"),
            ":updatedAt": now,
        },
    )
    return success_response(updated)
