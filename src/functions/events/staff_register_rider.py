"""Mgmt API: staff registers a rider for an event occurrence."""
import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from event_self_service import staff_register


def lambda_handler(event, context):
    deny = require_permission(event, Permission.EVENT_REGISTRATION_MANAGE)
    if deny:
        return deny
    return staff_register(event)
