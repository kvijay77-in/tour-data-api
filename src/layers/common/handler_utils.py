"""
Shared Lambda handler utilities

Provides the outermost error boundary for API Gateway Lambda handlers.
"""

import functools

from botocore.exceptions import BotoCoreError, ClientError

from logger import get_logger
from response import internal_error_response

logger = get_logger(__name__)


def api_handler(error_message: str = "Internal server error"):
    """Outermost error boundary for API Gateway Lambda handlers.

    Turns any uncaught exception into the standard 500 error envelope so
    clients never see raw API Gateway errors or stack traces. Handlers should
    still catch the specific exceptions they can handle (for example
    ``ValidationError`` -> 400) and let everything else reach this boundary.

    Args:
        error_message: Client-facing message for the 500 response.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(event, context):
            try:
                return func(event, context)
            except ClientError as e:
                err = e.response.get("Error", {})
                logger.error("AWS ClientError in %s: %s - %s",
                             func.__name__, err.get("Code"), err.get("Message"), exc_info=True)
            except BotoCoreError:
                logger.error("AWS SDK error in %s", func.__name__, exc_info=True)
            except Exception as e:  # pylint: disable=broad-exception-caught
                # Intentional API boundary catch-all; see docstring.
                logger.error("Unhandled %s in %s: %s",
                             type(e).__name__, func.__name__, e, exc_info=True)
            return internal_error_response(error_message)
        return wrapper
    return decorator
