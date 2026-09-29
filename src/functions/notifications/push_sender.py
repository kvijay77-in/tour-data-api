import sys
sys.path.insert(0, '/opt/python')

import json
import os
import urllib.request
from functools import lru_cache
from typing import Any, Dict, List

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeDeserializer

from common import split_base_token
from logger import get_logger, log_event

logger = get_logger(__name__)
deserializer = TypeDeserializer()
dynamodb = boto3.resource('dynamodb')
ssm = boto3.client('ssm')


@lru_cache(maxsize=4)
def _get_ssm_parameter(name: str) -> str:
    response = ssm.get_parameter(Name=name, WithDecryption=True)
    return response['Parameter']['Value']


def _deserialize_image(image: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return {key: deserializer.deserialize(value) for key, value in image.items()}


def _is_state_item(item: Dict[str, Any]) -> bool:
    return str(item.get('sk', '')).upper() == 'STATE'


def _query_rider_tokens_for_profile(profile_id: str) -> List[str]:
    table = dynamodb.Table(os.environ['RIDER_PUSH_DEVICE_TABLE'])
    rows = table.query(KeyConditionExpression=Key('profileId').eq(profile_id)).get('Items', [])
    return [row['token'] for row in rows if row.get('token')]


def _query_mgmt_tokens_for_user(sub: str) -> List[str]:
    table = dynamodb.Table(os.environ['MGMT_PUSH_DEVICE_TABLE'])
    rows = table.query(KeyConditionExpression=Key('cognitoSub').eq(sub)).get('Items', [])
    return [split_base_token(row['token']) for row in rows if row.get('itemType') == 'DEVICE' and row.get('token')]


def _query_mgmt_tokens_for_group(group: str) -> List[str]:
    table = dynamodb.Table(os.environ['MGMT_PUSH_DEVICE_TABLE'])
    rows = table.query(
        IndexName='GroupKeyIndex',
        KeyConditionExpression=Key('groupKey').eq(f'GROUP#{group}')
    ).get('Items', [])
    return [row.get('deviceToken') for row in rows if row.get('deviceToken')]


def _query_rider_profile_ids_for_tour(tour_id: str, status: str | None = None) -> List[str]:
    table = dynamodb.Table(os.environ['RIDER_TOURS_TABLE'])
    kwargs: Dict[str, Any] = {
        'IndexName': 'TourStatusIndex',
        'KeyConditionExpression': Key('tourId').eq(tour_id),
    }
    if status:
        kwargs['KeyConditionExpression'] = kwargs['KeyConditionExpression'] & Key('status').eq(status)
    rows = table.query(**kwargs).get('Items', [])
    profile_ids = []
    for row in rows:
        profile_id = row.get('profileId')
        if profile_id:
            profile_ids.append(profile_id)
    return profile_ids


def _query_tour_staff_groups(tour_id: str) -> List[str]:
    table = dynamodb.Table(f"{os.environ['STACK_NAME']}-User-{tour_id}")
    rows = _scan_all_items(table)
    return sorted({str(row.get('role')).strip() for row in rows if str(row.get('role', '')).strip()})


def _query_rider_tokens_for_profiles(profile_ids: List[str]) -> List[str]:
    tokens: List[str] = []
    for profile_id in profile_ids:
        tokens.extend(_query_rider_tokens_for_profile(profile_id))
    return tokens


def _scan_all_items(table) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {}
    while True:
        response = table.scan(**kwargs)
        items.extend(response.get('Items', []))
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            break
        kwargs['ExclusiveStartKey'] = last_key
    return items


def _resolve_tokens(item: Dict[str, Any]) -> List[str]:
    audience = str(item.get('audience') or '')
    if audience.startswith('PROFILE#'):
        return _query_rider_tokens_for_profile(audience.split('#', 1)[1])
    if audience.startswith('USER#'):
        return _query_mgmt_tokens_for_user(audience.split('#', 1)[1])
    if audience.startswith('GROUP#'):
        return _query_mgmt_tokens_for_group(audience.split('#', 1)[1])

    if audience == 'APP#RIDER':
        table = dynamodb.Table(os.environ['RIDER_PUSH_DEVICE_TABLE'])
        return [row.get('token') for row in _scan_all_items(table) if row.get('token')]

    if audience == 'APP#MGMT':
        table = dynamodb.Table(os.environ['MGMT_PUSH_DEVICE_TABLE'])
        return [split_base_token(row['token']) for row in _scan_all_items(table) if row.get('itemType') == 'DEVICE' and row.get('token')]

    if audience.startswith('TOUR#') and '#RIDER#' in audience:
        tour_id = audience.split('#')[1]
        rider_id = audience.split('#')[3]
        rider = dynamodb.Table(f"{os.environ['STACK_NAME']}-TourRider-{tour_id}").get_item(Key={'riderId': rider_id}).get('Item')
        if rider and rider.get('profileId'):
            return _query_rider_tokens_for_profile(rider['profileId'])

    if audience.startswith('TOUR#') and '#STATUS#' in audience:
        parts = audience.split('#')
        tour_id = parts[1]
        status = parts[3]
        return _query_rider_tokens_for_profiles(_query_rider_profile_ids_for_tour(tour_id, status=status))

    if audience.startswith('TOUR#') and audience.endswith('#APPLICANTS'):
        tour_id = audience.split('#')[1]
        return _query_rider_tokens_for_profiles(_query_rider_profile_ids_for_tour(tour_id))

    if audience.startswith('TOUR#') and audience.endswith('#APP#RIDER'):
        tour_id = audience.split('#')[1]
        return _query_rider_tokens_for_profiles(_query_rider_profile_ids_for_tour(tour_id))

    if audience.startswith('TOUR#') and audience.endswith('#APP#MGMT'):
        tour_id = audience.split('#')[1]
        groups = _query_tour_staff_groups(tour_id)
        tokens: List[str] = []
        for group in groups:
            tokens.extend(_query_mgmt_tokens_for_group(group))
        return tokens

    if audience.startswith('TOUR#') and audience.endswith('#ALL'):
        tour_id = audience.split('#')[1]
        rider_tokens = _query_rider_tokens_for_profiles(_query_rider_profile_ids_for_tour(tour_id))
        mgmt_tokens: List[str] = []
        for group in _query_tour_staff_groups(tour_id):
            mgmt_tokens.extend(_query_mgmt_tokens_for_group(group))
        return rider_tokens + mgmt_tokens

    if audience.startswith('TOUR#') and '#GROUP#' in audience:
        group = audience.split('#')[-1]
        return _query_mgmt_tokens_for_group(group)

    return []


def _delete_stale_token(token: str) -> None:
    rider_table = dynamodb.Table(os.environ['RIDER_PUSH_DEVICE_TABLE'])
    mgmt_table = dynamodb.Table(os.environ['MGMT_PUSH_DEVICE_TABLE'])

    for row in _scan_all_items(rider_table):
        if row.get('token') == token:
            rider_table.delete_item(Key={'profileId': row['profileId'], 'token': row['token']})
    for row in _scan_all_items(mgmt_table):
        if row.get('token') == token or row.get('deviceToken') == token:
            mgmt_table.delete_item(Key={'cognitoSub': row['cognitoSub'], 'token': row['token']})


def _push(messages: List[Dict[str, Any]], rider: bool) -> None:
    if not messages:
        return

    token_param_name = os.environ['EXPO_TOKEN_PARAM_RIDER' if rider else 'EXPO_TOKEN_PARAM_MGMT']
    try:
        access_token = _get_ssm_parameter(token_param_name)
    except Exception as exc:
        logger.warning('expo token param missing/unavailable: %s (%s)', token_param_name, str(exc))
        return

    for i in range(0, len(messages), 100):
        batch = messages[i:i + 100]
        payload = json.dumps(batch).encode('utf-8')
        request = urllib.request.Request(
            url='https://exp.host/--/api/v2/push/send',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Authorization': 'Bearer ' + access_token,
            },
            method='POST',
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode('utf-8'))
            tickets = body.get('data', [])
            for idx, ticket in enumerate(tickets):
                if ticket.get('status') == 'error' and (ticket.get('details') or {}).get('error') == 'DeviceNotRegistered':
                    bad_token = batch[idx].get('to')
                    if bad_token:
                        _delete_stale_token(bad_token)


