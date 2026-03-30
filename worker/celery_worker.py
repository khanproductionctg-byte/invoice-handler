"""
Celery worker configuration for background tasks.
"""
import os
from celery import Celery
from celery.schedules import crontab
from celery.exceptions import MaxRetriesExceededError
from dotenv import load_dotenv

# Initialize Sentry (optional)
load_dotenv()

sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        
        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=os.getenv("ENVIRONMENT", "production"),
            traces_sample_rate=0.1,
            integrations=[
                SqlalchemyIntegration(),
                RedisIntegration(),
            ],
            send_default_pii=False
        )
    except ImportError:
        pass

# Celery configuration
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = os.getenv("REDIS_PORT", "6379")
redis_db = os.getenv("REDIS_DB", "0")

broker_url = f"redis://{redis_host}:{redis_port}/{redis_db}"
result_backend = f"redis://{redis_host}:{redis_port}/{redis_db}"

celery_app = Celery(
    "invoice_handler",
    broker=broker_url,
    backend=result_backend,
    include=[
        "worker.tasks.invoice_tasks",
        "worker.tasks.report_tasks",
        "worker.tasks.maintenance",
    ]
)

# Dead Letter Queue configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", 30 * 60)),  # 30 minutes default
    task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", 25 * 60)),  # 25 minutes default
    worker_prefetch_multiplier=int(os.getenv("CELERY_PREFETCH_MULTIPLIER", 1)),
    worker_max_tasks_per_child=int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", 1000)),
    
    # Dead Letter Queue settings
    task_queues={
        'default': {
            'exchange': 'default',
            'routing_key': 'default',
        },
        'dead_letter': {
            'exchange': 'dead_letter',
            'routing_key': 'dead_letter',
        },
    },
    task_routes={
        'worker.tasks.invoice_tasks.*': {'queue': 'default'},
        'worker.tasks.report_tasks.*': {'queue': 'default'},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Dead letter task handler
@celery_app.task(bind=True, name='worker.tasks.handle_dlq', max_retries=3)
def handle_dlq_task(self, task_name, task_args, task_kwargs, exception_info):
    """
    Handler for dead letter queue - logs failed tasks for manual review.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.error(
        f"DLQ: Task {task_name} failed permanently. "
        f"Args: {task_args}, Kwargs: {task_kwargs}, Error: {exception_info}"
    )
    
    # Could integrate with alerting system here
    from utils.alert_system import send_alert
    send_alert({
        "type": "task_failed",
        "title": f"Critical: Task {task_name} in Dead Letter Queue",
        "message": f"Task failed after all retries. Manual intervention required.",
        "severity": "high",
        "data": {
            "task_name": task_name,
            "args": str(task_args),
            "kwargs": str(task_kwargs),
            "error": exception_info,
        }
    })

# Celery Beat schedule
celery_app.conf.beat_schedule = {
    'daily-ingestion': {
        'task': 'worker.tasks.invoice_tasks.daily_ingestion',
        'schedule': crontab(hour=2, minute=0),
    },
    'send-daily-payment-reminders': {
        'task': 'worker.tasks.invoice_tasks.send_daily_payment_reminders',
        'schedule': crontab(hour=9, minute=0),
    },
    'weekly-reports': {
        'task': 'worker.tasks.report_tasks.generate_weekly_report',
        'schedule': crontab(hour=3, minute=0, day_of_week=1),
    },
    'data-retention-policy': {
        'task': 'worker.tasks.maintenance.data_retention_policy',
        'schedule': crontab(hour=4, minute=0),  # Daily at 4 AM UTC
    },
    'token-budget-check': {
        'task': 'worker.celery_worker.check_token_budgets',
        'schedule': 60.0,  # Every 60 seconds
    },
}


@celery_app.task(name='worker.celery_worker.check_token_budgets')
def check_token_budgets() -> None:
    """Periodic task to check token budget alerts for all active workflows."""
    from utils.alert_system import check_token_budget_alerts
    
    try:
        alerts = check_token_budget_alerts()
        logger.info(f"Token budget check complete: {len(alerts)} alerts generated")
    except Exception as e:
        logger.error(f"Token budget check failed: {e}")

if __name__ == "__main__":
    celery_app.start()