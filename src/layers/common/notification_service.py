"""Notification framework service helpers."""

from __future__ import annotations

import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from dynamodb_utils import dynamodb, get_item, get_tour_item
from logger import get_logger
from models import utc_now_iso

logger = get_logger(__name__)

RULE_CACHE_TTL_SECONDS = 300
_RULE_CACHE: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}

CATEGORY_VALUES = {"ANNOUNCEMENT", "ALERT", "PERSONAL", "SYSTEM"}
PRIORITY_VALUES = {"URGENT", "NORMAL"}
ANDROID_CHANNEL_VALUES = {"urgent", "general"}

AUDIENCE_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"^ALL$"),
    re.compile(r"^APP#(RIDER|MGMT)$"),
    re.compile(r"^PROFILE#[A-Za-z0-9_.\-]{1,100}$"),
    re.compile(r"^USER#[A-Za-z0-9\-]{1,80}$"),
    re.compile(r"^GROUP#[A-Za-z0-9_\-]{1,80}$"),
    re.compile(r"^TOUR#[A-Za-z0-9_.\-]{3,50}#STATUS#[A-Z_]{2,40}$"),
    re.compile(r"^TOUR#[A-Za-z0-9_.\-]{3,50}#APPLICANTS$"),
    re.compile(r"^TOUR#[A-Za-z0-9_.\-]{3,50}#ALL$"),
    re.compile(r"^TOUR#[A-Za-z0-9_.\-]{3,50}#APP#(RIDER|MGMT)$"),
    re.compile(r"^TOUR#[A-Za-z0-9_.\-]{3,50}#GROUP#[A-Za-z0-9_\-]{1,80}$"),
    re.compile(r"^TOUR#[A-Za-z0-9_.\-]{3,50}#RIDER#R[1-9]\d{0,2}$"),
)


