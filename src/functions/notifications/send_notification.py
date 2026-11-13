import sys

from notification_common import get_jwt_claim, parse_json_body
from logger import get_logger, log_event
from notification_service import notify, validate_audiences
from rbac import Permission, require_permission
from response import bad_request_response, success_response
from handler_utils import api_handler

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)


@api_handler("Failed to send notification")
def lambda_handler(event, context):
    try:
        log_event(logger, event)
        deny = require_permission(event, Permission.NOTIFICATION_MANAGE)
        if deny:
            return deny

        body = parse_json_body(event)
        rule_id = body.get("ruleId")
        if not isinstance(rule_id, str) or not rule_id:
            return bad_request_response("ruleId is required")
        audience_override = body.get("audiences")
        if audience_override is not None:
            validate_audiences(audience_override)

        notification_id = notify(
            rule_id=rule_id,
            tour_id=body.get("tourId"),
            context=body.get("context") or {},
            audience_override=audience_override,
            actor=get_jwt_claim(event, "sub", "system"),
        )
        if not notification_id:
            return success_response({"notificationId": None})

        return success_response({"notificationId": notification_id})

    except ValueError as exc:
        return bad_request_response(str(exc))
