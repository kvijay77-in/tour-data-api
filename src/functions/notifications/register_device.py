import sys

import os

import boto3
from boto3.dynamodb.conditions import Attr, Key

from notification_common import (
    get_jwt_claim,
    get_profile_id_for_rider,
    get_user_groups,
    parse_json_body,
)
from logger import get_logger, log_event
from response import bad_request_response, success_response
from handler_utils import api_handler
from models import utc_now_iso

sys.path.insert(0, "/opt/python")

logger = get_logger(__name__)
dynamodb = boto3.resource("dynamodb")


def _validate_platform(platform: str) -> str:
    if platform not in {"ios", "android"}:
        raise ValueError("platform must be one of: ios, android")
    return platform


def _scan_all_with_token(table, token: str):
    items = []
    kwargs = {"FilterExpression": Attr("token").eq(token)}
    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return items


@api_handler("Failed to register device")
def lambda_handler(event, context):
    try:
        log_event(logger, event)
        body = parse_json_body(event)
        token = body.get("token")
        if not token or not isinstance(token, str):
            return bad_request_response("token is required")
        try:
            platform = _validate_platform(body.get("platform"))
        except ValueError as exc:
            return bad_request_response(str(exc))

        scope = os.environ.get("NOTIFICATION_SCOPE", "mgmt")
        now = utc_now_iso()
        expires_at = int(__import__("time").time()) + (90 * 24 * 3600)

        if scope == "rider":
            profile_id = get_profile_id_for_rider(event)
            if not profile_id:
                return bad_request_response(
                    "Unable to resolve rider profileId from identity"
                )

            table = dynamodb.Table(os.environ["RIDER_PUSH_DEVICE_TABLE"])
            for item in _scan_all_with_token(table, token):
                if item.get("profileId") != profile_id:
                    table.delete_item(
                        Key={"profileId": item["profileId"], "token": item["token"]}
                    )

            table.put_item(
                Item={
                    "profileId": profile_id,
                    "token": token,
                    "platform": platform,
                    "updatedAt": now,
                    "expiresAt": expires_at,
                }
            )
        else:
            cognito_sub = get_jwt_claim(event, "sub")
            if not cognito_sub:
                return bad_request_response("Unable to resolve user identity")

            table = dynamodb.Table(os.environ["MGMT_PUSH_DEVICE_TABLE"])
            groups = get_user_groups(event)

            for item in _scan_all_with_token(table, token):
                if item.get("cognitoSub") != cognito_sub:
                    table.delete_item(
                        Key={"cognitoSub": item["cognitoSub"], "token": item["token"]}
                    )

            current_rows = table.query(
                KeyConditionExpression=Key("cognitoSub").eq(cognito_sub)
            ).get("Items", [])
            for row in current_rows:
                if row.get("itemType") != "GROUP":
                    continue
                row_group = str(row.get("groupKey", "")).replace("GROUP#", "", 1)
                if row_group not in groups:
                    table.delete_item(
                        Key={"cognitoSub": cognito_sub, "token": row["token"]}
                    )

            table.put_item(
                Item={
                    "cognitoSub": cognito_sub,
                    "token": token,
                    "platform": platform,
                    "groups": groups,
                    "itemType": "DEVICE",
                    "updatedAt": now,
                    "expiresAt": expires_at,
                }
            )

            for group in groups:
                table.put_item(
                    Item={
                        "cognitoSub": cognito_sub,
                        "token": f"GROUP#{group}#{token}",
                        "deviceToken": token,
                        "groupKey": f"GROUP#{group}",
                        "platform": platform,
                        "itemType": "GROUP",
                        "updatedAt": now,
                        "expiresAt": expires_at,
                    }
                )

        return success_response({"registered": True}, status_code=201)

    except ValueError as exc:
        return bad_request_response(str(exc))
