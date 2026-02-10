"""
Logging utilities
"""

import logging
import os
import json
from typing import Any, Dict


def get_logger(name: str) -> logging.Logger:
    """
    Get configured logger instance
    
    Args:
        name: Logger name (usually __name__)
    
    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    
    # Set log level from environment variable
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    # Configure handler if not already configured
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger


def log_event(logger: logging.Logger, event: Dict[str, Any]) -> None:
    """
    Log Lambda event (sanitized)
    
    Args:
        logger: Logger instance
        event: Lambda event dictionary
    """
    # Create sanitized copy (remove sensitive headers)
    sanitized_event = event.copy()
    
    if 'headers' in sanitized_event:
        headers = sanitized_event['headers'].copy()
        if 'authorization' in headers:
            headers['authorization'] = '***REDACTED***'
        if 'Authorization' in headers:
            headers['Authorization'] = '***REDACTED***'
        sanitized_event['headers'] = headers
    
    logger.debug(f"Event: {json.dumps(sanitized_event, default=str)}")
