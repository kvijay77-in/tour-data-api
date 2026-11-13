"""
Unit tests for the api_handler error boundary in handler_utils.py
"""

import json
import sys

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

sys.path.insert(0, 'src/layers/common')

from handler_utils import api_handler  # noqa: E402  pylint: disable=wrong-import-position


def _raises(exc):
    @api_handler("Failed to do thing")
    def handler(event, context):
        raise exc
    return handler


@pytest.mark.parametrize("exc", [
    ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "GetItem"),
    EndpointConnectionError(endpoint_url="https://dynamodb.example"),
    KeyError("tourId"),
    ValueError("Environment variable STACK_NAME not set"),
])
def test_uncaught_exception_returns_standard_500(exc):
    resp = _raises(exc)({}, None)

    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert body["success"] is False
    assert body["error"] == {"code": "INTERNAL_ERROR", "message": "Failed to do thing"}
    assert resp["headers"]["Access-Control-Allow-Origin"] == "*"


def test_unhandled_error_log_includes_exception_type(caplog):
    _raises(KeyError("tourId"))({}, None)

    assert "Unhandled KeyError in handler" in caplog.text


def test_successful_response_passes_through_unchanged():
    expected = {"statusCode": 200, "body": "ok"}

    @api_handler()
    def handler(event, context):
        return expected

    assert handler({}, None) is expected
    assert handler.__name__ == "handler"
