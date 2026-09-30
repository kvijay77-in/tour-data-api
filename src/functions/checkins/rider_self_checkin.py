"""Rider-only check-in creation endpoint."""

import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from create_checkin import lambda_handler as create_checkin


def lambda_handler(event, context):
    deny = require_permission(event, Permission.SELF_CHECKIN)
    if deny:
        return deny
    request = dict(event)
    request['_self_service'] = True
    return create_checkin(request, context)
