"""Mgmt API: list registrations for an event occurrence."""
import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from event_self_service import list_registrations


def lambda_handler(event, context):
    deny = require_permission(event, Permission.EVENT_REGISTRATION_MANAGE)
    if deny:
        return deny
    return list_registrations(event)
