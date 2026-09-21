import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from event_engine import create_activity_record


def lambda_handler(event, context):
    deny = require_permission(event, Permission.EVENT_SCAN)
    if deny:
        return deny
    return create_activity_record(event)
