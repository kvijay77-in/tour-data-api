"""
Get active tour Lambda function

Returns the currently active tour using the StatusIndex GSI.
"""

import sys

from logger import get_logger, log_event
from self_service_policy import apply_tour_defaults
from response import success_response, error_response
from handler_utils import api_handler
from dynamodb_utils import query_items
from models import TourStatus

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)


@api_handler("Failed to retrieve active tour")
def lambda_handler(event, context):
    """
    Get the currently active tour

    Uses StatusIndex GSI to efficiently query by status.

    Returns:
        200: Active tour data
        404: No active tour found
        500: Server error
    """
    logger.info("Getting active tour")
    log_event(logger, event)

    # Use StatusIndex GSI to query for ACTIVE tours
    items = query_items(
        table_name_env="TOUR_MASTER_TABLE",
        key_condition_expression="#status = :status",
        expression_values={":status": TourStatus.ACTIVE.value},
        expression_names={"#status": "status"},
        index_name="StatusIndex",
    )

    if not items:
        return error_response(
            error_code="NO_ACTIVE_TOUR", message="No active tour found", status_code=404
        )

    # Return first active tour (should be only one)
    tour = items[0]

    logger.info("Found active tour: %s", tour.get("tourId"))
    return success_response(apply_tour_defaults(tour))
