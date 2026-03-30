"""
Maintenance tasks for data retention, cleanup, and system health.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from celery import shared_task
from sqlalchemy import and_

logger = logging.getLogger(__name__)

# Retention periods (in days) - configurable via environment
AUDIT_LOG_RETENTION_DAYS = int(os.getenv("AUDIT_LOG_RETENTION_DAYS", 365))
INVOICE_RETENTION_DAYS = int(os.getenv("INVOICE_RETENTION_DAYS", 2555))  # ~7 years for tax purposes
REPORT_RETENTION_DAYS = int(os.getenv("REPORT_RETENTION_DAYS", 730))  # 2 years
WORKFLOW_RUN_RETENTION_DAYS = int(os.getenv("WORKFLOW_RUN_RETENTION_DAYS", 90))
RECONCILIATION_HISTORY_RETENTION_DAYS = int(os.getenv("RECONCILIATION_HISTORY_RETENTION_DAYS", 180))


@shared_task(name='worker.tasks.maintenance.data_retention_policy')
def data_retention_policy():
    """
    Execute data retention policy - delete old data based on configured retention periods.
    This task runs daily at 4 AM UTC.
    """
    from db.database import SessionLocal
    from db.models import AuditLog, WorkflowRun, ReconciliationHistory, Report
    
    results = {
        "audit_logs_deleted": 0,
        "workflow_runs_deleted": 0,
        "reconciliation_history_deleted": 0,
        "reports_deleted": 0,
        "errors": []
    }
    
    db = SessionLocal()
    
    try:
        # Calculate cutoff dates
        audit_cutoff = datetime.utcnow() - timedelta(days=AUDIT_LOG_RETENTION_DAYS)
        workflow_cutoff = datetime.utcnow() - timedelta(days=WORKFLOW_RUN_RETENTION_DAYS)
        reconciliation_cutoff = datetime.utcnow() - timedelta(days=RECONCILIATION_HISTORY_RETENTION_DAYS)
        report_cutoff = datetime.utcnow() - timedelta(days=REPORT_RETENTION_DAYS)
        
        # Delete old audit logs
        try:
            deleted = db.query(AuditLog).filter(
                AuditLog.created_at < audit_cutoff
            ).delete(synchronize_session=False)
            results["audit_logs_deleted"] = deleted
            logger.info(f"Deleted {deleted} audit logs older than {AUDIT_LOG_RETENTION_DAYS} days")
        except Exception as e:
            results["errors"].append(f"Audit log cleanup failed: {str(e)}")
            logger.error(f"Audit log cleanup failed: {e}")
        
        # Delete old workflow runs
        try:
            deleted = db.query(WorkflowRun).filter(
                WorkflowRun.started_at < workflow_cutoff
            ).delete(synchronize_session=False)
            results["workflow_runs_deleted"] = deleted
            logger.info(f"Deleted {deleted} workflow runs older than {WORKFLOW_RUN_RETENTION_DAYS} days")
        except Exception as e:
            results["errors"].append(f"Workflow run cleanup failed: {str(e)}")
            logger.error(f"Workflow run cleanup failed: {e}")
        
        # Delete old reconciliation history
        try:
            deleted = db.query(ReconciliationHistory).filter(
                ReconciliationHistory.created_at < reconciliation_cutoff
            ).delete(synchronize_session=False)
            results["reconciliation_history_deleted"] = deleted
            logger.info(f"Deleted {deleted} reconciliation history older than {RECONCILIATION_HISTORY_RETENTION_DAYS} days")
        except Exception as e:
            results["errors"].append(f"Reconciliation history cleanup failed: {str(e)}")
            logger.error(f"Reconciliation history cleanup failed: {e}")
        
        # Delete old reports (soft delete - mark as archived)
        try:
            # First, we'll archive old reports instead of deleting them
            # This is safer for compliance
            archived = db.query(Report).filter(
                and_(
                    Report.created_at < report_cutoff,
                    Report.is_archived != True
                )
            ).update({"is_archived": True}, synchronize_session=False)
            results["reports_deleted"] = archived
            logger.info(f"Archived {archived} reports older than {REPORT_RETENTION_DAYS} days")
        except Exception as e:
            results["errors"].append(f"Report archival failed: {str(e)}")
            logger.error(f"Report archival failed: {e}")
        
        # Commit all changes
        db.commit()
        
        # Send alert if significant data was deleted
        total_deleted = (
            results["audit_logs_deleted"] + 
            results["workflow_runs_deleted"] + 
            results["reconciliation_history_deleted"] +
            results["reports_deleted"]
        )
        
        if total_deleted > 1000:
            from utils.alert_system import send_alert
            send_alert({
                "type": "data_retention",
                "title": "Data Retention Policy Executed",
                "message": f"Deleted/archived {total_deleted} records",
                "severity": "low",
                "data": results
            })
        
        logger.info(f"Data retention policy completed: {results}")
        return results
        
    except Exception as e:
        logger.error(f"Data retention policy failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


@shared_task(name='worker.tasks.maintenance.cleanup_failed_workflows')
def cleanup_failed_workflows():
    """
    Clean up old failed workflow runs that are stuck.
    Deletes failed workflows older than 30 days (SOC 2 compliance).
    """
    from db.database import SessionLocal
    from db.models import WorkflowRun
    
    db = SessionLocal()
    
    try:
        # Delete failed workflows older than 30 days
        cutoff = datetime.utcnow() - timedelta(days=30)
        
        deleted = db.query(WorkflowRun).filter(
            and_(
                WorkflowRun.status == "failed",
                WorkflowRun.started_at < cutoff
            )
        ).delete(synchronize_session=False)
        
        db.commit()
        logger.info(f"Deleted {deleted} failed workflows older than 30 days")
        
        return {"failed_workflows_deleted": deleted}
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed workflow cleanup failed: {e}")
        raise
    finally:
        db.close()


@shared_task(name='worker.tasks.maintenance.health_check')
def system_health_check():
    """
    Perform system health checks.
    """
    from db.database import SessionLocal
    import psutil
    
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }
    
    # Check database connection
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        health_status["checks"]["database"] = "ok"
    except Exception as e:
        health_status["checks"]["database"] = f"error: {str(e)}"
        health_status["status"] = "unhealthy"
    
    # Check disk space
    disk_usage = psutil.disk_usage('/')
    if disk_usage.percent > 90:
        health_status["checks"]["disk"] = f"warning: {disk_usage.percent}% used"
    else:
        health_status["checks"]["disk"] = f"ok: {disk_usage.percent}% used"
    
    # Check memory
    memory = psutil.virtual_memory()
    if memory.percent > 90:
        health_status["checks"]["memory"] = f"warning: {memory.percent}% used"
    else:
        health_status["checks"]["memory"] = f"ok: {memory.percent}% used"
    
    # Check Redis
    try:
        import redis
        r = redis.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=int(os.getenv("REDIS_DB", 0))
        )
        r.ping()
        health_status["checks"]["redis"] = "ok"
    except Exception as e:
        health_status["checks"]["redis"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status


# =============================================================================
# DATABASE BACKUP AUTOMATION
# =============================================================================

BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", 30))
BACKUP_SCHEDULE_HOUR = int(os.getenv("BACKUP_SCHEDULE_HOUR", 2))  # 2 AM UTC default
S3_BUCKET = os.getenv("S3_BACKUP_BUCKET", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")


@shared_task(name='worker.tasks.maintenance.database_backup')
def database_backup():
    """
    Create a database backup and optionally upload to S3.
    Runs daily at configured hour (default: 2 AM UTC).
    """
    from datetime import datetime
    import subprocess
    import tempfile
    import shutil
    
    logger.info("Starting database backup...")
    result = {
        "started_at": datetime.utcnow().isoformat(),
        "status": "started",
    }
    
    try:
        if not DATABASE_URL:
            logger.warning("DATABASE_URL not set - skipping backup")
            result["status"] = "skipped"
            result["reason"] = "DATABASE_URL not configured"
            return result
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"invoice_handler_backup_{timestamp}.sql"
        
        with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp_file:
            backup_path = tmp_file.name
        
        db_url = DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        
        cmd = [
            "pg_dump",
            "--clean",
            "--if-exists",
            "--format=custom",
            "-f", backup_path,
            db_url
        ]
        
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {proc.stderr}")
        
        result["backup_file"] = backup_path
        result["backup_size_bytes"] = os.path.getsize(backup_path)
        
        if S3_BUCKET:
            try:
                import boto3
                s3_client = boto3.client('s3')
                s3_key = f"backups/{datetime.utcnow().strftime('%Y/%m/%d')}/{backup_filename}"
                s3_client.upload_file(backup_path, S3_BUCKET, s3_key)
                result["s3_bucket"] = S3_BUCKET
                result["s3_key"] = s3_key
                logger.info(f"Backup uploaded to S3: {S3_BUCKET}/{s3_key}")
            except ImportError:
                logger.warning("boto3 not installed - skipping S3 upload")
            except Exception as e:
                logger.warning(f"S3 upload failed: {e}")
        
        os.unlink(backup_path)
        
        result["completed_at"] = datetime.utcnow().isoformat()
        result["status"] = "success"
        logger.info(f"Database backup completed successfully")
        
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        logger.error(f"Database backup failed: {e}")
    
    return result


@shared_task(name='worker.tasks.maintenance.cleanup_old_backups')
def cleanup_old_backups():
    """
    Remove local backup files older than BACKUP_RETENTION_DAYS.
    Optionally clean old S3 backups as well.
    """
    import boto3
    from datetime import datetime, timedelta
    
    logger.info("Cleaning up old backups...")
    result = {
        "local_deleted": 0,
        "s3_deleted": 0,
        "status": "started"
    }
    
    backup_dir = os.getenv("BACKUP_DIR", "/tmp/backups")
    
    if os.path.exists(backup_dir):
        cutoff = datetime.utcnow() - timedelta(days=BACKUP_RETENTION_DAYS)
        for filename in os.listdir(backup_dir):
            filepath = os.path.join(backup_dir, filename)
            if os.path.isfile(filepath):
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime < cutoff:
                    try:
                        os.unlink(filepath)
                        result["local_deleted"] += 1
                    except Exception as e:
                        logger.warning(f"Failed to delete {filepath}: {e}")
    
    if S3_BUCKET:
        try:
            s3_client = boto3.client('s3')
            cutoff_str = (datetime.utcnow() - timedelta(days=BACKUP_RETENTION_DAYS)).strftime('%Y/%m/%d')
            
            response = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix="backups/")
            if 'Contents' in response:
                for obj in response['Contents']:
                    if obj['Key'] < f"backups/{cutoff_str}/":
                        s3_client.delete_object(Bucket=S3_BUCKET, Key=obj['Key'])
                        result["s3_deleted"] += 1
        except Exception as e:
            logger.warning(f"S3 cleanup failed: {e}")
    
    result["status"] = "completed"
    logger.info(f"Backup cleanup completed: {result}")
    return result
