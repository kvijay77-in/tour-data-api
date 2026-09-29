import sys
sys.path.insert(0, '/opt/python')

import boto3

from logger import get_logger, log_event
from rbac import Permission, require_permission
from response import bad_request_response, internal_error_response

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
        table.delete_item(Key={'ruleId': rule_id})
        return {'statusCode': 204, 'headers': {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type,Authorization', 'Access-Control-Allow-Methods': 'DELETE,OPTIONS'}, 'body': ''}
    except Exception as exc:
        logger.error('delete rule failed: %s', str(exc), exc_info=True)
        return internal_error_response('Failed to delete rule')
