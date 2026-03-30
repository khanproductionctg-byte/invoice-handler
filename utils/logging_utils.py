"""
Logging utilities with PII masking for production 2026 compliance.
"""
import logging
import re
import json
from typing import Any, Dict
from functools import wraps

logger = logging.getLogger(__name__)


EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
PHONE_PATTERN = r'\+?1?\d{9,15}'
SSN_PATTERN = r'\b\d{3}-\d{2}-\d{4}\b'
CREDIT_CARD_PATTERN = r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'


class PIIMaskingFormatter(logging.Formatter):
    """Custom formatter that masks PII in log messages."""
    
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        return mask_pii(message)


def mask_pii(data: Any) -> Any:
    """Recursively mask PII in dictionaries, lists, or strings."""
    
    if isinstance(data, str):
        data = re.sub(EMAIL_PATTERN, '[EMAIL_REDACTED]', data)
        data = re.sub(PHONE_PATTERN, '[PHONE_REDACTED]', data)
        data = re.sub(SSN_PATTERN, '[SSN_REDACTED]', data)
        data = re.sub(CREDIT_CARD_PATTERN, '[CC_REDACTED]', data)
        return data
    
    elif isinstance(data, dict):
        mask_fields = {'email', 'phone', 'ssn', 'credit_card', 'password', 
                      'secret', 'token', 'api_key', 'vendor_name', 'customer_name'}
        
        return {
            k: '[REDACTED]' if k.lower() in mask_fields else mask_pii(v)
            for k, v in data.items()
        }
    
    elif isinstance(data, (list, tuple)):
        return [mask_pii(item) for item in data]
    
    else:
        return data


def log_with_pii_masking(func):
    """Decorator to automatically mask PII in function arguments."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        safe_args = mask_pii(list(args))
        safe_kwargs = mask_pii(kwargs)
        
        logger.debug(f"Calling {func.__name__} with masked arguments")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"{func.__name__} completed successfully")
            return result
        except Exception as e:
            logger.error(f"{func.__name__} failed: {str(e)}")
            raise
    return wrapper


def setup_secure_logging():
    """Configure logging with PII masking for production."""
    formatter = PIIMaskingFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    
    for logger_name in ['agents', 'utils', 'db', 'api']:
        lg = logging.getLogger(logger_name)
        lg.setLevel(logging.DEBUG)
        lg.addHandler(handler)
