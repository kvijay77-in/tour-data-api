import sys

from rbac import Permission, require_permission
from event_engine import get_hotel_upload_status

sys.path.insert(0, '/opt/python')


def lambda_handler(event, context):
    deny = require_permission(event, Permission.HOTEL_ALLOC_MANAGE)
    if deny:
        return deny
    return get_hotel_upload_status(event)
