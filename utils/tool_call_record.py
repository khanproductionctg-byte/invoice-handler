"""
Tool call recording for observability.
Records every tool invocation with hashed input/output, tokens, and latency.
"""
import hashlib
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TOOL_CALLS_COUNTER: Optional[Any] = None
RATE_LIMIT_CACHE: Dict[str, list] = {}

ToolCallRecordDict = Dict[str, Any]


@dataclass
class ToolCallRecord:
    timestamp: datetime
    tenant_id: str
    workflow_run_id: str
    agent_name: str
    tool_name: str
    input_hash: str
    output_hash: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    exit_reason: Literal["success", "error", "timeout", "rate_limit"]
    error_detail: Optional[str]


def _hash_content(content: Any) -> str:
    """Create SHA256 hash of content (never log raw financial data)."""
    if content is None:
        return ""
    try:
        content_str = str(content)
    except Exception:
        content_str = ""
    return hashlib.sha256(content_str.encode()).hexdigest()[:16]


def _get_tool_calls_counter() -> Optional[Any]:
    """Lazy-load Prometheus counter for tool calls."""
    global TOOL_CALLS_COUNTER
    if TOOL_CALLS_COUNTER is not None:
        return TOOL_CALLS_COUNTER

    try:
        from prometheus_client import Counter
        TOOL_CALLS_COUNTER = Counter(
            'tool_calls_total',
            'Total tool calls',
            ['tool_name', 'exit_reason', 'agent_name']
        )
    except ImportError:
        logger.warning("prometheus_client not installed - tool call metrics disabled")

    return TOOL_CALLS_COUNTER


def _check_rate_limit_alert(tool_name: str, tenant_id: str) -> None:
    """Fire alert if rate_limit exit_reason > 10 in last 60s for same tool."""
    key = f"{tenant_id}:{tool_name}"
    now = time.time()

    if key not in RATE_LIMIT_CACHE:
        RATE_LIMIT_CACHE[key] = []

    RATE_LIMIT_CACHE[key] = [t for t in RATE_LIMIT_CACHE[key] if now - t < 60]
    RATE_LIMIT_CACHE[key].append(now)

    count = len(RATE_LIMIT_CACHE[key])
    if count > 10:
        logger.warning(
            "RATE_LIMIT_ALERT",
            extra={
                "tool_name": tool_name,
                "tenant_id": tenant_id,
                "count_60s": count,
                "threshold": 10
            }
        )


def emit_tool_record(record: ToolCallRecord) -> None:
    """
    Emit tool call record: insert to audit_logs, structlog, Prometheus, alerts.
    """
    try:
        db: Optional[Session] = None
        try:
            from db.database import SessionLocal
            db = SessionLocal()
            from db.models import AuditLog
            audit_entry = AuditLog(
                tenant_id=int(record.tenant_id) if record.tenant_id.isdigit() else 0,
                action="tool_call",
                resource_type=record.tool_name,
                resource_id=0,
                new_values=str(asdict(record)),
                status="success" if record.exit_reason == "success" else "failure",
                error_message=record.error_detail,
            )
            db.add(audit_entry)
            db.commit()
        except Exception as db_err:
            logger.warning(f"Failed to insert audit log: {db_err}")
        finally:
            if db:
                db.close()
    except Exception:
        pass

    structured = {
        "event": "tool_call",
        "timestamp": record.timestamp.isoformat(),
        "tenant_id": record.tenant_id,
        "workflow_run_id": record.workflow_run_id,
        "agent_name": record.agent_name,
        "tool_name": record.tool_name,
        "input_hash": record.input_hash,
        "output_hash": record.output_hash,
        "tokens_in": record.tokens_in,
        "tokens_out": record.tokens_out,
        "latency_ms": record.latency_ms,
        "exit_reason": record.exit_reason,
    }
    logger.info("tool_call_record", extra=structured)

    counter = _get_tool_calls_counter()
    if counter:
        counter.labels(
            tool_name=record.tool_name,
            exit_reason=record.exit_reason,
            agent_name=record.agent_name
        ).inc()

    if record.exit_reason == "rate_limit":
        _check_rate_limit_alert(record.tool_name, record.tenant_id)
