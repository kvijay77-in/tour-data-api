import sys

import boto3

from logger import get_logger, log_event
from rbac import Permission, require_permission
from response import internal_error_response, success_response

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)
dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    try:
        log_event(logger, event)
        deny = require_permission(event, Permission.NOTIFICATION_MANAGE)
        if deny:
            return deny
        table = dynamodb.Table(__import__('os').environ['NOTIFICATION_RULE_TABLE'])
        items = table.scan().get('Items', [])
        items.sort(key=lambda row: row.get('ruleId', ''))
        return success_response({'items': items, 'count': len(items)})
    except Exception as exc:
        logger.error('list rules failed: %s', str(exc), exc_info=True)
        return internal_error_response('Failed to list rules')
