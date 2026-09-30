"""Rider-only check-in cancellation endpoint."""

import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from cancel_checkin import lambda_handler as cancel_checkin


def lambda_handler(event, context):
    deny = require_permission(event, Permission.SELF_CHECKIN)
    if deny:
        return deny
    request = dict(event)
    request['_self_service'] = True
    return cancel_checkin(request, context)
