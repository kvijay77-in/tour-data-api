import sys

from rbac import Permission, require_permission
from event_engine import get_current_tour_user

sys.path.insert(0, '/opt/python')


def lambda_handler(event, context):
    deny = require_permission(event, Permission.READ)
    if deny:
        return deny
    return get_current_tour_user(event)
