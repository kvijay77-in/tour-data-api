"""Rider API: un-register the caller from an event occurrence."""

import sys

from rbac import Permission, require_permission
from event_self_service import unregister_self

sys.path.insert(0, "/opt/python")


def lambda_handler(event, context):
    deny = require_permission(event, Permission.READ)
    if deny:
        return deny
    return unregister_self(event)
