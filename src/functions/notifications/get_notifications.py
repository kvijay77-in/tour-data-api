import sys

import os

from botocore.exceptions import BotoCoreError, ClientError

from notification_common import (
    archive_read_items_for_audience,
    dedupe_notifications,
    get_archive_after_read_hours,
    get_jwt_claim,
    get_profile_id_for_rider,
    get_rider_tour_rows,
    get_state_key,
    get_state_row,
    get_user_groups,
    list_active_tours,
    normalize_notification_item,
    own_table_for_scope,
    parse_limit,
    query_audience_items,
    query_audience_items_from_archive,
)
from logger import get_logger, log_event
from response import bad_request_response, success_response
from handler_utils import api_handler

sys.path.insert(0, '/opt/python')

logger = get_logger(__name__)


def _build_rider_audiences(profile_id, tour_rows):
    return sorted({'APP#RIDER', f'PROFILE#{profile_id}'})


def _fetch_tour_items_for_rider(tour_rows, since, limit):
    items = []
    stack_name = os.environ.get('STACK_NAME')
    for row in tour_rows:
        tour_id = row.get('tourId')
        rider_id = row.get('riderId')
        if not tour_id:
            continue
        table_name = f'{stack_name}-Notification-{tour_id}'
        audiences = [f'TOUR#{tour_id}#ALL', f'TOUR#{tour_id}#APP#RIDER']
        audiences.append(f'TOUR#{tour_id}#APPLICANTS')
        status = row.get('status')
        if status:
            audiences.append(f'TOUR#{tour_id}#STATUS#{status}')
        if rider_id:
            audiences.append(f'TOUR#{tour_id}#RIDER#{rider_id}')
        for audience in audiences:
            try:
                items.extend(query_audience_items(table_name, audience, since, limit))
                items.extend(query_audience_items_from_archive(table_name, audience, since, limit))
            except (ClientError, BotoCoreError) as exc:
                logger.warning('Failed to query rider tour notification table %s audience=%s: %s', table_name, audience, str(exc))
                continue
    return items


def _fetch_tour_items_for_mgmt(groups, since, limit):
    items = []
    stack_name = os.environ.get('STACK_NAME')
    for tour_id in list_active_tours():
        table_name = f'{stack_name}-Notification-{tour_id}'
        audiences = [f'TOUR#{tour_id}#ALL', f'TOUR#{tour_id}#APP#MGMT']
        for group in groups:
            audiences.append(f'TOUR#{tour_id}#GROUP#{group}')
        for audience in audiences:
            try:
                items.extend(query_audience_items(table_name, audience, since, limit))
                items.extend(query_audience_items_from_archive(table_name, audience, since, limit))
            except (ClientError, BotoCoreError) as exc:
                logger.warning('Failed to query mgmt tour notification table %s audience=%s: %s', table_name, audience, str(exc))
                continue
    return items


@api_handler('Failed to list notifications')
def lambda_handler(event, context):
    log_event(logger, event)
    query = event.get('queryStringParameters') or {}
    since = query.get('since')
    try:
        limit = parse_limit(query.get('limit'), default=50, max_value=200)
    except ValueError as exc:
        return bad_request_response(str(exc))

    scope = os.environ.get('NOTIFICATION_SCOPE', 'mgmt')
    own_table = own_table_for_scope(scope)

    items = []
    if scope == 'rider':
        profile_id = get_profile_id_for_rider(event)
        if not profile_id:
            return success_response({'items': [], 'unreadCount': 0})
        tour_rows = get_rider_tour_rows(profile_id)
        state_key = get_state_key(scope, profile_id)
        audiences = _build_rider_audiences(profile_id, tour_rows)
        for audience in audiences:
            items.extend(query_audience_items(own_table, audience, since, limit))
        items.extend(_fetch_tour_items_for_rider(tour_rows, since, limit))
    else:
        sub = get_jwt_claim(event, 'sub')
        groups = get_user_groups(event)
        state_key = get_state_key(scope, sub)
        audiences = ['APP#MGMT', f'USER#{sub}', *[f'GROUP#{g}' for g in groups]]
        for audience in audiences:
            items.extend(query_audience_items(own_table, audience, since, limit))
        items.extend(_fetch_tour_items_for_mgmt(groups, since, limit))

    state = get_state_row(own_table, state_key)
    last_read_at = state.get('lastReadAt') if state else None
    if last_read_at:
        archive_after_hours = get_archive_after_read_hours()
        if scope == 'rider':
            for row in tour_rows:
                tour_id = row.get('tourId')
                rider_id = row.get('riderId')
                if not tour_id:
                    continue
                table_name = f'{os.environ.get("STACK_NAME")}-Notification-{tour_id}'
                archive_read_items_for_audience(table_name, f'TOUR#{tour_id}#ALL', last_read_at, archive_after_hours)
                archive_read_items_for_audience(table_name, f'TOUR#{tour_id}#APP#RIDER', last_read_at, archive_after_hours)
                archive_read_items_for_audience(table_name, f'TOUR#{tour_id}#APPLICANTS', last_read_at, archive_after_hours)
                status = row.get('status')
                if status:
                    archive_read_items_for_audience(table_name, f'TOUR#{tour_id}#STATUS#{status}', last_read_at, archive_after_hours)
                if rider_id:
                    archive_read_items_for_audience(table_name, f'TOUR#{tour_id}#RIDER#{rider_id}', last_read_at, archive_after_hours)
        else:
            for tour_id in list_active_tours():
                table_name = f'{os.environ.get("STACK_NAME")}-Notification-{tour_id}'
                archive_read_items_for_audience(table_name, f'TOUR#{tour_id}#ALL', last_read_at, archive_after_hours)
                archive_read_items_for_audience(table_name, f'TOUR#{tour_id}#APP#MGMT', last_read_at, archive_after_hours)
                for group in groups:
                    archive_read_items_for_audience(table_name, f'TOUR#{tour_id}#GROUP#{group}', last_read_at, archive_after_hours)

    normalized = [normalize_notification_item(row, last_read_at) for row in items]
    deduped = dedupe_notifications(normalized)
    merged = deduped[:limit]
    unread_count = sum(1 for row in deduped if not row.get('isRead'))

    return success_response({'items': merged, 'unreadCount': unread_count})
