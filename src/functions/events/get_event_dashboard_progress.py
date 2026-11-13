import sys

from rbac import Permission, require_permission
from event_engine import get_event_dashboard_progress

sys.path.insert(0, "/opt/python")


def lambda_handler(event, context):
    deny = require_permission(event, Permission.DASHBOARD)
    if deny:
        return deny
    return get_event_dashboard_progress(event)
