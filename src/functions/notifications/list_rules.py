import sys

import boto3

from logger import get_logger, log_event
from rbac import Permission, require_permission
from response import success_response
from handler_utils import api_handler

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)
dynamodb = boto3.resource('dynamodb')


@api_handler('Failed to list rules')
def lambda_handler(event, context):
    log_event(logger, event)
    deny = require_permission(event, Permission.NOTIFICATION_MANAGE)
    if deny:
        return deny
    table = dynamodb.Table(__import__('os').environ['NOTIFICATION_RULE_TABLE'])
    items = table.scan().get('Items', [])
    items.sort(key=lambda row: row.get('ruleId', ''))
    return success_response({'items': items, 'count': len(items)})
