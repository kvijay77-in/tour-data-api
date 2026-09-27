import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from event_engine import cancel_activity_record


def lambda_handler(event, context):
    deny = require_permission(event, Permission.EVENT_SCAN)
    if deny:
        return deny
    return cancel_activity_record(event)
