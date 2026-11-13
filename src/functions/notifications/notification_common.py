"""Notification API shared helpers."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError

from dynamodb_utils import get_item, get_table
from logger import get_logger
from models import utc_now_iso
from response import bad_request_response

logger = get_logger(__name__)
_NOTIFICATION_ARCHIVE_CFG_CACHE: dict[str, tuple[float, int]] = {}
DEFAULT_ARCHIVE_AFTER_READ_HOURS = 48


def get_jwt_claim(event: Dict[str, Any], claim: str, default: str = "") -> str:
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
        .get(claim, default)
    )


def get_user_groups(event: Dict[str, Any]) -> List[str]:
    groups_raw = get_jwt_claim(event, "cognito:groups", "")
    if isinstance(groups_raw, list):
        return [str(v).strip() for v in groups_raw if str(v).strip()]
    if not groups_raw:
        return []
    return [g.strip() for g in str(groups_raw).split(",") if g.strip()]


def get_profile_id_for_rider(event: Dict[str, Any]) -> Optional[str]:
    cognito_username = get_jwt_claim(event, "cognito:username") or get_jwt_claim(
        event, "username"
    )
    if not cognito_username:
        return None
    mapping = get_item(
        "RIDER_COGNITO_USER_TABLE", {"cognitoUserName": cognito_username}
    )
    return mapping.get("profileId") if mapping else None


def parse_json_body(event: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON in request body") from exc


def parse_limit(value: Optional[str], default: int = 50, max_value: int = 200) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if parsed <= 0 or parsed > max_value:
        raise ValueError(f"limit must be between 1 and {max_value}") from exc
    return parsed


def parse_iso_datetime(value: str, field: str) -> datetime:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid ISO datetime") from exc


def get_state_row(table_name: str, state_key: str) -> Optional[Dict[str, Any]]:
    table = boto3.resource("dynamodb").Table(table_name)
    response = table.get_item(Key={"audience": state_key, "sk": "STATE"})
    return response.get("Item")


def set_state_row(table_name: str, state_key: str, read_at: str) -> None:
    table = boto3.resource("dynamodb").Table(table_name)
    table.put_item(
        Item={
            "audience": state_key,
            "sk": "STATE",
            "lastReadAt": read_at,
            "updatedAt": utc_now_iso(),
        }
    )


def query_audience_items(
    table_name: str, audience: str, since: Optional[str], limit: int
) -> List[Dict[str, Any]]:
    table = boto3.resource("dynamodb").Table(table_name)
    key_expr = Key("audience").eq(audience)
    if since:
        key_expr = key_expr & Key("sk").gt(f"{since}#")
    kwargs: Dict[str, Any] = {
        "KeyConditionExpression": key_expr,
        "ScanIndexForward": False,
        "Limit": limit,
    }
    resp = table.query(**kwargs)
    return resp.get("Items", [])


def query_audience_items_from_archive(
    table_name: str, audience: str, since: Optional[str], limit: int
) -> List[Dict[str, Any]]:
    archive_table_name = to_archive_table_name(table_name)
    if not archive_table_name:
        return []
    try:
        return query_audience_items(archive_table_name, audience, since, limit)
    except (ClientError, BotoCoreError):
        return []


def list_active_tours() -> List[str]:
    table = get_table("TOUR_MASTER_TABLE")
    response = table.query(
        IndexName="StatusIndex",
        KeyConditionExpression=Key("status").eq("ACTIVE"),
    )
    return [item["tourId"] for item in response.get("Items", []) if item.get("tourId")]


def get_rider_tour_rows(profile_id: str) -> List[Dict[str, Any]]:
    table = get_table("RIDER_TOURS_TABLE")
    response = table.query(KeyConditionExpression=Key("profileId").eq(profile_id))
    return response.get("Items", [])


def get_state_key(scope: str, identity: str) -> str:
    return f"STATE#{identity}" if not identity.startswith("STATE#") else identity


def to_archive_table_name(table_name: str) -> Optional[str]:
    marker = "-Notification-"
    if marker not in table_name:
        return None
    return table_name.replace(marker, "-NotificationArchive-")


def get_archive_after_read_hours() -> int:
    now = time.time()
    cached = _NOTIFICATION_ARCHIVE_CFG_CACHE.get("value")
    if cached and now - cached[0] < 300:
        return cached[1]
    value = DEFAULT_ARCHIVE_AFTER_READ_HOURS
    try:
        config = (
            get_item(
                "APP_CONFIG_TABLE", {"configType": "NOTIFICATION", "configId": "LIMITS"}
            )
            or {}
        )
        cfg = config.get("config") or {}
        parsed = int(cfg.get("archiveAfterReadHours", DEFAULT_ARCHIVE_AFTER_READ_HOURS))
        if parsed > 0:
            value = parsed
    except (ClientError, BotoCoreError, ValueError, TypeError, AttributeError):
        value = DEFAULT_ARCHIVE_AFTER_READ_HOURS
    _NOTIFICATION_ARCHIVE_CFG_CACHE["value"] = (now, value)
    return value


def archive_read_items_for_audience(
    table_name: str,
    audience: str,
    last_read_at: Optional[str],
    archive_after_hours: int,
    limit: int = 50,
) -> int:
    archive_table_name = to_archive_table_name(table_name)
    if not archive_table_name or not last_read_at:
        return 0
    table = boto3.resource("dynamodb").Table(table_name)
    archive_table = boto3.resource("dynamodb").Table(archive_table_name)
    key_expr = Key("audience").eq(audience)
    try:
        rows = table.query(
            KeyConditionExpression=key_expr,
            ScanIndexForward=True,
            Limit=max(1, limit),
        ).get("Items", [])
    except (ClientError, BotoCoreError) as exc:
        logger.warning(
            "Archive query failed table=%s audience=%s: %s",
            table_name,
            audience,
            str(exc),
        )
        return 0
    moved = 0
    cutoff = datetime.now(timezone.utc).timestamp() - max(1, archive_after_hours) * 3600
    for row in rows:
        created_at = row.get("createdAt") or str(row.get("sk", "")).split("#", 1)[0]
        if not created_at or created_at > last_read_at:
            continue
        try:
            created_ts = parse_iso_datetime(created_at, "createdAt").timestamp()
        except ValueError:
            continue
        if created_ts > cutoff:
            continue
        try:
            archive_table.put_item(Item=row)
            table.delete_item(Key={"audience": row["audience"], "sk": row["sk"]})
        except (ClientError, BotoCoreError) as exc:
            logger.warning(
                "Archive move failed table=%s audience=%s: %s",
                table_name,
                audience,
                str(exc),
            )
            continue
        moved += 1
    return moved


def normalize_notification_item(
    item: Dict[str, Any], last_read_at: Optional[str]
) -> Dict[str, Any]:
    created_at = item.get("createdAt") or str(item.get("sk", "")).split("#", 1)[0]
    return {
        "notificationId": item.get("notificationId"),
        "ruleId": item.get("ruleId"),
        "title": item.get("title", ""),
        "body": item.get("body", ""),
        "priority": item.get("priority", "NORMAL"),
        "target": item.get("target", {}),
        "tourId": item.get("tourId"),
        "createdAt": created_at,
        "isRead": bool(last_read_at and created_at and created_at <= last_read_at),
    }


def dedupe_notifications(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: Dict[str, Dict[str, Any]] = {}
    for item in items:
        notification_id = item.get("notificationId")
        if not notification_id:
            continue
        current = deduped.get(notification_id)
        if current is None or (item.get("createdAt") or "") > (
            current.get("createdAt") or ""
        ):
            deduped[notification_id] = item
    return sorted(
        deduped.values(), key=lambda row: row.get("createdAt", ""), reverse=True
    )


def own_table_for_scope(scope: str) -> str:
    if scope == "rider":
        return os.environ["RIDER_NOTIFICATION_TABLE"]
    return os.environ["MGMT_NOTIFICATION_TABLE"]


def split_base_token(token_key: str) -> str:
    if token_key.startswith("GROUP#"):
        parts = token_key.split("#")
        return parts[-1]
    return token_key


def as_bad_request(exc: Exception):
    return bad_request_response(str(exc))
