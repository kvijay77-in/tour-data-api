import sys

import os

import boto3
from boto3.dynamodb.conditions import Key

from notification_common import get_jwt_claim, get_profile_id_for_rider
from logger import get_logger, log_event
from response import internal_error_response

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)
dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    try:
        log_event(logger, event)
        token = (event.get('pathParameters') or {}).get('token')
        if not token:
            return {'statusCode': 204, 'headers': {'Access-Control-Allow-Origin': '*'}, 'body': ''}

        scope = os.environ.get('NOTIFICATION_SCOPE', 'mgmt')
        if scope == 'rider':
            profile_id = get_profile_id_for_rider(event)
            if profile_id:
                table = dynamodb.Table(os.environ['RIDER_PUSH_DEVICE_TABLE'])
                table.delete_item(Key={'profileId': profile_id, 'token': token})
        else:
            cognito_sub = get_jwt_claim(event, 'sub')
            if cognito_sub:
                table = dynamodb.Table(os.environ['MGMT_PUSH_DEVICE_TABLE'])
                rows = table.query(KeyConditionExpression=Key('cognitoSub').eq(cognito_sub)).get('Items', [])
                for row in rows:
                    if row.get('token') == token or row.get('deviceToken') == token:
                        table.delete_item(Key={'cognitoSub': cognito_sub, 'token': row['token']})

        return {'statusCode': 204, 'headers': {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type,Authorization', 'Access-Control-Allow-Methods': 'DELETE,OPTIONS'}, 'body': ''}
    except Exception as exc:
        logger.error('delete device failed: %s', str(exc), exc_info=True)
        return internal_error_response('Failed to delete device')
