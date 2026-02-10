"""
DynamoDB utility functions
"""

import os
import boto3
from typing import Dict, Any, Optional, List
from botocore.exceptions import ClientError


# Initialize DynamoDB resource (reused across Lambda invocations)
dynamodb = boto3.resource('dynamodb')

# Table references (loaded from environment variables)
TABLES = {}


def get_table(table_name_env: str):
    """
    Get DynamoDB table resource (with caching)
    
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


def get_item(table_name_env: str, key: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Get item from DynamoDB table
    
    Args:
        table_name_env: Environment variable name containing table name
        key: Primary key dictionary
    
    Returns:
        Item dictionary or None if not found
    """
    table = get_table(table_name_env)
    
    try:
        response = table.get_item(Key=key)
        return response.get('Item')
    except ClientError as e:
        print(f"Error getting item from {table_name_env}: {e}")
        raise


def put_item(table_name_env: str, item: Dict[str, Any]) -> None:
    """
    Put item into DynamoDB table
    
    Args:
        table_name_env: Environment variable name containing table name
        item: Item dictionary to store
    """
    table = get_table(table_name_env)
    
    try:
        table.put_item(Item=item)
    except ClientError as e:
        print(f"Error putting item to {table_name_env}: {e}")
        raise


def update_item(
    table_name_env: str,
    key: Dict[str, str],
    update_expression: str,
    expression_values: Dict[str, Any],
    expression_names: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Update item in DynamoDB table
    
    Args:
        table_name_env: Environment variable name containing table name
        key: Primary key dictionary
        update_expression: DynamoDB update expression
        expression_values: Expression attribute values
        expression_names: Expression attribute names (optional)
    
    Returns:
        Updated item attributes
    """
    table = get_table(table_name_env)
    
    try:
        kwargs = {
            'Key': key,
            'UpdateExpression': update_expression,
            'ExpressionAttributeValues': expression_values,
            'ReturnValues': 'ALL_NEW'
        }
        
        if expression_names:
            kwargs['ExpressionAttributeNames'] = expression_names
        
        response = table.update_item(**kwargs)
        return response.get('Attributes', {})
    except ClientError as e:
        print(f"Error updating item in {table_name_env}: {e}")
        raise


def query_items(
    table_name_env: str,
    key_condition_expression: str,
    expression_values: Dict[str, Any],
    index_name: Optional[str] = None,
    filter_expression: Optional[str] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Query items from DynamoDB table
    
    Args:
        table_name_env: Environment variable name containing table name
        key_condition_expression: Key condition expression
        expression_values: Expression attribute values
        index_name: GSI name (optional)
        filter_expression: Filter expression (optional)
        limit: Maximum number of items to return (optional)
    
    Returns:
        List of items
    """
    table = get_table(table_name_env)
    
    try:
        kwargs = {
            'KeyConditionExpression': key_condition_expression,
            'ExpressionAttributeValues': expression_values
        }
        
        if index_name:
            kwargs['IndexName'] = index_name
        
        if filter_expression:
            kwargs['FilterExpression'] = filter_expression
        
        if limit:
            kwargs['Limit'] = limit
        
        response = table.query(**kwargs)
        items = response.get('Items', [])
        
        # Handle pagination if needed
        while 'LastEvaluatedKey' in response:
            kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = table.query(**kwargs)
            items.extend(response.get('Items', []))
        
        return items
    except ClientError as e:
        print(f"Error querying items from {table_name_env}: {e}")
        raise


def scan_items(
    table_name_env: str,
    filter_expression: Optional[str] = None,
    expression_values: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Scan items from DynamoDB table
    
    Warning: Scan operations are expensive. Use query when possible.
    
    Args:
        table_name_env: Environment variable name containing table name
        filter_expression: Filter expression (optional)
        expression_values: Expression attribute values (optional)
        limit: Maximum number of items to return (optional)
    
    Returns:
        List of items
    """
    table = get_table(table_name_env)
    
    try:
        kwargs = {}
        
        if filter_expression:
            kwargs['FilterExpression'] = filter_expression
        
        if expression_values:
            kwargs['ExpressionAttributeValues'] = expression_values
        
        if limit:
            kwargs['Limit'] = limit
        
        response = table.scan(**kwargs)
        items = response.get('Items', [])
        
        # Handle pagination if needed
        while 'LastEvaluatedKey' in response and (not limit or len(items) < limit):
            kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = table.scan(**kwargs)
            items.extend(response.get('Items', []))
        
        return items
    except ClientError as e:
        print(f"Error scanning items from {table_name_env}: {e}")
        raise


def batch_get_items(table_name_env: str, keys: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Batch get items from DynamoDB table
    
    Args:
        table_name_env: Environment variable name containing table name
        keys: List of primary key dictionaries
    
    Returns:
        List of items
    """
    if not keys:
        return []
    
    table = get_table(table_name_env)
    table_name = os.environ.get(table_name_env)
    
    try:
        # DynamoDB batch_get_item has a limit of 100 items
        batch_size = 100
        all_items = []
        
        for i in range(0, len(keys), batch_size):
            batch_keys = keys[i:i + batch_size]
            
            response = dynamodb.batch_get_item(
                RequestItems={
                    table_name: {
                        'Keys': batch_keys
                    }
                }
            )
            
            all_items.extend(response['Responses'].get(table_name, []))
            
            # Handle unprocessed keys
            while response.get('UnprocessedKeys'):
                response = dynamodb.batch_get_item(
                    RequestItems=response['UnprocessedKeys']
                )
                all_items.extend(response['Responses'].get(table_name, []))
        
        return all_items
    except ClientError as e:
        print(f"Error batch getting items from {table_name_env}: {e}")
        raise