class _SafeTemplateDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def validate_audience_expression(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return any(pattern.fullmatch(value) for pattern in AUDIENCE_PATTERNS)


def validate_audiences(audiences: Iterable[str]) -> List[str]:
    normalized = []
    for audience in audiences or []:
        if not validate_audience_expression(audience):
            raise ValueError(f"Invalid audience expression: {audience}")
        normalized.append(audience)
    if not normalized:
        raise ValueError("At least one audience expression is required")
    return normalized


def validate_rule_payload(payload: Dict[str, Any], partial: bool = False) -> Dict[str, Any]:
    required = [
        "ruleId",
        "enabled",
        "category",
        "audiences",
        "titleTemplate",
        "bodyTemplate",
        "push",
        "priority",
        "androidChannel",
        "target",
        "ttlHours",
        "allowOverride",
    ]

    if not partial:
        missing = [field for field in required if field not in payload]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

    validated = dict(payload)

    if "ruleId" in validated:
        rule_id = validated["ruleId"]
        if not isinstance(rule_id, str) or not re.fullmatch(r"[A-Z0-9_\-]{2,80}", rule_id):
            raise ValueError("ruleId must match [A-Z0-9_-]{2,80}")

    if "category" in validated and validated["category"] not in CATEGORY_VALUES:
        raise ValueError(f"category must be one of {sorted(CATEGORY_VALUES)}")

    if "audiences" in validated:
        validated["audiences"] = validate_audiences(validated["audiences"])

    if "priority" in validated and validated["priority"] not in PRIORITY_VALUES:
        raise ValueError(f"priority must be one of {sorted(PRIORITY_VALUES)}")

    if "androidChannel" in validated and validated["androidChannel"] not in ANDROID_CHANNEL_VALUES:
        raise ValueError(f"androidChannel must be one of {sorted(ANDROID_CHANNEL_VALUES)}")

    if "ttlHours" in validated:
        ttl_hours = validated["ttlHours"]
        if not isinstance(ttl_hours, int) or ttl_hours <= 0:
            raise ValueError("ttlHours must be a positive integer")

    if "target" in validated:
        target = validated["target"]
        if not isinstance(target, dict):
            raise ValueError("target must be an object")
        if not isinstance(target.get("screen"), str) or not target.get("screen"):
            raise ValueError("target.screen is required")
        param_keys = target.get("paramKeys", [])
        if not isinstance(param_keys, list) or any(not isinstance(v, str) for v in param_keys):
            raise ValueError("target.paramKeys must be a string array")

    if "quietHours" in validated and validated["quietHours"] is not None:
        quiet = validated["quietHours"]
        if not isinstance(quiet, dict):
            raise ValueError("quietHours must be an object")
        for field in ("from", "to", "tz"):
            if field not in quiet or not isinstance(quiet[field], str) or not quiet[field]:
                raise ValueError(f"quietHours.{field} is required")

    for bool_field in ("enabled", "push", "allowOverride"):
        if bool_field in validated and not isinstance(validated[bool_field], bool):
            raise ValueError(f"{bool_field} must be boolean")

    return validated


def _get_notification_rule_table_env() -> str:
    return os.environ.get("NOTIFICATION_RULE_TABLE", "")


def _load_rule(rule_id: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    cached = _RULE_CACHE.get(rule_id)
    if cached and now - cached[0] < RULE_CACHE_TTL_SECONDS:
        return cached[1]

    rule = None
    table_env = _get_notification_rule_table_env()
    if table_env:
        try:
            rule = get_item("NOTIFICATION_RULE_TABLE", {"ruleId": rule_id})
        except Exception as exc:  # pragma: no cover - safeguard path
            logger.warning("rule lookup failed: ruleId=%s error=%s", rule_id, str(exc))
            rule = None

    _RULE_CACHE[rule_id] = (now, rule)
    return rule


def _render_template(template: str, context: Optional[Dict[str, Any]]) -> str:
    if not isinstance(template, str):
        return ""
    values = context or {}
    safe_values = _SafeTemplateDict({key: "" if value is None else value for key, value in values.items()})
    try:
        return template.format_map(safe_values)
    except Exception:
        return template


def _extract_tour_id(expression: str) -> Optional[str]:
    if not expression.startswith("TOUR#"):
        return None
    parts = expression.split("#")
    return parts[1] if len(parts) > 1 else None


def _resolve_tour_rider_to_profile(audience: str) -> Optional[str]:
    # TOUR#{tourId}#RIDER#{riderId}
    parts = audience.split("#")
    if len(parts) != 4:
        return None
    tour_id = parts[1]
    rider_id = parts[3]
    try:
        rider = get_tour_item("TourRider", tour_id, {"riderId": rider_id})
    except Exception as exc:
        logger.warning("tour rider lookup failed: audience=%s error=%s", audience, str(exc))
        return None
    if not rider:
        return None
    return rider.get("profileId")


def _route_audience(audience: str) -> List[Tuple[str, str]]:
    # returns list[(table_name, audience_to_store)]
    rider_table = os.environ.get("RIDER_NOTIFICATION_TABLE")
    mgmt_table = os.environ.get("MGMT_NOTIFICATION_TABLE")

    if audience == "ALL":
        routes: List[Tuple[str, str]] = []
        if rider_table:
            routes.append((rider_table, "APP#RIDER"))
        if mgmt_table:
            routes.append((mgmt_table, "APP#MGMT"))
        return routes

    if audience.startswith("APP#RIDER") or audience.startswith("PROFILE#") or "#STATUS#" in audience or audience.endswith("#APPLICANTS"):
        return [(rider_table, audience)] if rider_table else []

    if audience.startswith("APP#MGMT") or audience.startswith("USER#") or audience.startswith("GROUP#"):
        return [(mgmt_table, audience)] if mgmt_table else []

    if "#RIDER#" in audience:
        profile_id = _resolve_tour_rider_to_profile(audience)
        if profile_id and rider_table:
            return [(rider_table, f"PROFILE#{profile_id}")]
        return []

    if audience.startswith("TOUR#"):
        tour_id = _extract_tour_id(audience)
        if not tour_id:
            return []
        table_name = f"{os.environ.get('STACK_NAME')}-Notification-{tour_id}"
        return [(table_name, audience)]

    return []


def _to_epoch_seconds(value: datetime) -> int:
    return int(value.timestamp())


def _build_notification_item(
    audience: str,
    notification_id: str,
    created_at: str,
    rule_id: str,
    rule: Dict[str, Any],
    title: str,
    body: str,
    tour_id: Optional[str],
    actor: Optional[str],
) -> Dict[str, Any]:
    ttl_hours = int(rule.get("ttlHours") or 24)
    expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    item: Dict[str, Any] = {
        "audience": audience,
        "sk": f"{created_at}#{notification_id}",
        "notificationId": notification_id,
        "ruleId": rule_id,
        "title": title,
        "body": body,
        "priority": rule.get("priority", "NORMAL"),
        "androidChannel": rule.get("androidChannel", "general"),
        "target": rule.get("target", {}),
        "createdBy": actor or "system",
        "push": bool(rule.get("push", False)),
        "createdAt": created_at,
        "expiresAt": _to_epoch_seconds(expires),
    }
    if tour_id:
        item["tourId"] = tour_id
    if rule.get("quietHours"):
        item["quietHours"] = rule["quietHours"]
    return item


def _batch_write(items_by_table: Dict[str, List[Dict[str, Any]]]) -> None:
    for table_name, items in items_by_table.items():
        if not table_name or not items:
            continue
        table = dynamodb.Table(table_name)
        with table.batch_writer() as batch:
            for item in items:
                batch.put_item(Item=item)


def notify(
    rule_id: str,
    tour_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    audience_override: Optional[List[str]] = None,
    actor: Optional[str] = None,
) -> Optional[str]:
    """Create notification inbox records for a rule. Never raises."""
    try:
        rule = _load_rule(rule_id)
        if not rule or not rule.get("enabled"):
            return None

        audiences = rule.get("audiences") or []
        if audience_override and rule.get("allowOverride"):
            audiences = audience_override

        rendered_context = dict(context or {})
        if tour_id and "tourId" not in rendered_context:
            rendered_context["tourId"] = tour_id

        validated_audiences = validate_audiences(audiences)
        notification_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        title = _render_template(rule.get("titleTemplate", ""), rendered_context)
        body = _render_template(rule.get("bodyTemplate", ""), rendered_context)

        items_by_table: Dict[str, List[Dict[str, Any]]] = {}
        for audience in validated_audiences:
            for table_name, audience_to_store in _route_audience(audience):
                item = _build_notification_item(
                    audience_to_store,
                    notification_id,
                    created_at,
                    rule_id,
                    rule,
                    title,
                    body,
                    tour_id,
                    actor,
                )
                items_by_table.setdefault(table_name, []).append(item)

        if not items_by_table:
            return None

        _batch_write(items_by_table)
        return notification_id
    except Exception as exc:  # never raise to caller
        logger.error(
            "notification_service.notify failed ruleId=%s tourId=%s error=%s",
            rule_id,
            tour_id,
            str(exc),
            exc_info=True,
        )
        return None
