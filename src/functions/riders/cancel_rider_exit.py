"""
Lambda function to cancel an EXITED status for a tour rider.

Special update behavior:
- valid only when current status is EXITED
- restores status from prevStatus
- removes prevStatus, exitedAt, exitedBy attributes

Route: POST /v1/tours/{tourId}/riders/{riderId}/exit/cancel
"""

import sys

from logger import get_logger
from response import (
    success_response,
    bad_request_response,
    not_found_response,
    error_response,
)
from handler_utils import api_handler
from validation import validate_tour_id, validate_rider_id, ValidationError
from models import BaggageStatus, TourRiderStatus, utc_now_iso
from dynamodb_utils import get_tour_item, update_tour_item
from rbac import Permission, require_permission

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def _get_claim(event, key, default=''):
    return (
        event.get('requestContext', {})
        .get('authorizer', {})
        .get('jwt', {})
        .get('claims', {})
        .get(key, default)
    )


@api_handler('Failed to cancel rider exit status')
def lambda_handler(event, context):
    """Revert EXITED status to prevStatus and clear exit metadata."""
    deny = require_permission(event, Permission.RIDER_EXIT)
    if deny:
        return deny

    path_params = event.get('pathParameters', {})
    tour_id = path_params.get('tourId')
    rider_id = path_params.get('riderId')

    if not tour_id or not rider_id:
        return bad_request_response("tourId and riderId are required in path")

    try:
        validate_tour_id(tour_id)
        validate_rider_id(rider_id)
    except ValidationError as e:
        return bad_request_response(str(e))

    existing = get_tour_item(
        table_type='TourRider',
        tour_id=tour_id,
        key={'riderId': rider_id}
    )
    if not existing:
        return not_found_response('TourRider', rider_id)

    current_status = str(existing.get('status', '')).strip()
    if current_status != TourRiderStatus.EXITED.value:
        return error_response(
            error_code='INVALID_EXIT_CANCEL_INVOCATION',
            message="Exit cancellation is valid only when rider status is EXITED",
            status_code=400,
        )

    prev_status = str(existing.get('prevStatus', '')).strip()
    if not prev_status:
        return bad_request_response("Cannot cancel exit because prevStatus is missing")

    updated = update_tour_item(
        table_type='TourRider',
        tour_id=tour_id,
        key={'riderId': rider_id},
        update_expression=(
            'SET #status = :status, baggageStatus = :baggageStatus, updatedAt = :updatedAt '
            'REMOVE prevStatus, exitedAt, exitedBy, '
            'baggageExitedAt, baggageExitedBy, baggageReleasedAt, '
            'baggageReleasedBy, baggageExitNote'
        ),
        expression_values={
            ':status': prev_status,
            ':updatedAt': utc_now_iso(),
            ':baggageStatus': BaggageStatus.ACTIVE.value,
        },
        expression_names={'#status': 'status'}
    )
    updated['baggageStatus'] = BaggageStatus.ACTIVE.value

    return success_response(updated)
