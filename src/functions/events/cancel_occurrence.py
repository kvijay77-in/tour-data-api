import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from event_engine import cancel_occurrence


def lambda_handler(event, context):
    deny = require_permission(event, Permission.EVENT_OCCURRENCE_MANAGE)
    if deny:
        return deny
    return cancel_occurrence(event)
