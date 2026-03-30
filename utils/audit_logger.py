"""
Audit logging utilities for SOC 2 Type II compliance.
Logs all data access and modification events.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """Audit action types."""
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"
    EXPORT = "export"
    LOGIN_FAILED = "login_failed"
    ACCESS_DENIED = "access_denied"


class AuditLogger:
    """
    Audit logger for tracking all data access and modifications.
    Logs to both database and structured log output.
    """
    
    def __init__(self):
        self._db_session = None
    
    def set_db_session(self, db_session):
        """Set database session for audit logging."""
        self._db_session = db_session
    
    def log(
        self,
        action: str,
        resource_type: str,
        tenant_id: int,
        user_id: Optional[int] = None,
        resource_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_method: Optional[str] = None,
        request_path: Optional[str] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        status: str = "success",
        error_message: Optional[str] = None
    ):
        """
        Log an audit event.
        
        Args:
            action: The action performed (create, read, update, delete, etc.)
            resource_type: Type of resource (invoice, payment, customer, etc.)
            tenant_id: ID of the tenant
            user_id: ID of the user who performed the action
            resource_id: ID of the affected resource
            ip_address: Client IP address
            user_agent: Client user agent
            request_method: HTTP method
            request_path: HTTP request path
            old_values: Previous values (for updates/deletes)
            new_values: New values (for creates/updates)
            status: success or failure
            error_message: Error message if failed
        """
        # Build structured log data
        audit_data = {
            "event_type": "audit_log",
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "request_method": request_method,
            "request_path": request_path,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": str(uuid.uuid4())[:8]
        }
        
        # Add change details if present
        if old_values:
            # Strip sensitive fields
            safe_old = self._sanitize_values(old_values)
            audit_data["old_values"] = safe_old
        
        if new_values:
            # Strip sensitive fields
            safe_new = self._sanitize_values(new_values)
            audit_data["new_values"] = safe_new
        
        if error_message:
            audit_data["error_message"] = error_message
        
        # Log to structured logger (for JSON logs / SIEM ingestion)
        log_level = logging.INFO if status == "success" else logging.WARNING
        logger.log(log_level, "Audit event", extra=audit_data)
        
        # Also save to database if session is available
        self._save_to_db(audit_data)
    
    def _sanitize_values(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive fields from values before logging."""
        sensitive_fields = {
            'password', 'hashed_password', 'access_token', 'refresh_token',
            'encrypted_tokens', 'api_key', 'secret', 'token', 'card_number',
            'cvv', 'ssn', 'credit_card'
        }
        
        sanitized = {}
        for key, value in values.items():
            if key.lower() in sensitive_fields:
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_values(value)
            else:
                sanitized[key] = value
        
        return sanitized
    
    def _save_to_db(self, audit_data: Dict[str, Any]):
        """Save audit log to database with guaranteed write via Celery."""
        if not self._db_session:
            self._save_via_celery(audit_data)
            return
        
        try:
            from db.models import AuditLog
            
            audit_log = AuditLog(
                tenant_id=audit_data["tenant_id"],
                user_id=audit_data.get("user_id"),
                action=audit_data["action"],
                resource_type=audit_data["resource_type"],
                resource_id=audit_data.get("resource_id"),
                ip_address=audit_data.get("ip_address"),
                user_agent=audit_data.get("user_agent"),
                request_method=audit_data.get("request_method"),
                request_path=audit_data.get("request_path"),
                old_values=json.dumps(audit_data.get("old_values")) if audit_data.get("old_values") else None,
                new_values=json.dumps(audit_data.get("new_values")) if audit_data.get("new_values") else None,
                status=audit_data["status"],
                error_message=audit_data.get("error_message")
            )
            
            self._db_session.add(audit_log)
            self._db_session.commit()
            
        except Exception as e:
            logger.error(f"Failed to save audit log to database: {str(e)}")
            try:
                self._db_session.rollback()
            except:
                pass
            self._save_via_celery(audit_data)
    
    def _save_via_celery(self, audit_data: Dict[str, Any]):
        """Fallback to Celery task for guaranteed audit log writes."""
        try:
            from worker.tasks.audit_tasks import save_audit_log
            save_audit_log.delay(audit_data)
        except Exception as e:
            logger.error(f"Failed to queue audit log to Celery: {str(e)}")
    
    # Convenience methods for common actions
    
    def log_create(
        self, tenant_id: int, user_id: int, resource_type: str, resource_id: int,
        values: Dict[str, Any], **kwargs
    ):
        """Log a create action."""
        self.log(
            action=AuditAction.CREATE,
            resource_type=resource_type,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=resource_id,
            new_values=values,
            **kwargs
        )
    
    def log_read(
        self, tenant_id: int, user_id: int, resource_type: str, resource_id: int, **kwargs
    ):
        """Log a read action."""
        self.log(
            action=AuditAction.READ,
            resource_type=resource_type,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=resource_id,
            **kwargs
        )
    
    def log_update(
        self, tenant_id: int, user_id: int, resource_type: str, resource_id: int,
        old_values: Dict[str, Any], new_values: Dict[str, Any], **kwargs
    ):
        """Log an update action."""
        self.log(
            action=AuditAction.UPDATE,
            resource_type=resource_type,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=resource_id,
            old_values=old_values,
            new_values=new_values,
            **kwargs
        )
    
    def log_delete(
        self, tenant_id: int, user_id: int, resource_type: str, resource_id: int,
        old_values: Optional[Dict[str, Any]] = None, **kwargs
    ):
        """Log a delete action."""
        self.log(
            action=AuditAction.DELETE,
            resource_type=resource_type,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=resource_id,
            old_values=old_values,
            **kwargs
        )
    
    def log_login(
        self, tenant_id: int, user_id: int, status: str = "success", **kwargs
    ):
        """Log a login attempt."""
        self.log(
            action=AuditAction.LOGIN if status == "success" else AuditAction.LOGIN_FAILED,
            resource_type="auth",
            tenant_id=tenant_id,
            user_id=user_id if status == "success" else None,
            status=status,
            **kwargs
        )
    
    def log_export(
        self, tenant_id: int, user_id: int, resource_type: str, count: int, **kwargs
    ):
        """Log a data export."""
        self.log(
            action=AuditAction.EXPORT,
            resource_type=resource_type,
            tenant_id=tenant_id,
            user_id=user_id,
            new_values={"export_count": count},
            **kwargs
        )


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get or create the global audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def set_audit_db_session(db_session):
    """Set database session for audit logging."""
    audit_logger = get_audit_logger()
    audit_logger.set_db_session(db_session)
