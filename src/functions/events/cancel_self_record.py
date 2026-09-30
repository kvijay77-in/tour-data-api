"""Rider API: cancel the caller's own activity record."""
import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from event_self_service import cancel_self_record


def lambda_handler(event, context):
    deny = require_permission(event, Permission.SELF_CHECKIN)
    if deny:
        return deny
    return cancel_self_record(event)
