import sys

import boto3

from notification_common import get_jwt_claim, parse_json_body
from logger import get_logger, log_event
from notification_service import validate_rule_payload
from rbac import Permission, require_permission
from response import bad_request_response, not_found_response, success_response
from handler_utils import api_handler
from models import utc_now_iso

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)
dynamodb = boto3.resource("dynamodb")


@api_handler("Failed to update rule")
def lambda_handler(event, context):
    try:
        log_event(logger, event)
        deny = require_permission(event, Permission.NOTIFICATION_MANAGE)
        if deny:
            return deny

        rule_id = (event.get("pathParameters") or {}).get("ruleId")
        if not rule_id:
            return bad_request_response("ruleId is required in path")

        body = parse_json_body(event)
        validated = validate_rule_payload({**body, "ruleId": rule_id}, partial=False)

        table = dynamodb.Table(__import__("os").environ["NOTIFICATION_RULE_TABLE"])
        existing = table.get_item(Key={"ruleId": rule_id}).get("Item")
        if not existing:
            return not_found_response("NotificationRule", rule_id)

        validated["version"] = int(existing.get("version") or 0) + 1
        validated["updatedAt"] = utc_now_iso()
        validated["updatedBy"] = get_jwt_claim(event, "sub", "system")

        table.put_item(Item=validated)
        return success_response(validated)
    except ValueError as exc:
        return bad_request_response(str(exc))
