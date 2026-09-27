import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from event_engine import get_dashboard


def lambda_handler(event, context):
    deny = require_permission(event, Permission.DASHBOARD)
    if deny:
        return deny
    return get_dashboard(event)
