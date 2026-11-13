import sys

import os

from notification_common import (
    get_jwt_claim,
    get_profile_id_for_rider,
    get_state_key,
    own_table_for_scope,
    parse_iso_datetime,
    parse_json_body,
    set_state_row,
)
from logger import get_logger, log_event
from models import utc_now_iso
from response import bad_request_response, success_response
from handler_utils import api_handler

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)


@api_handler("Failed to mark notifications as read")
def lambda_handler(event, context):
    try:
        log_event(logger, event)
        scope = os.environ.get("NOTIFICATION_SCOPE", "mgmt")
        table_name = own_table_for_scope(scope)
        body = parse_json_body(event)
        read_at = body.get("readAt")
        if read_at:
            read_dt = parse_iso_datetime(read_at, "readAt")
            read_at = read_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        else:
            read_at = utc_now_iso()

        if scope == "rider":
            identity = get_profile_id_for_rider(event)
            if not identity:
                return bad_request_response(
                    "Unable to resolve rider profileId from identity"
                )
        else:
            identity = get_jwt_claim(event, "sub")
            if not identity:
                return bad_request_response("Unable to resolve user identity")

        set_state_row(table_name, get_state_key(scope, identity), read_at)
        return success_response({"readAt": read_at})

    except ValueError as exc:
        return bad_request_response(str(exc))
