"""
PII Redaction utilities for protecting sensitive data in logs and LLM prompts.
"""
import re
import copy
from typing import Any, Dict, List, Optional, Union
from decimal import Decimal
from datetime import datetime, date
from pydantic import BaseModel


PII_FIELDS: frozenset[str] = frozenset({
    "vendor_email",
    "vendor_phone", 
    "account_number",
    "routing_number",
    "access_token",
    "refresh_token",
    "ssn",
    "tax_id",
    "bank_account",
    "plaid_token",
    "client_secret",
    "api_key",
    "secret_key",
    "password",
    "token",
    "auth_token",
    "session_id",
    "credit_card",
    "card_number",
    "cvv",
    "pin",
    "national_id",
    "passport",
    "driver_license",
    "date_of_birth",
    "dob",
    "mother_maiden_name",
    "security_question",
    "security_answer",
})

PII_VALUE_PATTERNS: List[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', re.IGNORECASE)),
    ("phone", re.compile(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b')),
    ("credit_card", re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b')),
    ("ssn", re.compile(r'\b\d{3}-\d{2}-\d{4}\b')),
]


def _matches_pii_value(value: str) -> bool:
    """Check if a string value matches any PII pattern."""
    if not isinstance(value, str):
        return False
    for _, pattern in PII_VALUE_PATTERNS:
        if pattern.search(value):
            return True
    return False


def _redact_value(value: Any) -> Any:
    """Redact a value if it matches PII patterns."""
    if isinstance(value, str):
        if _matches_pii_value(value):
            return "[REDACTED]"
    return value


def deep_redact(obj: Any, max_depth: int = 10) -> Any:
    """
    Recursively redact PII from any object.
    
    Args:
        obj: Any object to redact (dict, list, Pydantic model, etc.)
        max_depth: Maximum recursion depth (default 10 levels)
    
    Returns:
        A deep copy of the object with PII redacted. Original is never mutated.
    """
    if max_depth <= 0:
        if isinstance(obj, dict):
            return _redact_dict(obj, 0)
        return obj
    
    if obj is None:
        return None
    
    if isinstance(obj, str):
        redacted = obj
        for _, pattern in PII_VALUE_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    
    if isinstance(obj, bytes):
        return obj
    
    if isinstance(obj, (int, float, bool, Decimal)):
        return obj
    
    if isinstance(obj, (datetime, date)):
        return obj
    
    if isinstance(obj, dict):
        return _redact_dict(obj, max_depth)
    
    if isinstance(obj, (list, tuple)):
        return _redact_list(obj, max_depth)
    
    if hasattr(obj, "model_dump"):
        return _redact_pydantic(obj, max_depth)
    
    if hasattr(obj, "__dict__"):
        return _redact_object(obj, max_depth)
    
    return obj


def _redact_dict(obj: Dict[Any, Any], max_depth: int) -> Dict[Any, Any]:
    """Redact PII from a dictionary."""
    result: Dict[Any, Any] = {}
    for key, value in obj.items():
        key_str = str(key).lower()
        
        if key_str in PII_FIELDS:
            result[key] = "[REDACTED]"
        elif isinstance(value, str):
            if _matches_pii_value(value):
                result[key] = "[REDACTED]"
            else:
                result[key] = value
        elif isinstance(value, dict):
            if max_depth > 1:
                result[key] = _redact_dict(value, max_depth - 1)
            elif max_depth > 0:
                result[key] = _redact_dict(value, 0)
            else:
                result[key] = value
        elif isinstance(value, (list, tuple)):
            if max_depth > 1:
                result[key] = _redact_list(value, max_depth - 1)
            else:
                result[key] = value
        else:
            result[key] = value
    
    return result


def _redact_list(obj: Union[List[Any], tuple], max_depth: int) -> Union[List[Any], tuple]:
    """Redact PII from a list or tuple."""
    is_tuple = isinstance(obj, tuple)
    if max_depth > 1:
        redacted_list = [deep_redact(item, max_depth - 1) for item in obj]
    elif max_depth > 0:
        redacted_list = [deep_redact(item, 0) for item in obj]
    else:
        redacted_list = list(obj)
    return tuple(redacted_list) if is_tuple else redacted_list


def _redact_pydantic(obj: BaseModel, max_depth: int) -> BaseModel:
    """Redact PII from a Pydantic model."""
    try:
        data = obj.model_dump()
        redacted_data = deep_redact(data, max_depth - 1)
        return obj.__class__.model_validate(redacted_data)
    except Exception:
        return obj


def _redact_object(obj: Any, max_depth: int) -> Any:
    """Redact PII from a regular object."""
    result = copy.deepcopy(obj)
    for attr_name in dir(result):
        if attr_name.startswith('_'):
            continue
        
        try:
            value = getattr(result, attr_name)
        except AttributeError:
            continue
        
        if callable(value) and not isinstance(value, (str, int, float, bool)):
            continue
        
        attr_lower = attr_name.lower()
        if attr_lower in PII_FIELDS:
            setattr(result, attr_name, "[REDACTED]")
        else:
            try:
                redacted_value = deep_redact(value, max_depth - 1)
                setattr(result, attr_name, redacted_value)
            except (AttributeError, TypeError):
                pass
    
    return result


LLM_SAFE_FIELDS: frozenset[str] = frozenset({
    "vendor_name",
    "amount_due",
    "due_date", 
    "invoice_number",
    "line_items",
    "currency",
    "invoice_date",
    "status",
    "description",
    "amount_paid",
})


def sanitize_for_llm(invoice: Union[Dict[str, Any], Any]) -> Dict[str, Any]:
    """
    Strip invoice data down to only LLM-necessary fields.
    
    Args:
        invoice: Invoice as dict or ORM model
    
    Returns:
        Dict containing only safe fields for LLM consumption
    """
    if invoice is None:
        return {}
    
    if hasattr(invoice, "__dict__"):
        invoice = {k: v for k, v in invoice.__dict__.items() if not k.startswith('_')}
    
    if hasattr(invoice, "model_dump"):
        invoice = invoice.model_dump() if hasattr(invoice, "model_dump") else dict(invoice)
    
    if not isinstance(invoice, dict):
        invoice = {}
    
    safe_data: Dict[str, Any] = {}
    
    for field in LLM_SAFE_FIELDS:
        if field in invoice:
            value = invoice[field]
            if value is not None:
                safe_data[field] = deep_redact(value)
    
    return safe_data
