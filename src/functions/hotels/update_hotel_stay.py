import sys

from rbac import Permission, require_permission
from event_engine import upsert_hotel_stay

sys.path.insert(0, '/opt/python')


def lambda_handler(event, context):
    deny = require_permission(event, Permission.HOTEL_ALLOC_MANAGE)
    if deny:
        return deny
    return upsert_hotel_stay(event)
