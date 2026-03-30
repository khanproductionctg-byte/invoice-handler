"""
Prompt Injection Guard - Security utilities for LLM inputs.
Protects against prompt injection attacks in user-provided data.
"""
import re
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class PromptInjectionError(Exception):
    """Raised when prompt injection is detected and enforcement is enabled."""
    pass


INSTRUCTION_PATTERNS = [
    r"(?i)(ignore\s+(all\s+)?(previous|prior|above|instructions|prompts?|rules?|commands?))",
    r"(?i)(forget\s+(everything|all|your)\s+(instructions?|rules?|programming|training))",
    r"(?i)(new\s+instruction[s]?:)",
    r"(?i)(system\s*:\s*)",
    r"(?i)(assistant\s*:)",
    r"(?i)(you\s+are\s+(now|a|an)\s+)",
    r"(?i)(pretend\s+(you|to\s+be)|act\s+as\s+if)",
    r"(?i)(roleplay)",
    r"(?i)(let's\s+play\s+a\s+game)",
    r"(?i)(you\s+can\s+ignore)",
    r"(?i)(disregard\s+(your|all))",
    r"(?i)(override\s+(your|safety|security))",
    r"(?i)(bypass\s+(safety|security|rules?))",
    r"(?i)(jailbreak)",
    r"(?i)(DAN\s+mode)",
    r"(?i)(developer\s+mode)",
    r"(?i)(\{\{.*\}\})",  # Template injection
    r"(?i)(<script|javascript:|onerror=|onclick=)",  # XSS
]


def sanitize_for_prompt(value: Any) -> str:
    """
    Sanitize user input to prevent prompt injection.
    
    Args:
        value: Any input value to sanitize
        
    Returns:
        Sanitized string safe for inclusion in prompts
    """
    if value is None:
        return ""
    
    text = str(value)
    
    # Remove control characters
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    
    # Remove or escape injection patterns
    for pattern in INSTRUCTION_PATTERNS:
        # Replace matched patterns with a safe placeholder
        text = re.sub(pattern, "[FILTERED]", text, flags=re.IGNORECASE)
    
    # Escape template injection markers
    text = text.replace("{{", "[\[").replace("}}", "\]]")
    text = text.replace("{{", "[[").replace("}}", "]]")
    
    # Escape potential JSON/XSS patterns
    text = re.sub(r'<script', '&lt;script', text, flags=re.IGNORECASE)
    text = re.sub(r'javascript:', 'javascript&#58;', text, flags=re.IGNORECASE)
    
    return text


def check_for_injection(text: str, raise_on_injection: bool = False) -> tuple[bool, List[str]]:
    """
    Check if text contains potential prompt injection attempts.
    
    Args:
        text: Text to check
        raise_on_injection: If True, raise PromptInjectionError instead of just returning
        
    Returns:
        Tuple of (is_safe, list_of_violations)
        
    Raises:
        PromptInjectionError: If raise_on_injection=True and injection detected
    """
    violations = []
    
    for pattern in INSTRUCTION_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            violations.append(f"Pattern matched: {pattern}")
    
    is_safe = len(violations) == 0
    
    if not is_safe and raise_on_injection:
        logger.warning(f"Prompt injection detected: {violations}")
        raise PromptInjectionError(
            f"Potential prompt injection detected. Violations: {violations}"
        )
    
    return is_safe, violations


def sanitize_invoice_data(data: Dict[str, Any], enforce: bool = False) -> Dict[str, Any]:
    """
    Sanitize invoice data for LLM processing.
    
    Args:
        data: Invoice data dictionary
        enforce: If True, raise exception on injection instead of just sanitizing
        
    Returns:
        Sanitized dictionary
    """
    fields_to_sanitize = [
        "vendor_name", "description", "notes", "memo",
        "customer_name", "customer_email", "line_item_description",
        "invoice_number", "reference", "terms"
    ]
    
    sanitized = data.copy()
    
    for field in fields_to_sanitize:
        if field in sanitized and sanitized[field]:
            value = str(sanitized[field])
            is_safe, violations = check_for_injection(value, raise_on_injection=enforce)
            sanitized[field] = sanitize_for_prompt(value)
            if not is_safe:
                logger.warning(f"Field '{field}' contained injection patterns: {violations}")
    
    return sanitized


def format_safe_prompt(template: str, enforce: bool = False, **kwargs) -> str:
    """
    Format a prompt template with sanitized inputs.
    
    Args:
        template: Prompt template string
        enforce: If True, raise exception on injection
        **kwargs: Variables to inject
        
    Returns:
        Safely formatted prompt
        
    Raises:
        PromptInjectionError: If enforce=True and injection detected
    """
    sanitized_kwargs = {}
    
    for key, value in kwargs.items():
        value_str = str(value)
        check_for_injection(value_str, raise_on_injection=enforce)
        sanitized_kwargs[key] = sanitize_for_prompt(value)
    
    return template.format(**sanitized_kwargs)
