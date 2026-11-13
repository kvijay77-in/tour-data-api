"""Re-provision tour-specific DynamoDB tables without modifying TourMaster."""

import sys

import boto3

from dynamodb_utils import get_item
from logger import get_logger, log_event
from rbac import Permission, require_permission
from self_service_policy import apply_tour_defaults
from response import bad_request_response, not_found_response, success_response
from handler_utils import api_handler
from tour_provisioning import provision_tour_tables
from validation import ValidationError, validate_tour_id

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)

dynamodb_client = boto3.client('dynamodb')


@api_handler('Failed to re-provision tour tables')
def lambda_handler(event, context):
    """Create any missing tables for an already provisioned tour."""
    log_event(logger, event)

    deny = require_permission(event, Permission.TOUR_MANAGE)
    if deny:
        return deny

    tour_id = (event.get('pathParameters') or {}).get('tourId')
    if not tour_id:
        return bad_request_response("tourId is required in path")

    try:
        validate_tour_id(tour_id)
    except ValidationError as e:
        return bad_request_response(str(e))

    tour = get_item('TOUR_MASTER_TABLE', {'tourId': tour_id})
    if not tour:
        return not_found_response("Tour", tour_id)

    if not tour.get('provisionedAt'):
        return bad_request_response(
            "Tour tables have not been provisioned; use PUT /v1/tours with provisioning=true"
        )

    provisioned_tables = provision_tour_tables(
        dynamodb_client,
        tour_id,
        ignore_existing=True,
    )

    logger.info(
        "Tour %s re-provisioning completed with %s tables", tour_id, len(provisioned_tables)
    )
    return success_response({
        'tour': apply_tour_defaults(tour),
        'provisionedTables': provisioned_tables,
    })