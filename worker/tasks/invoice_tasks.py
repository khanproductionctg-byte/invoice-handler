"""
Celery tasks for invoice processing (ingestion, reconciliation, chasing, etc.).
"""
from celery import current_task
from worker.celery_worker import celery_app
from agents.ingestion_agent import IngestionAgent
from agents.reconciler_agent import ReconcilerAgent
from agents.chaser_agent import ChaserAgent
from agents.orchestrator import InvoiceHandlerOrchestrator
from agents.base_agent import AgentState
from db.database import SessionLocal
from db import models
from db.models import User, TenantUser
import logging
import time
import json
import os
from datetime import datetime

logger = logging.getLogger(__name__)

LLM_MODEL = os.getenv("LLM_MODEL", "nemotron-3-super")

# Helper function to get initialized agents
def get_ingestion_agent():
    from utils.ingestion import (
        fetch_gmail_invoices,
        fetch_drive_pdfs,
        fetch_quickbooks_invoices,
        fetch_xero_invoices,
        fetch_plaid_transactions_and_statements
    )
    tools = [
        fetch_gmail_invoices,
        fetch_drive_pdfs,
        fetch_quickbooks_invoices,
        fetch_xero_invoices,
        fetch_plaid_transactions_and_statements
    ]
    return IngestionAgent(tools)

def get_reconciler_agent():
    from langchain_community.llms import Ollama
    llm = Ollama(model=LLM_MODEL)
    from langchain_core.tools import tool
    from utils.reconciliation import reconcile_invoices
    
    @tool
    def reconcile_tool(tenant_id: int, user_id: int) -> str:
        return reconcile_invoices(tenant_id, user_id)
    
    tools = [reconcile_tool]
    return ReconcilerAgent(llm, tools)

def get_chaser_agent():
    from langchain_community.llms import Ollama
    llm = Ollama(model=LLM_MODEL)
    from langchain_core.tools import tool
    from utils.payment_chaser import chase_payments
    
    @tool
    def chase_tool(tenant_id: int, user_id: int) -> str:
        return chase_payments(tenant_id, user_id)
    
    tools = [chase_tool]
    return ChaserAgent(llm, tools)

def get_reporter_agent():
    from langchain_community.llms import Ollama
    llm = Ollama(model=LLM_MODEL)
    from langchain_core.tools import tool
    from utils.report_generator import generate_financial_report, export_report_to_excel
    from utils.alert_system import check_alert_conditions
    
    @tool
    def generate_report_tool(report_type: str, period_start: str, period_end: str, user_id: int, forecast: bool = False) -> str:
        from datetime import datetime
        start = datetime.fromisoformat(period_start).date()
        end = datetime.fromisoformat(period_end).date()
        return generate_financial_report(report_type, start, end, user_id, forecast)
    
    @tool
    def export_report_tool(report_id: int, format: str) -> str:
        return export_report_to_excel(report_id)
    
    @tool
    def check_alerts_tool(user_id: int) -> str:
        return check_alert_conditions(user_id)
    
    tools = [generate_report_tool, export_report_tool, check_alerts_tool]
    from agents.reporter_agent import ReporterAgent
    return ReporterAgent(llm, tools)


@celery_app.task(bind=True, time_limit=600, soft_time_limit=540)
def process_invoices_for_user(self, user_id: int):
    """Process invoices for a specific user - full workflow."""
    from celery.exceptions import SoftTimeLimitExceeded
    from db.models import WorkflowRun
    from agents.orchestrator import WorkflowStatus

    logger.info(f"Starting invoice processing for user {user_id}")
    invocation_id = None
    
    try:
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User with id {user_id} not found")

        tenant_user = db.query(TenantUser).filter(TenantUser.user_id == user_id).first()
        
        ingestion_agent = get_ingestion_agent()
        reconciler_agent = get_reconciler_agent()
        chaser_agent = get_chaser_agent()
        reporter_agent = get_reporter_agent()
        
        orchestrator = InvoiceHandlerOrchestrator(
            ingestion_agent=ingestion_agent,
            reconciler_agent=reconciler_agent,
            chaser_agent=chaser_agent,
            reporter_agent=reporter_agent
        )

        result_state = orchestrator.run(
            user_id=user_id,
            tenant_id=tenant_user.tenant_id if tenant_user else None,
            workflow_id=None,
            config={"task": "Process invoices for user"}
        )

        invocation_id = result_state.invocation_id
        return {"status": "completed", "invocation_id": invocation_id}

    except SoftTimeLimitExceeded:
        logger.error(f"Soft time limit exceeded for user {user_id}")
        return {"status": "timeout", "invocation_id": invocation_id}
    except Exception as e:
        logger.error(f"Error processing invoices for user {user_id}: {str(e)}")
        raise
    finally:
        if 'db' in locals():
            db.close()


