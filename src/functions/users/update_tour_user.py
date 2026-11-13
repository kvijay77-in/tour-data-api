import sys

from rbac import Permission, require_permission
from event_engine import update_tour_user

sys.path.insert(0, '/opt/python')


def lambda_handler(event, context):
    deny = require_permission(event, Permission.USER_MANAGE)
    if deny:
        return deny
    return update_tour_user(event)