def lambda_handler(event, context):
    log_event(logger, event)
    records = event.get('Records', [])

    rider_messages: List[Dict[str, Any]] = []
    mgmt_messages: List[Dict[str, Any]] = []

    for record in records:
        if record.get('eventName') != 'INSERT':
            continue
        new_image = (record.get('dynamodb') or {}).get('NewImage')
        if not new_image:
            continue

        item = _deserialize_image(new_image)
        if _is_state_item(item) or not item.get('push'):
            continue

        tokens = _resolve_tokens(item)
        if not tokens:
            continue

        message_template = {
            'title': item.get('title', ''),
            'body': item.get('body', ''),
            'sound': 'default',
            'priority': 'high' if item.get('priority') == 'URGENT' else 'default',
            'channelId': item.get('androidChannel', 'general'),
            'collapseId': item.get('notificationId'),
            'data': {
                'notificationId': item.get('notificationId'),
                'tourId': item.get('tourId'),
                'target': item.get('target', {}),
            },
        }

        target_bucket = rider_messages if str(item.get('audience', '')).startswith(('PROFILE#', 'APP#RIDER', 'TOUR#')) else mgmt_messages
        for token in set(tokens):
            target_bucket.append({**message_template, 'to': token})

    _push(rider_messages, rider=True)
    _push(mgmt_messages, rider=False)

    return {'processed': len(records), 'riderMessages': len(rider_messages), 'mgmtMessages': len(mgmt_messages)}
