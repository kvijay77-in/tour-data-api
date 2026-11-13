"""Get rider profile by profile ID with ownership and role-based attribute filtering."""

import sys

from logger import get_logger, log_event
from response import success_response, not_found_response, bad_request_response
from handler_utils import api_handler
from dynamodb_utils import get_item
from validation import build_emergency_contact_from_profile
from ownership import require_own_profile, is_rider_api_request
from profile_schema import filter_profile_for_response

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)


@api_handler("Failed to get rider profile")
def lambda_handler(event, context):
    log_event(logger, event)
    profile_id = (event.get("pathParameters") or {}).get("profileId")
    if not profile_id:
        return bad_request_response("profileId is required in path")

    deny = require_own_profile(event, profile_id)
    if deny:
        return deny

    rider = get_item("RIDER_PROFILE_TABLE", {"profileId": profile_id})
    if not rider:
        return not_found_response("RiderProfile", profile_id)

    emergency_contact = build_emergency_contact_from_profile(rider)
    if emergency_contact is not None:
        rider["emergencyContact"] = emergency_contact

    rider.pop("emergencyContactName", None)
    rider.pop("emergencyContactPhone", None)
    rider.pop("emergencyContactRelationship", None)
    rider.pop("Relationship", None)

    staff_mode = not is_rider_api_request(event)
    filtered = filter_profile_for_response(rider, event=event, staff_mode=staff_mode)
    return success_response(filtered)
