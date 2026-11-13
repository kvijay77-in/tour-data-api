"""
DynamoDB utility functions

Supports two table resolution patterns:
1. Shared tables: resolved via environment variable (table_name_env pattern)
2. Tour-specific tables: resolved dynamically using {STACK_NAME}-{TableType}-{tourId}
"""

import os
from typing import Dict, Any, Optional, List
from decimal import Decimal
import boto3
from botocore.exceptions import ClientError

# Initialize DynamoDB resource (reused across Lambda invocations)
dynamodb = boto3.resource("dynamodb")

# Table references (loaded from environment variables or cached by name)
TABLES = {}


def _normalize_dynamodb_numbers(value: Any) -> Any:
    """Recursively convert Python floats to Decimal for boto3 DynamoDB writes."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _normalize_dynamodb_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_dynamodb_numbers(item) for item in value]
    return value


def get_table(table_name_env: str):
    """
    Get DynamoDB table resource for shared tables (resolved via environment variable)

    Args:
        table_name_env: Environment variable name containing table name

    Returns:
        DynamoDB table resource
    """
    if table_name_env not in TABLES:
        table_name = os.environ.get(table_name_env)
        if not table_name:
            raise ValueError(f"Environment variable {table_name_env} not set")
        TABLES[table_name_env] = dynamodb.Table(table_name)

    return TABLES[table_name_env]


def get_tour_table_name(table_type: str, tour_id: str) -> str:
    """
    Build the full DynamoDB table name for a tour-specific table.

    Pattern: {STACK_NAME}-{TableType}-{tourId}

    Args:
        table_type: Table type (TourRider, Ride, CheckIn, User)
        tour_id: Tour identifier (e.g., TOT-2026)

    Returns:
        Full table name (e.g., dev-Ride-TOT-2026)
    """
    stack_name = os.environ.get("STACK_NAME")
    if not stack_name:
        raise ValueError("Environment variable STACK_NAME not set")
    return f"{stack_name}-{table_type}-{tour_id}"


def get_tour_table(table_type: str, tour_id: str):
    """
    Get DynamoDB table resource for a tour-specific table (with caching).

    Args:
        table_type: Table type (TourRider, Ride, CheckIn, User)
        tour_id: Tour identifier (e.g., TOT-2026)

    Returns:
        DynamoDB table resource
    """
    table_name = get_tour_table_name(table_type, tour_id)
    cache_key = f"tour:{table_name}"

    if cache_key not in TABLES:
        TABLES[cache_key] = dynamodb.Table(table_name)

    return TABLES[cache_key]


def get_item(table_name_env: str, key: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Get item from a shared DynamoDB table (resolved via env var)

    Args:
        table_name_env: Environment variable name containing table name
        key: Primary key dictionary

    Returns:
        Item dictionary or None if not found
    """
    table = get_table(table_name_env)

    try:
        response = table.get_item(Key=key)
        return response.get("Item")
    except ClientError as e:
        print(f"Error getting item from {table_name_env}: {e}")
        raise


def get_tour_item(
    table_type: str, tour_id: str, key: Dict[str, str]
) -> Optional[Dict[str, Any]]:
    """
    Get item from a tour-specific DynamoDB table

    Args:
        table_type: Table type (TourRider, Ride, CheckIn, User)
        tour_id: Tour identifier
        key: Primary key dictionary

    Returns:
        Item dictionary or None if not found
    """
    table = get_tour_table(table_type, tour_id)

    try:
        response = table.get_item(Key=key)
        return response.get("Item")
    except ClientError as e:
        print(f"Error getting item from {table_type}-{tour_id}: {e}")
        raise


