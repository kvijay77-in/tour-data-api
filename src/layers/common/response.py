"""
Response utilities for consistent API responses
"""

import json
from typing import Any, Dict, Optional
from decimal import Decimal

from models import utc_now_iso


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types from DynamoDB"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def success_response(data: Any, status_code: int = 200) -> Dict[str, Any]:
    """
    Create a successful API response
    
    Args:
        data: Response data
        status_code: HTTP status code (default: 200)
    
    Returns:
        API Gateway proxy response dict
    """
    body = {
        "success": True,
        "data": data,
        "timestamp": utc_now_iso()
    }
    
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS"
        },
        "body": json.dumps(body, cls=DecimalEncoder)
    }


def error_response(
    error_code: str,
    message: str,
    status_code: int = 400,
    details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create an error API response
    
    Args:
        error_code: Error code identifier
        message: Human-readable error message
        status_code: HTTP status code (default: 400)
        details: Additional error details (optional)
    
    Returns:
        API Gateway proxy response dict
    """
    body = {
        "success": False,
        "error": {
            "code": error_code,
            "message": message
        },
        "timestamp": utc_now_iso()
    }
    
    if details:
        body["error"]["details"] = details
    
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS"
        },
        "body": json.dumps(body)
    }


# Common error responses

def not_found_response(resource: str, identifier: str) -> Dict[str, Any]:
    """Create a 404 not found response"""
    return error_response(
        error_code=f"{resource.upper()}_NOT_FOUND",
        message=f"{resource} '{identifier}' not found",
        status_code=404
    )


def bad_request_response(message: str, details: Optional[Dict] = None) -> Dict[str, Any]:
    """Create a 400 bad request response"""
    return error_response(
        error_code="BAD_REQUEST",
        message=message,
        status_code=400,
        details=details
    )


def validation_error_response(message: str, details: Optional[Dict] = None) -> Dict[str, Any]:
    """Create a 400 validation error response"""
    return error_response(
        error_code="VALIDATION_ERROR",
        message=message,
        status_code=400,
        details=details
    )


def unauthorized_response(message: str = "Unauthorized") -> Dict[str, Any]:
    """Create a 401 unauthorized response"""
    return error_response(
        error_code="UNAUTHORIZED",
        message=message,
        status_code=401
    )


def forbidden_response(message: str = "Forbidden") -> Dict[str, Any]:
    """Create a 403 forbidden response"""
    return error_response(
        error_code="FORBIDDEN",
        message=message,
        status_code=403
    )


def conflict_response(
    message: str,
    error_code: str = "CONFLICT",
    details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create a 409 conflict response
    
    Args:
        message: Human-readable error message
        error_code: Specific error code (default: CONFLICT)
        details: Additional error details (optional)
    """
    return error_response(
        error_code=error_code,
        message=message,
        status_code=409,
        details=details
    )


def not_modified_response() -> Dict[str, Any]:
    """Create a 304 Not Modified response (no body)"""
    return {
        "statusCode": 304,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,If-None-Match",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS"
        },
        "body": ""
    }


def internal_error_response(message: str = "Internal server error") -> Dict[str, Any]:
    """Create a 500 internal server error response"""
    return error_response(
        error_code="INTERNAL_ERROR",
        message=message,
        status_code=500
    )
