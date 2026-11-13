"""
Create a new tour Lambda function

Creates the Tour record in the shared TourMaster table and optionally
provisions tour-specific DynamoDB tables.
"""

import sys
import json
import boto3

from logger import get_logger, log_event
from response import (
    success_response,
    bad_request_response,
    conflict_response,
    internal_error_response,
    validation_exception_response,
)
from handler_utils import api_handler
from dynamodb_utils import get_item, put_item
from validation import (
    validate_tour_id,
    validate_iso_date,
    validate_required_fields,
    validate_ride_count,
    validate_optional_bool,
    ValidationError,
)
from models import TourStatus, utc_now_iso
from tour_provisioning import provision_tour_tables
from rbac import require_permission, Permission

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)

dynamodb_client = boto3.client("dynamodb")


@api_handler("Failed to create tour")
def lambda_handler(event, context):
    """
    Create a new tour

    Body:
        tourId: Free-form tour identifier (required, 3-50 chars)
        name: Tour name (required)
        startDate: ISO 8601 date (required)
        endDate: ISO 8601 date (required)
        rideCount: Total number of rides planned for the tour (required, positive integer)
        description: Tour description (optional)
        provisioning: Whether to provision tour-specific tables (optional, default false)
        selfQuitRidingAllowed: Whether riders may self-report Quit Riding (optional, default false)

    Creates:
        1. Tour record in shared TourMaster table
        2. Tour-specific DynamoDB tables only when provisioning is true
        3. Updates Tour status to PLANNING once requested tables are active
    """
    try:
        log_event(logger, event)

        # Enforce RBAC — only TOUR_MANAGE permission may create tours
        deny = require_permission(event, Permission.TOUR_MANAGE)
        if deny:
            return deny

        # Parse request body
        body = json.loads(event.get("body", "{}"))

        # Validate required fields
        try:
            validate_required_fields(
                body, ["tourId", "name", "startDate", "endDate", "rideCount"]
            )
        except ValidationError as e:
            return bad_request_response(str(e))

        tour_id = body["tourId"]

        # Validate tour ID format
        try:
            validate_tour_id(tour_id)
        except ValidationError as e:
            return bad_request_response(str(e))

        # Validate dates
        try:
            validate_iso_date(body["startDate"], "startDate")
            validate_iso_date(body["endDate"], "endDate")
        except ValidationError as e:
            return bad_request_response(str(e))

        if body["endDate"] < body["startDate"]:
            return bad_request_response("endDate must be on or after startDate")

        try:
            validate_ride_count(body["rideCount"])
        except ValidationError as e:
            return bad_request_response(str(e))

        # Check tourId uniqueness
        existing = get_item(table_name_env="TOUR_MASTER_TABLE", key={"tourId": tour_id})

        if existing:
            return conflict_response(f"Tour '{tour_id}' already exists")

        provisioning = body.get("provisioning", False)
        if not isinstance(provisioning, bool):
            return bad_request_response("provisioning must be a boolean")

        self_quit_riding_allowed = body.get("selfQuitRidingAllowed", False)
        try:
            validate_optional_bool(self_quit_riding_allowed, "selfQuitRidingAllowed")
        except ValidationError as e:
            return validation_exception_response(e)
        self_quit_riding_allowed = self_quit_riding_allowed is True

        # Create Tour record. Provisioning is request-only and is not stored.
        now = utc_now_iso()
        tour_item = {
            "tourId": tour_id,
            "name": body["name"],
            "startDate": body["startDate"],
            "endDate": body["endDate"],
            "status": (
                TourStatus.PROVISIONING.value
                if provisioning
                else TourStatus.PLANNING.value
            ),
            "rideCount": body["rideCount"],
            "selfQuitRidingAllowed": self_quit_riding_allowed,
            "createdAt": now,
            "updatedAt": now,
        }

        if body.get("description"):
            tour_item["description"] = body["description"]

        put_item("TOUR_MASTER_TABLE", tour_item)
        logger.info(
            "Tour record created: %s (status: %s)", tour_id, tour_item["status"]
        )

        if not provisioning:
            return success_response(tour_item, status_code=201)

        # Provision tour-specific tables
        created_tables = []
        try:
            created_tables = provision_tour_tables(dynamodb_client, tour_id)

        except Exception as e:  # pylint: disable=broad-exception-caught
            # Intentionally broad: any provisioning failure must be recorded on the tour.
            logger.error("Error provisioning tables for tour %s: %s", tour_id, e)
            # Update tour status to indicate failure
            tour_item["status"] = TourStatus.PLANNING.value
            tour_item["updatedAt"] = utc_now_iso()
            tour_item["provisioningError"] = str(e)
            put_item("TOUR_MASTER_TABLE", tour_item)
            return internal_error_response(
                f"Tour created but table provisioning failed: {str(e)}"
            )

        # Update tour status to PLANNING
        tour_item["status"] = TourStatus.PLANNING.value
        tour_item["provisionedAt"] = utc_now_iso()
        tour_item["updatedAt"] = utc_now_iso()
        put_item("TOUR_MASTER_TABLE", tour_item)

        logger.info(
            "Tour %s provisioned successfully with %s tables",
            tour_id,
            len(created_tables),
        )

        return success_response(tour_item, status_code=201)

    except json.JSONDecodeError:
        return bad_request_response("Invalid JSON in request body")
