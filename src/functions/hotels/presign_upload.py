import sys
sys.path.insert(0, '/opt/python')

from rbac import Permission, require_permission
from event_engine import presign_hotel_upload


def lambda_handler(event, context):
    deny = require_permission(event, Permission.HOTEL_ALLOC_MANAGE)
    if deny:
        return deny
    return presign_hotel_upload(event)
