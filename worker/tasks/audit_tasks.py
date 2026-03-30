"""
Celery tasks for audit logging to ensure guaranteed writes.
"""
import json
import logging
from typing import Dict, Any

from worker.celery_worker import celery_app
from db.database import SessionLocal
from db import models

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(Exception,),
    retry_backoff=True
)
def save_audit_log(self, audit_data: Dict[str, Any]):
    """
    Save audit log to database via Celery task.
    This ensures audit logs are written even if the original request fails.
    """
    db = SessionLocal()
    try:
        audit_log = models.AuditLog(
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
        
        db.add(audit_log)
        db.commit()
        logger.info(f"Audit log saved via Celery: {audit_data.get('action')} on {audit_data.get('resource_type')}")
        
    except Exception as e:
        logger.error(f"Failed to save audit log via Celery: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()
