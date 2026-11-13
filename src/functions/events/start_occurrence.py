import sys

from rbac import Permission, require_permission
from event_engine import start_occurrence

sys.path.insert(0, '/opt/python')


def lambda_handler(event, context):
    deny = require_permission(event, Permission.EVENT_OCCURRENCE_MANAGE)
    if deny:
        return deny
    return start_occurrence(event)
