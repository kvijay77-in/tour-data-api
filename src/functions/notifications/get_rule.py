import sys
sys.path.insert(0, '/opt/python')

import boto3

from logger import get_logger, log_event
from rbac import Permission, require_permission
from response import bad_request_response, internal_error_response, not_found_response, success_response

logger = get_logger(__name__)
dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    try:
        log_event(logger, event)
        deny = require_permission(event, Permission.NOTIFICATION_MANAGE)
        if deny:
            return deny
        rule_id = (event.get('pathParameters') or {}).get('ruleId')
        if not rule_id:
            return bad_request_response('ruleId is required in path')
        table = dynamodb.Table(__import__('os').environ['NOTIFICATION_RULE_TABLE'])
        row = table.get_item(Key={'ruleId': rule_id}).get('Item')
        if not row:
            return not_found_response('NotificationRule', rule_id)
        return success_response(row)
    except Exception as exc:
        logger.error('get rule failed: %s', str(exc), exc_info=True)
        return internal_error_response('Failed to get rule')
