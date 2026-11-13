"""
Get tour by ID Lambda function
"""

import sys

from logger import get_logger, log_event
from self_service_policy import apply_tour_defaults
from response import success_response, not_found_response, bad_request_response
from handler_utils import api_handler
from dynamodb_utils import get_item
from validation import validate_tour_id, ValidationError

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)


@api_handler("Failed to retrieve tour")
def lambda_handler(event, context):
    """
    Get tour by ID

    Path Parameters:
        tourId: Tour identifier (e.g., TOT-2026)
    """
    log_event(logger, event)

    # Extract tour ID from path parameters
    tour_id = event.get("pathParameters", {}).get("tourId")

    if not tour_id:
        return bad_request_response("tourId is required in path")

    # Validate tour ID format
    try:
        validate_tour_id(tour_id)
    except ValidationError as e:
        return bad_request_response(str(e))

    logger.info("Getting tour: %s", tour_id)

    # Get tour from DynamoDB
    tour = get_item(table_name_env="TOUR_MASTER_TABLE", key={"tourId": tour_id})

    if not tour:
        return not_found_response("Tour", tour_id)

    logger.info("Found tour: %s", tour_id)
    return success_response(apply_tour_defaults(tour))
