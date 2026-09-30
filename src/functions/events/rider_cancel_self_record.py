"""Rider-only event activity cancellation endpoint."""

import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from cancel_activity_record import lambda_handler as cancel_record


def lambda_handler(event, context):
    deny = require_permission(event, Permission.SELF_CHECKIN)
    if deny:
        return deny
    request = dict(event)
    request['_self_service'] = True
    return cancel_record(request, context)