def put_item(
    table_name_env: str,
    item: Dict[str, Any],
    condition_expression: Optional[str] = None,
    expression_values: Optional[Dict[str, Any]] = None,
    expression_names: Optional[Dict[str, str]] = None,
) -> None:
    """
    Put item into a shared DynamoDB table (resolved via env var)

    Args:
        table_name_env: Environment variable name containing table name
        item: Item dictionary to store
    """
    table = get_table(table_name_env)

    try:
        kwargs = {"Item": _normalize_dynamodb_numbers(item)}
        if condition_expression:
            kwargs["ConditionExpression"] = condition_expression
        if expression_values:
            kwargs["ExpressionAttributeValues"] = _normalize_dynamodb_numbers(
                expression_values
            )
        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names

        table.put_item(**kwargs)
    except ClientError as e:
        print(f"Error putting item to {table_name_env}: {e}")
        raise


def put_tour_item(
    table_type: str,
    tour_id: str,
    item: Dict[str, Any],
    condition_expression: Optional[str] = None,
    expression_values: Optional[Dict[str, Any]] = None,
    expression_names: Optional[Dict[str, str]] = None,
) -> None:
    """
    Put item into a tour-specific DynamoDB table

    Args:
        table_type: Table type (TourRider, Ride, CheckIn, User)
        tour_id: Tour identifier
        item: Item dictionary to store
    """
    table = get_tour_table(table_type, tour_id)

    try:
        kwargs = {"Item": _normalize_dynamodb_numbers(item)}
        if condition_expression:
            kwargs["ConditionExpression"] = condition_expression
        if expression_values:
            kwargs["ExpressionAttributeValues"] = _normalize_dynamodb_numbers(
                expression_values
            )
        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names

        table.put_item(**kwargs)
    except ClientError as e:
        print(f"Error putting item to {table_type}-{tour_id}: {e}")
        raise


