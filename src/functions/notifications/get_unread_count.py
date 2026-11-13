import sys

import json
from response import success_response
from get_notifications import lambda_handler as list_handler

sys.path.insert(0, '/opt/python')


def lambda_handler(event, context):
    response = list_handler(event, context)
    if response.get('statusCode') != 200:
        return response

    body = json.loads(response['body'])
    unread = body.get('data', {}).get('unreadCount', 0)

    return success_response({'unreadCount': unread})
