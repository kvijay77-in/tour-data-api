import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from event_engine import list_hotels


def lambda_handler(event, context):
    deny = require_permission(event, Permission.READ)
    if deny:
        return deny
    return list_hotels(event)
