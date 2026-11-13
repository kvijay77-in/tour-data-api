import sys

from rbac import Permission, require_permission
from event_engine import get_hotel_stays

sys.path.insert(0, '/opt/python')


def lambda_handler(event, context):
    deny = require_permission(event, Permission.READ)
    if deny:
        return deny
    return get_hotel_stays(event)
