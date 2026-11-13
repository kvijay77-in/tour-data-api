"""
Update tour Lambda function

Updates an existing TourMaster item and optionally provisions its tour-specific
tables when they have not been provisioned before.
"""

import sys

import json

import boto3

from logger import get_logger, log_event
from response import (
    success_response, bad_request_response, not_found_response,
    internal_error_response, validation_exception_response
)
from dynamodb_utils import get_item, put_item
from validation import (
    validate_tour_id, validate_iso_date, validate_ride_count, validate_optional_bool, ValidationError
)
from models import TourStatus, utc_now_iso
from tour_provisioning import provision_tour_tables
from self_service_policy import apply_tour_defaults
from rbac import require_permission, Permission

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)

dynamodb_client = boto3.client('dynamodb')

TOUR_UPDATE_FIELDS = {'name', 'startDate', 'endDate', 'description', 'status', 'rideCount', 'selfQuitRidingAllowed'}


def _validate_optional_bool(value, field_name):
    """Validate an optional boolean request field."""
    if value is not None and not isinstance(value, bool):
        raise ValidationError(f"{field_name} must be a boolean")


def _validate_update_fields(updates, merged_tour):
    """Validate TourMaster update fields."""
    for field_name, value in updates.items():
        if value is None:
            raise ValidationError(f"{field_name} cannot be null")

        if field_name in {'name', 'description'} and not isinstance(value, str):
            raise ValidationError(f"{field_name} must be a string")

    if 'startDate' in updates:
        if not isinstance(updates['startDate'], str):
            raise ValidationError("startDate must be a string in YYYY-MM-DD format")
        validate_iso_date(updates['startDate'], 'startDate')

    if 'endDate' in updates:
        if not isinstance(updates['endDate'], str):
            raise ValidationError("endDate must be a string in YYYY-MM-DD format")
        validate_iso_date(updates['endDate'], 'endDate')

    if 'rideCount' in updates:
        validate_ride_count(updates['rideCount'])

    if merged_tour['endDate'] < merged_tour['startDate']:
        raise ValidationError("endDate must be on or after startDate")

    if 'status' in updates:
        try:
            merged_tour['status'] = TourStatus(updates['status'].upper()).value
        except (AttributeError, ValueError):
            valid_statuses = ', '.join(status.value for status in TourStatus)
            raise ValidationError(f"Invalid status. Must be one of: {valid_statuses}")


def lambda_handler(event, context):
    """
    Update an existing tour and rerun tour-specific table provisioning.

    Body:
        tourId: Existing tour identifier (required)
        provisioning: Whether to provision tour-specific tables (optional, default false).
        name: Tour name (optional)
        startDate: ISO 8601 date (optional)
        endDate: ISO 8601 date (optional)
        description: Tour description (optional)
        rideCount: Total number of rides planned for the tour (optional, positive integer)
        status: Tour status (optional)
        selfQuitRidingAllowed: Whether riders may self-report Quit Riding (optional boolean)
    """
    try:
        log_event(logger, event)

        deny = require_permission(event, Permission.TOUR_MANAGE)
        if deny:
            return deny

        body = json.loads(event.get('body') or '{}')
        tour_id = body.get('tourId')
        if not tour_id:
            return bad_request_response("tourId is required")

        try:
            validate_tour_id(tour_id)
            _validate_optional_bool(body.get('provisioning'), 'provisioning')
        except ValidationError as e:
            return bad_request_response(str(e))

        if 'provisionOnly' in body:
            return bad_request_response(
                "provisionOnly is not supported; use PUT /v1/tours/{tourId}/provision"
            )

        provisioning = body.get('provisioning', False)

        tour = get_item(
            table_name_env='TOUR_MASTER_TABLE',
            key={'tourId': tour_id}
        )
        if not tour:
            return not_found_response("Tour", tour_id)

        if provisioning and tour.get('provisionedAt'):
            return bad_request_response(
                "Tour tables are already provisioned; use PUT /v1/tours/{tourId}/provision"
            )

        updates = {key: body[key] for key in TOUR_UPDATE_FIELDS if key in body}
        if not updates and not provisioning:
            return bad_request_response("At least one TourMaster field is required")

        updated_tour = {**tour, **updates}
        if 'selfQuitRidingAllowed' in updates:
            try:
                validate_optional_bool(updates['selfQuitRidingAllowed'], 'selfQuitRidingAllowed')
            except ValidationError as e:
                return validation_exception_response(e)
            updates['selfQuitRidingAllowed'] = updates['selfQuitRidingAllowed'] is True
            updated_tour['selfQuitRidingAllowed'] = updates['selfQuitRidingAllowed']
        try:
            _validate_update_fields(updates, updated_tour)
        except ValidationError as e:
            return bad_request_response(str(e))

        if updates:
            updated_tour['updatedAt'] = utc_now_iso()
            put_item('TOUR_MASTER_TABLE', updated_tour)

        if not provisioning:
            return success_response({
                'tour': apply_tour_defaults(updated_tour),
                'provisioning': provisioning,
                'provisionedTables': [],
            })

        try:
            provisioned_tables = provision_tour_tables(
                dynamodb_client,
                tour_id,
                ignore_existing=True,
            )
        except Exception as e:
            logger.error("Error provisioning tables for tour %s: %s", tour_id, e)
            updated_tour['provisioningError'] = str(e)
            updated_tour['updatedAt'] = utc_now_iso()
            put_item('TOUR_MASTER_TABLE', updated_tour)
            return internal_error_response(f"Tour update processed but table provisioning failed: {str(e)}")

        updated_tour.pop('provisioningError', None)
        updated_tour['provisionedAt'] = utc_now_iso()
        updated_tour['updatedAt'] = utc_now_iso()
        put_item('TOUR_MASTER_TABLE', updated_tour)

        logger.info("Tour %s provisioning rerun completed with %s tables", tour_id, len(provisioned_tables))
        return success_response({
            'tour': apply_tour_defaults(updated_tour),
            'provisioning': provisioning,
            'provisionedTables': provisioned_tables,
        })

    except json.JSONDecodeError:
        return bad_request_response("Invalid JSON in request body")
    except Exception as e:
        logger.error("Error updating tour: %s", e, exc_info=True)
        return internal_error_response("Failed to update tour")
