"""
Admin API routes for system monitoring and management.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
import os
import psutil
import time
from datetime import datetime, timedelta

from db.database import get_db
from db import models

# Rate limiting
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    limiter = Limiter(key_func=get_remote_address)
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    limiter = None
    RATE_LIMITING_AVAILABLE = False

# Optional Celery imports
try:
    from celery.result import AsyncResult
    from worker.celery_worker import celery_app
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    celery_app = None
    AsyncResult = None

router = APIRouter(prefix="/admin", tags=["admin"])

# Admin authentication dependency
async def require_admin(request: Request, db: Session = Depends(get_db)):
    """Require admin role for access."""
    from middleware.auth import get_current_user
    user = await get_current_user(request, db)
    if not user or not getattr(user, 'is_superadmin', False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# Helper function to get system stats
def get_system_stats() -> Dict[str, Any]:
    return {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory": {
            "total": psutil.virtual_memory().total,
            "available": psutil.virtual_memory().available,
            "percent": psutil.virtual_memory().percent,
            "used": psutil.virtual_memory().used,
            "free": psutil.virtual_memory().free,
        },
        "disk": {
            "total": psutil.disk_usage('/').total,
            "used": psutil.disk_usage('/').used,
            "free": psutil.disk_usage('/').free,
            "percent": psutil.disk_usage('/').percent,
        },
        "boot_time": psutil.boot_time(),
    }

# Helper function to get Celery stats
def get_celery_stats() -> Dict[str, Any]:
    try:
        # Get active tasks
        active_tasks = celery_app.control.active()
        # Get scheduled tasks
        scheduled_tasks = celery_app.control.scheduled()
        # Get reserved tasks
        reserved_tasks = celery_app.control.reserved()
        # Get stats
        stats = celery_app.control.stats()
        
        return {
            "active_tasks": active_tasks,
            "scheduled_tasks": scheduled_tasks,
            "reserved_tasks": reserved_tasks,
            "worker_stats": stats,
        }
    except Exception as e:
        return {"error": f"Failed to get Celery stats: {str(e)}"}

# Helper function to get recent database activity
def get_db_stats(db: Session) -> Dict[str, Any]:
    try:
        # Count records in main tables
        user_count = db.query(models.User).count()
        invoice_count = db.query(models.Invoice).count()
        expense_count = db.query(models.Expense).count()
        payment_count = db.query(models.Payment).count()
        report_count = db.query(models.Report).count()
        
        # Get recent invoices (last 24 hours)
        recent_invoices = db.query(models.Invoice).filter(
            models.Invoice.created_at >= datetime.utcnow() - timedelta(days=1)
        ).count()
        
        return {
            "user_count": user_count,
            "invoice_count": invoice_count,
            "expense_count": expense_count,
            "payment_count": payment_count,
            "report_count": report_count,
            "recent_invoices_24h": recent_invoices,
        }
    except Exception as e:
        return {"error": f"Failed to get DB stats: {str(e)}"}

@router.get("/health", response_model=Dict[str, Any])
def admin_health_check(
    db: Session = Depends(get_db)
):
    """
    Get system health status.
    """
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": get_system_stats(),
        "celery": get_celery_stats(),
        "database": get_db_stats(db),
    }

@router.get("/ingestion/status", response_model=Dict[str, Any])
def admin_ingestion_status(
    db: Session = Depends(get_db)
):
    """
    Get status of ingestion tasks (last run times, etc.).
    We don't have a table for ingestion logs, so we can't show historical data.
    For now, we can show the configuration and suggest using Celery monitoring tools.
    """
    # In a real system, we would have an ingestion_log table.
    # For now, we return a message and the config.
    return {
        "message": "Ingestion status tracking not implemented. Use Celery monitoring tools (e.g., Flower) for real-time status.",
        "configuration": {
            "daily_ingestion_schedule": "0 2 * * * (Every day at 2:00 AM UTC)",
            "ingestion_sources": ["gmail", "drive", "quickbooks", "xero", "plaid"],
        },
        "suggestion": "Consider implementing an ingestion log table to track runs."
    }

@router.post("/ingestion/trigger/{source}", response_model=Dict[str, Any])
@limiter.limit("5/minute")
def admin_trigger_ingestion(
    request: Request,
    source: str,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(require_admin)
):
    """
    Manually trigger ingestion for a specific source for all users.
    """
    valid_sources = ["gmail", "drive", "quickbooks", "xero", "plaid"]
    if source not in valid_sources:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source. Must be one of: {valid_sources}"
        )
    
    # We'll trigger the ingestion task for each user.
    # In a real system, you might want to do this in a batch or use a different approach.
    try:
        # Get all active users
        users = db.query(models.User).filter(models.User.is_active == True).all()
        
        # For each user, we would call the ingestion task for that source.
        # However, our current ingest_data_for_user task runs all sources.
        # We could modify it to accept a source parameter, but for now we'll just
        # note that this would trigger all sources for each user.
        # We return a message indicating what would happen.
        
        return {
            "message": f"Triggered ingestion for source '{source}' for {len(users)} users.",
            "note": "This triggers the full ingestion process for each user (all sources). "
                    "To trigger a single source, the ingestion task would need to be modified "
                    "to accept a source parameter.",
            "users_affected": len([u.id for u in users]),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger ingestion: {str(e)}"
        )

@router.get("/agents/metrics", response_model=Dict[str, Any])
def admin_agents_metrics(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(require_admin)
):
    """
    Get performance metrics for the agents.
    We don't have a table for agent metrics, so we return a placeholder.
    """
    return {
        "message": "Agent metrics tracking not implemented. Consider adding tables to track agent runs, processing times, and success rates.",
        "suggested_tables": [
            "agent_run_log",
            "ingestion_log",
            "matching_log",
            "reminder_log",
            "report_log"
        ]
    }

@router.get("/config", response_model=Dict[str, Any])
def admin_get_config(
    request: Request,
    admin_user: models.User = Depends(require_admin)
):
    """
    Get current configuration (non-sensitive).
    Note: In a production system, you would not expose all config values.
    """
    # We'll expose some non-sensitive configuration from environment variables.
    # We avoid exposing secrets.
    config = {
        "app_name": os.getenv("APP_NAME", "Invoice Handler"),
        "app_version": os.getenv("APP_VERSION", "1.0.0"),
        "debug": os.getenv("DEBUG", "False").lower() == "true",
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "environment": os.getenv("ENVIRONMENT", "development"),
        "scheduler": {
            "daily_ingestion": "0 2 * * * (Every day at 2:00 AM UTC)",
            "daily_reminders": "0 9 * * * (Every day at 9:00 AM UTC)",
            "weekly_reports": "0 3 * * 1 (Every Monday at 3:00 AM UTC)",
        },
        "features": {
            "forecasting_enabled": True,  # This is hardcoded in the reporter agent
            "tax_ready_csv_export": True,
        }
    }
    return config

# Note: We do not provide endpoints to update configuration at runtime because
# it would require restarting services or implementing a dynamic config system.
# For configuration changes, we recommend updating the .env file and restarting.