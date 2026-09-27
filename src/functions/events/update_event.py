import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from event_engine import update_event_definition


def lambda_handler(event, context):
    deny = require_permission(event, Permission.EVENT_MANAGE)
    if deny:
        return deny
    return update_event_definition(event)
