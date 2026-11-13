import sys

import boto3

from notification_common import get_jwt_claim, parse_json_body
from logger import get_logger, log_event
from notification_service import validate_rule_payload
from rbac import Permission, require_permission
from response import bad_request_response, conflict_response, success_response
from handler_utils import api_handler
from models import utc_now_iso

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)
dynamodb = boto3.resource('dynamodb')


@api_handler('Failed to create rule')
def lambda_handler(event, context):
    try:
        log_event(logger, event)
        deny = require_permission(event, Permission.NOTIFICATION_MANAGE)
        if deny:
            return deny

        body = parse_json_body(event)
        validated = validate_rule_payload(body, partial=False)
        validated['version'] = int(validated.get('version') or 1)
        validated['updatedAt'] = utc_now_iso()
        validated['updatedBy'] = get_jwt_claim(event, 'sub', 'system')

        table = dynamodb.Table(__import__('os').environ['NOTIFICATION_RULE_TABLE'])
        if table.get_item(Key={'ruleId': validated['ruleId']}).get('Item'):
            return conflict_response(f"NotificationRule '{validated['ruleId']}' already exists")
        table.put_item(Item=validated)
        return success_response(validated, status_code=201)
    except ValueError as exc:
        return bad_request_response(str(exc))