@celery_app.task(bind=True, time_limit=900, soft_time_limit=840)
def reconcile_invoices_for_user(self, user_id: int):
    """Reconcile invoices for a specific user."""
    logger.info(f"Starting reconciliation for user {user_id}")

    try:
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User with id {user_id} not found")

        tenant_user = db.query(TenantUser).filter(TenantUser.user_id == user_id).first()
        if not tenant_user:
            raise ValueError(f"No tenant for user {user_id}")
        
        tenant_id = tenant_user.tenant_id
        
        reconciler_agent = get_reconciler_agent()
        
        result = reconciler_agent.run(
            tenant_id=tenant_id,
            user_id=user_id,
            config={"task": "reconciliation"}
        )

        return {"status": "completed", "tenant_id": tenant_id}

    except Exception as e:
        logger.error(f"Error reconciling for user {user_id}: {str(e)}")
        raise
    finally:
        if 'db' in locals():
            db.close()


@celery_app.task(bind=True, time_limit=600, soft_time_limit=540)
def send_payment_reminders_for_user(self, user_id: int):
    """Send payment reminders for a specific user."""
    logger.info(f"Starting payment reminders for user {user_id}")

    try:
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User with id {user_id} not found")

        tenant_user = db.query(TenantUser).filter(TenantUser.user_id == user_id).first()
        if not tenant_user:
            raise ValueError(f"No tenant for user {user_id}")
        
        tenant_id = tenant_user.tenant_id
        
        chaser_agent = get_chaser_agent()
        
        result = chaser_agent.run(
            tenant_id=tenant_id,
            user_id=user_id,
            config={"task": "payment_reminders"}
        )

        return {"status": "completed", "tenant_id": tenant_id, "reminders_sent": result.get("reminders_sent", 0)}

    except Exception as e:
        logger.error(f"Error sending reminders for user {user_id}: {str(e)}")
        raise
    finally:
        if 'db' in locals():
            db.close()


@celery_app.task(bind=True)
def daily_ingestion():
    """Daily ingestion task - runs all active tenant syncs."""
    logger.info("Starting daily ingestion")
    
    db = SessionLocal()
    try:
        tenants = db.query(models.Tenant).filter(models.Tenant.is_active == True).all()
        
        for tenant in tenants:
            try:
                ingest_tenant_chunk(tenant.id)
            except Exception as e:
                logger.error(f"Ingestion failed for tenant {tenant.id}: {e}")
        
        return {"status": "completed", "tenants": len(tenants)}
    finally:
        db.close()


def ingest_tenant_chunk(tenant_id: int):
    """Ingest data for a specific tenant."""
    from sqlalchemy import text
    
    db = SessionLocal()
    try:
        db.execute(text("SET LOCAL app.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        
        ingestion_agent = get_ingestion_agent()
        
        result = ingestion_agent.run(
            tenant_id=tenant_id,
            user_id=None,
            config={"task": "daily_ingestion"}
        )
        
        db.commit()
        return result
    finally:
        db.close()


@celery_app.task(bind=True)
def send_daily_payment_reminders():
    """Daily payment reminder task."""
    logger.info("Starting daily payment reminders")
    
    db = SessionLocal()
    try:
        tenants = db.query(models.Tenant).filter(models.Tenant.is_active == True).all()
        
        for tenant in tenants:
            try:
                users = db.query(TenantUser).filter(
                    TenantUser.tenant_id == tenant.id,
                    TenantUser.role == "owner"
                ).all()
                
                for tu in users:
                    send_payment_reminders_for_user.delay(tu.user_id)
            except Exception as e:
                logger.error(f"Reminders failed for tenant {tenant.id}: {e}")
        
        return {"status": "completed", "tenants": len(tenants)}
    finally:
        db.close()


REMINDER_TEMPLATES = {
    "friendly": """Dear {customer_name},

This is a friendly reminder that Invoice #{invoice_number} for {currency} {amount} is due on {due_date}.

Please let us know if you have any questions.

Best regards,
The Accounts Team""",
    
    "second": """Dear {customer_name},

This is a follow-up regarding Invoice #{invoice_number} for {currency} {amount} which was due on {due_date}.

Please remit payment at your earliest convenience.

Best regards,
The Accounts Team""",
    
    "urgent": """Dear {customer_name},

We regret to inform you that Invoice #{invoice_number} for {currency} {amount} is now {days_overdue} days overdue.

Please contact us immediately to resolve this matter.

Best regards,
The Accounts Team""",
    
    "final": """Dear {customer_name},

This is a final notice regarding Invoice #{invoice_number} for {currency} {amount}, now {days_overdue} days overdue.

Please remit payment immediately to avoid further action.

The Accounts Team""",
    
    "legal": """Dear {customer_name},

FINAL DEMAND FOR PAYMENT

Invoice #{invoice_number} for {currency} {amount} is significantly overdue.

Please contact us immediately to resolve this matter.

The Accounts Team"""
}
