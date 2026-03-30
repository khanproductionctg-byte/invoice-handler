"""
Structured JSON logging for production.
"""
import logging
import json
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Format logs as JSON for easier parsing and searching."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        if record.exc_info:
            log_obj["error"] = str(record.exc_info[1])
            log_obj["stack_trace"] = self.formatException(record.exc_info)
        
        extra = getattr(record, "extra", None)
        if extra:
            from utils.pii_redactor import deep_redact
            log_obj["extra"] = deep_redact(extra)
        
        return json.dumps(log_obj)


def setup_structured_logging() -> logging.Handler:
    """Configure the application to use structured JSON logging."""
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)
    
    return handler
