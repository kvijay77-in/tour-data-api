import sys

from rbac import Permission, require_permission
from event_engine import update_hotel

sys.path.insert(0, '/opt/python')


def lambda_handler(event, context):
    deny = require_permission(event, Permission.HOTEL_ALLOC_MANAGE)
    if deny:
        return deny
    return update_hotel(event)