def update_item(
    table_name_env: str,
    key: Dict[str, str],
    update_expression: str,
    expression_values: Dict[str, Any],
    expression_names: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Update item in a shared DynamoDB table (resolved via env var)
    """
    table = get_table(table_name_env)
    return _do_update_item(
        table, key, update_expression, expression_values, expression_names
    )


def update_tour_item(
    table_type: str,
    tour_id: str,
    key: Dict[str, str],
    update_expression: str,
    expression_values: Dict[str, Any],
    expression_names: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Update item in a tour-specific DynamoDB table
    """
    table = get_tour_table(table_type, tour_id)
    return _do_update_item(
        table, key, update_expression, expression_values, expression_names
    )


def _do_update_item(
    table,
    key: Dict[str, str],
    update_expression: str,
    expression_values: Dict[str, Any],
    expression_names: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Internal helper for update_item operations"""
    try:
        kwargs = {
            "Key": key,
            "UpdateExpression": update_expression,
            "ExpressionAttributeValues": _normalize_dynamodb_numbers(expression_values),
            "ReturnValues": "ALL_NEW",
        }

        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names

        response = table.update_item(**kwargs)
        return response.get("Attributes", {})
    except ClientError as e:
        print(f"Error updating item: {e}")
        raise


def query_items(
    table_name_env: str,
    key_condition_expression: str,
    expression_values: Dict[str, Any],
    index_name: Optional[str] = None,
    filter_expression: Optional[str] = None,
    expression_names: Optional[Dict[str, str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Query items from a shared DynamoDB table (resolved via env var)
    """
    table = get_table(table_name_env)
    return _do_query_items(
        table,
        key_condition_expression,
        expression_values,
        index_name,
        filter_expression,
        expression_names,
        limit,
    )


def query_tour_items(
    table_type: str,
    tour_id: str,
    key_condition_expression: str,
    expression_values: Dict[str, Any],
    index_name: Optional[str] = None,
    filter_expression: Optional[str] = None,
    expression_names: Optional[Dict[str, str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Query items from a tour-specific DynamoDB table
    """
    table = get_tour_table(table_type, tour_id)
    return _do_query_items(
        table,
        key_condition_expression,
        expression_values,
        index_name,
        filter_expression,
        expression_names,
        limit,
    )


def _do_query_items(
    table,
    key_condition_expression: str,
    expression_values: Dict[str, Any],
    index_name: Optional[str] = None,
    filter_expression: Optional[str] = None,
    expression_names: Optional[Dict[str, str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Internal helper for query operations"""
    try:
        kwargs = {
            "KeyConditionExpression": key_condition_expression,
            "ExpressionAttributeValues": expression_values,
        }

        if index_name:
            kwargs["IndexName"] = index_name

        if filter_expression:
            kwargs["FilterExpression"] = filter_expression

        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names

        if limit:
            kwargs["Limit"] = limit

        response = table.query(**kwargs)
        items = response.get("Items", [])

        # Handle pagination if needed
        while "LastEvaluatedKey" in response:
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = table.query(**kwargs)
            items.extend(response.get("Items", []))

        return items
    except ClientError as e:
        print(f"Error querying items: {e}")
        raise


def scan_items(
    table_name_env: str,
    filter_expression: Optional[str] = None,
    expression_values: Optional[Dict[str, Any]] = None,
    expression_names: Optional[Dict[str, str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Scan items from a shared DynamoDB table (resolved via env var).
    Warning: Scan operations are expensive. Use query when possible.
    """
    table = get_table(table_name_env)
    return _do_scan_items(
        table, filter_expression, expression_values, expression_names, limit
    )


def scan_tour_items(
    table_type: str,
    tour_id: str,
    filter_expression: Optional[str] = None,
    expression_values: Optional[Dict[str, Any]] = None,
    expression_names: Optional[Dict[str, str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Scan items from a tour-specific DynamoDB table.
    Warning: Scan operations are expensive. Use query when possible.
    """
    table = get_tour_table(table_type, tour_id)
    return _do_scan_items(
        table, filter_expression, expression_values, expression_names, limit
    )


def _do_scan_items(
    table,
    filter_expression: Optional[str] = None,
    expression_values: Optional[Dict[str, Any]] = None,
    expression_names: Optional[Dict[str, str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Internal helper for scan operations"""
    try:
        kwargs = {}

        if filter_expression:
            kwargs["FilterExpression"] = filter_expression

        if expression_values:
            kwargs["ExpressionAttributeValues"] = expression_values

        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names

        if limit:
            kwargs["Limit"] = limit

        response = table.scan(**kwargs)
        items = response.get("Items", [])

        # Handle pagination if needed
        while "LastEvaluatedKey" in response and (not limit or len(items) < limit):
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = table.scan(**kwargs)
            items.extend(response.get("Items", []))

        return items
    except ClientError as e:
        print(f"Error scanning items: {e}")
        raise


def batch_get_items(
    table_name_env: str, keys: List[Dict[str, str]]
) -> List[Dict[str, Any]]:
    """
    Batch get items from a shared DynamoDB table (resolved via env var)
    """
    if not keys:
        return []

    table_name = os.environ.get(table_name_env)
    if not table_name:
        raise ValueError(f"Environment variable {table_name_env} not set")

    return _do_batch_get_items(table_name, keys)


def batch_get_tour_items(
    table_type: str, tour_id: str, keys: List[Dict[str, str]]
) -> List[Dict[str, Any]]:
    """
    Batch get items from a tour-specific DynamoDB table
    """
    if not keys:
        return []

    table_name = get_tour_table_name(table_type, tour_id)
    return _do_batch_get_items(table_name, keys)


def _do_batch_get_items(
    table_name: str, keys: List[Dict[str, str]]
) -> List[Dict[str, Any]]:
    """Internal helper for batch get operations"""
    try:
        batch_size = 100
        all_items = []

        for i in range(0, len(keys), batch_size):
            batch_keys = keys[i : i + batch_size]

            response = dynamodb.batch_get_item(
                RequestItems={table_name: {"Keys": batch_keys}}
            )

            all_items.extend(response["Responses"].get(table_name, []))

            # Handle unprocessed keys
            while response.get("UnprocessedKeys"):
                response = dynamodb.batch_get_item(
                    RequestItems=response["UnprocessedKeys"]
                )
                all_items.extend(response["Responses"].get(table_name, []))

        return all_items
    except ClientError as e:
        print(f"Error batch getting items from {table_name}: {e}")
        raise
