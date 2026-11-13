"""Mgmt API: staff un-registers a rider from an event occurrence."""

import sys

from rbac import Permission, require_permission
from event_self_service import staff_unregister

sys.path.insert(0, "/opt/python")


def lambda_handler(event, context):
    deny = require_permission(event, Permission.EVENT_REGISTRATION_MANAGE)
    if deny:
        return deny
    return staff_unregister(event)
