import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from event_engine import create_tour_user


def lambda_handler(event, context):
    deny = require_permission(event, Permission.USER_MANAGE)
    if deny:
        return deny
    return create_tour_user(event)
