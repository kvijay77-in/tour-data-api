"""Rider API: rider self-service activity record."""
import sys

from rbac import Permission, require_permission
from event_self_service import create_self_record

sys.path.insert(0, '/opt/python')


def lambda_handler(event, context):
    deny = require_permission(event, Permission.SELF_CHECKIN)
    if deny:
        return deny
    return create_self_record(event)
