"""
SaaS API routes for multi-tenant operations.
Handles: tenants, workflows, connections, usage, api-keys
"""
import secrets
import hashlib
import json
import asyncio
import os
from passlib.context import CryptContext
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Request
from fastapi.responses import StreamingResponse

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_redis_client = None

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            _redis_client = redis.from_url(redis_url, decode_responses=True)
            _redis_client.ping()
        except Exception:
            _redis_client = None
    return _redis_client
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta

from db.database import get_db
from db import models
from middleware import get_current_user, get_current_tenant, require_feature
from config.plan_limits import PLAN_LIMITS, can_use_feature, get_plan_limits

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

router = APIRouter(prefix="/api/v1", tags=["saas"])


def _rate_limit(limit_str: str):
    """Rate limiter decorator that falls back gracefully if slowapi unavailable."""
    if limiter and RATE_LIMITING_AVAILABLE:
        return limiter.limit(limit_str)
    return lambda f: f


class PaginatedResponse(BaseModel):
    """Standard paginated response for list endpoints."""
    data: List[Any]
    total: int
    page: int
    per_page: int
    total_pages: int


def paginate_query(query, page: int = 1, per_page: int = 50):
    """Paginate a SQLAlchemy query."""
    per_page = min(per_page, 100)
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return PaginatedResponse(
        data=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=(total + per_page - 1) // per_page
    )


# ============================================================================
# SCHEMAS
# ============================================================================

class TenantResponse(BaseModel):
    id: int
    name: str
    slug: str
    plan: str
    subscription_status: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class TenantCreate(BaseModel):
    name: str
    slug: str


class TenantUpdate(BaseModel):
    name: Optional[str] = None


class WorkflowRunRequest(BaseModel):
    workflow_type: str = "full"
    sources: Optional[List[str]] = None


class WorkflowRunResponse(BaseModel):
    id: int
    invocation_id: str
    workflow_type: str
    status: str
    current_step: Optional[str]
    progress: int
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    total_invoices: int
    overdue_count: int
    overdue_amount: float
    paid_count: int
    reconciliation_rate: float
    pending_count: int
    pending_amount: float
    this_month_invoices: int
    this_month_revenue: float


class ConnectionResponse(BaseModel):
    id: int
    provider: str
    is_active: bool
    connected_at: datetime
    expires_at: Optional[datetime]
    last_synced_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class UsageResponse(BaseModel):
    month: str
    invoices_used: int
    invoices_limit: int
    emails_used: int
    emails_limit: int
    sms_used: int
    sms_limit: int
    api_calls: int


class APIKeyResponse(BaseModel):
    id: int
    name: str
    prefix: str
    last_used_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


class APIKeyCreate(BaseModel):
    name: str


# ============================================================================
# TENANT MANAGEMENT
# ============================================================================

@router.post("/tenants", response_model=TenantResponse)
async def create_tenant(
    data: TenantCreate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new tenant (organization/company)."""
    # Check slug uniqueness
    existing = db.query(models.Tenant).filter(models.Tenant.slug == data.slug).first()
    if existing:
        raise HTTPException(400, "This URL is already taken. Choose another.")
    
    # Create tenant
    tenant = models.Tenant(
        name=data.name,
        slug=data.slug,
        plan="free"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    
    # Link user as owner
    tenant_user = models.TenantUser(
        tenant_id=tenant.id,
        user_id=user.id,
        role="owner"
    )
    db.add(tenant_user)
    
    # Initialize usage record
    limits = PLAN_LIMITS["free"]
    usage = models.UsageRecord(
        tenant_id=tenant.id,
        month=datetime.utcnow().strftime("%Y-%m"),
        invoices_limit=limits["invoices_per_month"],
        emails_limit=limits["emails_per_month"],
        sms_limit=limits["sms_per_month"]
    )
    db.add(usage)
    db.commit()
    
    return tenant


@router.get("/tenants/me", response_model=TenantResponse)
async def get_my_tenant(
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Get current tenant information."""
    return tenant


@router.patch("/tenants/me", response_model=TenantResponse)
async def update_my_tenant(
    data: TenantUpdate,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Update current tenant information."""
    if data.name:
        tenant.name = data.name
    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/tenants/me/limits")
async def get_tenant_limits(
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Get plan limits for current tenant."""
    return get_plan_limits(tenant.plan)


# ============================================================================
# DASHBOARD
# ============================================================================

@router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    year: int = Query(None, description="Year for historical data"),
    month: int = Query(None, description="Month for historical data")
):
    """Get dashboard statistics for the tenant - optimized with aggregate queries and caching."""
    redis_client = get_redis_client()
    
    if year and month:
        cache_key = f"dashboard:stats:{tenant.id}:{year}:{month}"
    else:
        cache_key = f"dashboard:stats:{tenant.id}"
    
    if redis_client and not (year and month):
        cached = redis_client.get(cache_key)
        if cached:
            return DashboardStats(**json.loads(cached))
    
    from sqlalchemy import func, case, cast, Float
    from calendar import monthrange
    
    today = datetime.utcnow().date()
    
    if year and month:
        target_date = datetime(year, month, 1).date()
        month_start = target_date
        _, last_day = monthrange(year, month)
        month_end = target_date.replace(day=last_day)
    else:
        month_start = today.replace(day=1)
        month_end = None
    
    # Single optimized query to get counts and amounts by status
    status_stats = db.query(
        func.count(models.Invoice.id).label('total'),
        func.sum(cast(case((models.Invoice.status == "overdue", 1), else_=0), Float)).label('overdue_count'),
        func.sum(cast(case((models.Invoice.status == "overdue", models.Invoice.amount_due), else_=0), Float)).label('overdue_amount'),
        func.sum(cast(case((models.Invoice.status == "paid", 1), else_=0), Float)).label('paid_count'),
        func.sum(cast(case((models.Invoice.status == "pending", 1), else_=0), Float)).label('pending_count'),
        func.sum(cast(case((models.Invoice.status == "pending", models.Invoice.amount_due), else_=0), Float)).label('pending_amount')
    ).filter(
        models.Invoice.tenant_id == tenant.id
    ).first()
    
    total = status_stats.total or 0
    overdue_count = int(status_stats.overdue_count or 0)
    overdue_amount = float(status_stats.overdue_amount or 0)
    paid_count = int(status_stats.paid_count or 0)
    pending_count = int(status_stats.pending_count or 0)
    pending_amount = float(status_stats.pending_amount or 0)
    
    # This month stats - single query with aggregation
    month_query = db.query(
        func.count(models.Invoice.id).label('invoice_count'),
        func.sum(cast(models.Invoice.amount_paid, Float)).label('revenue')
    ).filter(
        models.Invoice.tenant_id == tenant.id,
        models.Invoice.invoice_date >= month_start
    )
    if month_end:
        month_query = month_query.filter(models.Invoice.invoice_date <= month_end)
    month_stats = month_query.first()
    
    this_month_invoices = month_stats.invoice_count or 0
    this_month_revenue = float(month_stats.revenue or 0)
    
    # Reconciliation rate
    reconciliation_rate = (paid_count / total * 100) if total > 0 else 0
    
    result = DashboardStats(
        total_invoices=total,
        overdue_count=overdue_count,
        overdue_amount=overdue_amount,
        paid_count=paid_count,
        reconciliation_rate=round(reconciliation_rate, 1),
        pending_count=pending_count,
        pending_amount=pending_amount,
        this_month_invoices=this_month_invoices,
        this_month_revenue=this_month_revenue
    )
    
    if redis_client and not (year and month):
        try:
            redis_client.setex(cache_key, 60, result.model_dump_json())
        except Exception:
            pass
    
    return result


@router.get("/dashboard/activity")
async def get_recent_activity(
    limit: int = Query(10, le=50),
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Get recent activity for the tenant."""
    # Get recent workflow runs
    workflows = db.query(models.WorkflowRun).filter(
        models.WorkflowRun.tenant_id == tenant.id
    ).order_by(models.WorkflowRun.created_at.desc()).limit(limit).all()
    
    activities = []
    for w in workflows:
        activities.append({
            "id": w.id,
            "type": "workflow",
            "description": f"{w.workflow_type} workflow - {w.status}",
            "timestamp": w.created_at.isoformat(),
            "status": w.status
        })
    
    return activities


# ============================================================================
# WORKFLOWS
# ============================================================================

@router.post("/workflows/run", response_model=WorkflowRunResponse)
@_rate_limit("10/minute")  # 10 workflow runs per minute per IP
async def run_workflow(
    request: WorkflowRunRequest,
    background_tasks: BackgroundTasks,
    user: models.User = Depends(get_current_user),
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Start a new workflow run."""
    # Check plan limits
    current_month = datetime.utcnow().strftime("%Y-%m")
    usage = db.query(models.UsageRecord).filter(
        models.UsageRecord.tenant_id == tenant.id,
        models.UsageRecord.month == current_month
    ).first()
    
    limits = get_plan_limits(tenant.plan)
    
    if usage and usage.invoices_processed >= usage.invoices_limit and usage.invoices_limit > 0:
        raise HTTPException(
            403,
            f"Monthly invoice limit reached ({usage.invoices_limit}). Upgrade to process more."
        )
    
    # Create workflow run record
    invocation_id = f"wf_{secrets.token_urlsafe(12)}"
    
    workflow_run = models.WorkflowRun(
        tenant_id=tenant.id,
        user_id=user.id,
        invocation_id=invocation_id,
        workflow_type=request.workflow_type,
        status="queued",
        started_at=datetime.utcnow()
    )
    db.add(workflow_run)
    db.commit()
    db.refresh(workflow_run)
    
    # Queue background task
    background_tasks.add_task(
        run_langgraph_workflow,
        tenant_id=tenant.id,
        workflow_run_id=workflow_run.id,
        workflow_type=request.workflow_type,
        sources=request.sources
    )
    
    return workflow_run


@router.get("/workflows/{invocation_id}", response_model=WorkflowRunResponse)
async def get_workflow_status(
    invocation_id: str,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Get workflow run status."""
    workflow = db.query(models.WorkflowRun).filter(
        models.WorkflowRun.tenant_id == tenant.id,
        models.WorkflowRun.invocation_id == invocation_id
    ).first()
    
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    
    return workflow


@router.get("/workflows/{invocation_id}/stream")
async def stream_workflow_progress(
    invocation_id: str,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Server-Sent Events endpoint for live workflow progress."""
    async def event_generator():
        last_status = None
        while True:
            workflow = db.query(models.WorkflowRun).filter(
                models.WorkflowRun.tenant_id == tenant.id,
                models.WorkflowRun.invocation_id == invocation_id
            ).first()
            
            if not workflow:
                yield f"data: {{\"error\": \"not_found\"}}\n\n"
                break
            
            current = {
                "status": workflow.status,
                "progress": workflow.progress,
                "current_step": workflow.current_step,
                "error_message": workflow.error_message
            }
            
            if current != last_status:
                yield f"data: {json.dumps(current)}\n\n"
                last_status = current.copy()
            
            if workflow.status in ("completed", "failed", "cancelled"):
                break
            
            await asyncio.sleep(1)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/workflows", response_model=List[WorkflowRunResponse])
async def list_workflows(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=100),
    status: Optional[str] = None,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """List workflow runs with pagination."""
    query = db.query(models.WorkflowRun).filter(
        models.WorkflowRun.tenant_id == tenant.id
    )
    
    if status:
        query = query.filter(models.WorkflowRun.status == status)
    
    query = query.order_by(models.WorkflowRun.created_at.desc())
    
    total = query.count()
    workflows = query.offset((page - 1) * per_page).limit(per_page).all()
    
    return {
        "data": workflows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page
    }


def run_langgraph_workflow(
    tenant_id: int,
    workflow_run_id: int,
    workflow_type: str,
    sources: Optional[List[str]] = None
):
    """Background task to run the LangGraph workflow."""
    from db.database import SessionLocal
    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from agents.orchestrator import InvoiceHandlerOrchestrator
    from agents.ingestion_agent import IngestionAgent
    from agents.reconciler_agent import ReconcilerAgent
    from agents.chaser_agent import ChaserAgent
    from agents.reporter_agent import ReporterAgent
    from langchain_community.llms import Ollama
    from langchain_core.tools import tool
    import os
    
    db = SessionLocal()
    LLM_MODEL = os.getenv("LLM_MODEL", "nemotron-3-super")
    
    try:
        workflow = db.query(models.WorkflowRun).filter(
            models.WorkflowRun.id == workflow_run_id
        ).first()
        
        if not workflow:
            return
        
        db.execute(text("SET LOCAL app.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        
        workflow.status = "running"
        workflow.current_step = "initializing"
        workflow.progress = 5
        db.commit()
        
        # Get user_id from TenantUser relationship (workflow.user_id doesn't exist)
        user_id = None
        tenant_user = db.query(models.TenantUser).filter(
            models.TenantUser.tenant_id == tenant_id
        ).first()
        if tenant_user:
            user_id = tenant_user.user_id
        else:
            # Fallback: get first user associated with this tenant
            user = db.query(models.User).join(models.TenantUser).filter(
                models.TenantUser.tenant_id == tenant_id
            ).first()
            if user:
                user_id = user.id
        
        if user_id is None:
            raise ValueError(f"No user found for tenant {tenant_id}")
        
        llm = Ollama(model=LLM_MODEL)
        
        # Import real ingestion tools
        from utils.ingestion import (
            fetch_gmail_invoices,
            fetch_drive_pdfs,
            fetch_quickbooks_invoices,
            fetch_xero_invoices,
            fetch_plaid_transactions_and_statements
        )
        
        # Create ingestion tools with tenant context
        @tool
        def ingest_gmail(tenant_id: int = tenant_id, days_back: int = 30) -> str:
            return fetch_gmail_invoices(tenant_id, user_id, days_back)
        
        @tool
        def ingest_drive(tenant_id: int = tenant_id, days_back: int = 30) -> str:
            return fetch_drive_pdfs(tenant_id, user_id, days_back)
        
        @tool
        def ingest_quickbooks(tenant_id: int = tenant_id, days_back: int = 30) -> str:
            return fetch_quickbooks_invoices(tenant_id, user_id, days_back)
        
        @tool
        def ingest_xero(tenant_id: int = tenant_id, days_back: int = 30) -> str:
            return fetch_xero_invoices(tenant_id, user_id, days_back)
        
        @tool
        def ingest_plaid(tenant_id: int = tenant_id, days_back: int = 30) -> str:
            return fetch_plaid_transactions_and_statements(tenant_id, user_id, days_back)
        
        # Create reconciliation and chasing tools
        from utils.reconciliation import reconcile_invoices
        
        @tool
        def reconcile_tool(tenant_id: int = tenant_id) -> str:
            return reconcile_invoices(tenant_id, user_id)
        
        from utils.payment_chaser import chase_payments
        from utils.report_generator import generate_financial_report
        from utils.alert_system import check_alert_conditions
        
        @tool
        def chase_tool(tenant_id: int = tenant_id) -> str:
            return chase_payments(tenant_id, user_id)
        
        @tool
        def generate_report_tool(tenant_id: int = tenant_id) -> str:
            from datetime import date, timedelta
            from db.database import SessionLocal
            db = SessionLocal()
            try:
                end_date = date.today()
                start_date = end_date - timedelta(days=30)
                return generate_financial_report(db, tenant_id, start_date, end_date, "monthly", False)
            finally:
                db.close()
        
        @tool
        def check_alerts_tool(tenant_id: int = tenant_id) -> str:
            return check_alert_conditions(tenant_id)
        
        ingestion_tools = [ingest_gmail, ingest_drive, ingest_quickbooks, ingest_xero, ingest_plaid]
        reconciler_tools = [reconcile_tool]
        chaser_tools = [chase_tool]
        reporter_tools = [generate_report_tool, check_alerts_tool]
        
        # Create agents with real tools
        ingestion_agent = IngestionAgent(ingestion_tools)
        reconciler_agent = ReconcilerAgent(llm, reconciler_tools)
        chaser_agent = ChaserAgent(llm, chaser_tools)
        reporter_agent = ReporterAgent(llm, reporter_tools)
        
        orchestrator = InvoiceHandlerOrchestrator(
            ingestion_agent=ingestion_agent,
            reconciler_agent=reconciler_agent,
            chaser_agent=chaser_agent,
            reporter_agent=reporter_agent,
            enable_checkpoints=True,
        )
        
        workflow.current_step = "ingestion"
        workflow.progress = 20
        db.commit()
        
        result_state = orchestrator.run(
            user_id=user_id,
            tenant_id=tenant_id,
            workflow_id=str(workflow_run_id),
            config={"sources": sources or []}
        )
        
        workflow.progress = 80
        workflow.current_step = "finalizing"
        db.commit()
        
        workflow.status = "completed"
        workflow.progress = 100
        workflow.completed_at = datetime.utcnow()
        workflow.results = result_state.model_dump_json() if hasattr(result_state, 'model_dump_json') else str(result_state)
        db.commit()
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Workflow failed: {str(e)}")
        
        if 'workflow' in locals():
            workflow.status = "failed"
            workflow.error_message = str(e)
            workflow.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


# ============================================================================
# CONNECTIONS
# ============================================================================

@router.get("/connections", response_model=List[ConnectionResponse])
async def list_connections(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """List connected accounts."""
    accounts = db.query(models.ConnectedAccount).filter(
        models.ConnectedAccount.tenant_id == tenant.id,
        models.ConnectedAccount.is_active == True
    ).all()
    
    return accounts


@router.post("/connections/{provider}/disconnect")
@_rate_limit("5/minute")  # 5 disconnects per minute per IP
async def disconnect_provider(
    provider: str,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Disconnect a provider."""
    account = db.query(models.ConnectedAccount).filter(
        models.ConnectedAccount.tenant_id == tenant.id,
        models.ConnectedAccount.provider == provider
    ).first()
    
    if not account:
        raise HTTPException(404, "Connection not found")
    
    account.is_active = False
    db.commit()


# ============================================================================
# REMINDERS
# ============================================================================

class ReminderResponse(BaseModel):
    id: int
    invoice_id: int
    invoice_number: str
    customer_name: str
    amount_due: float
    currency: str
    due_date: str
    status: str
    reminder_type: Optional[str] = None
    scheduled_for: Optional[str] = None
    sent_at: Optional[str] = None

    class Config:
        from_attributes = True


class ReminderStats(BaseModel):
    pending: int
    sent_today: int
    failed: int


@router.get("/reminders", response_model=List[ReminderResponse])
async def list_reminders(
    status_filter: Optional[str] = Query(None, alias="status"),
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """List payment reminders (both pending and sent)."""
    today = datetime.utcnow().date()
    
    overdue_invoices = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id,
        models.Invoice.status == "overdue"
    ).all()
    
    pending_invoices = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id,
        models.Invoice.status == "pending",
        models.Invoice.due_date <= today + timedelta(days=7)
    ).all()
    
    invoice_ids = [inv.id for inv in overdue_invoices + pending_invoices]
    
    sent_followups = db.query(models.PaymentFollowup).filter(
        models.PaymentFollowup.tenant_id == tenant.id,
        models.PaymentFollowup.invoice_id.in_(invoice_ids) if invoice_ids else False
    ).all()
    
    sent_by_invoice = {}
    for followup in sent_followups:
        if followup.invoice_id not in sent_by_invoice:
            sent_by_invoice[followup.invoice_id] = []
        sent_by_invoice[followup.invoice_id].append(followup)
    
    reminders = []
    
    for invoice in overdue_invoices + pending_invoices:
        customer = db.query(models.Customer).filter(
            models.Customer.id == invoice.customer_id
        ).first() if invoice.customer_id else None
        
        followups = sent_by_invoice.get(invoice.id, [])
        
        if followups:
            for followup in followups:
                reminders.append(ReminderResponse(
                    id=followup.id,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    customer_name=customer.full_name if customer and customer.full_name else invoice.vendor_name,
                    amount_due=float(invoice.amount_due),
                    currency=invoice.currency,
                    due_date=invoice.due_date.isoformat() if invoice.due_date else "",
                    status="sent",
                    reminder_type=invoice.last_reminder_type,
                    scheduled_for=None,
                    sent_at=followup.sent_at.isoformat() if followup.sent_at else None
                ))
        else:
            reminder_type = "first"
            if invoice.status == "overdue":
                if invoice.reminder_count == 0:
                    reminder_type = "first"
                elif invoice.reminder_count == 1:
                    reminder_type = "second" 
                elif invoice.reminder_count == 2:
                    reminder_type = "final"
                else:
                    reminder_type = "escalation"
            
            reminders.append(ReminderResponse(
                id=-invoice.id,
                invoice_id=invoice.id,
                invoice_number=invoice.invoice_number,
                customer_name=customer.full_name if customer and customer.full_name else invoice.vendor_name,
                amount_due=float(invoice.amount_due),
                currency=invoice.currency,
                due_date=invoice.due_date.isoformat() if invoice.due_date else "",
                status="pending",
                reminder_type=reminder_type,
                scheduled_for=datetime.utcnow().isoformat(),
                sent_at=None
            ))
    
    if status_filter:
        reminders = [r for r in reminders if r.status == status_filter]
    
    return reminders


@router.get("/reminders/stats", response_model=ReminderStats)
async def get_reminder_stats(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Get reminder statistics."""
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    
    pending_count = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id,
        models.Invoice.status.in_(["overdue", "pending"]),
        models.Invoice.due_date <= today + timedelta(days=7)
    ).count()
    
    sent_today_count = db.query(models.PaymentFollowup).filter(
        models.PaymentFollowup.tenant_id == tenant.id,
        models.PaymentFollowup.sent_at >= today_start
    ).count()
    
    return ReminderStats(
        pending=pending_count,
        sent_today=sent_today_count,
        failed=0
    )


# ============================================================================
# USAGE
# ============================================================================
# USAGE
# ============================================================================

@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Get current month's usage."""
    current_month = datetime.utcnow().strftime("%Y-%m")
    
    usage = db.query(models.UsageRecord).filter(
        models.UsageRecord.tenant_id == tenant.id,
        models.UsageRecord.month == current_month
    ).first()
    
    if not usage:
        limits = get_plan_limits(tenant.plan)
        return UsageResponse(
            month=current_month,
            invoices_used=0,
            invoices_limit=limits["invoices_per_month"],
            emails_used=0,
            emails_limit=limits["emails_per_month"],
            sms_used=0,
            sms_limit=limits["sms_per_month"],
            api_calls=0
        )
    
    return UsageResponse(
        month=usage.month,
        invoices_used=usage.invoices_processed,
        invoices_limit=usage.invoices_limit,
        emails_used=usage.emails_sent,
        emails_limit=usage.emails_limit,
        sms_used=usage.sms_sent,
        sms_limit=usage.sms_limit,
        api_calls=usage.api_calls
    )


@router.post("/usage/initialize")
async def initialize_usage(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Initialize usage record for current month."""
    current_month = datetime.utcnow().strftime("%Y-%m")
    limits = get_plan_limits(tenant.plan)
    
    existing = db.query(models.UsageRecord).filter(
        models.UsageRecord.tenant_id == tenant.id,
        models.UsageRecord.month == current_month
    ).first()
    
    if not existing:
        usage = models.UsageRecord(
            tenant_id=tenant.id,
            month=current_month,
            invoices_limit=limits["invoices_per_month"],
            emails_limit=limits["emails_per_month"],
            sms_limit=limits["sms_per_month"]
        )
        db.add(usage)
        db.commit()
    
    return {"status": "initialized"}


# ============================================================================
# API KEYS
# ============================================================================

@router.post("/api-keys", response_model=dict)
@_rate_limit("3/minute")  # 3 API keys per minute per IP
async def create_api_key(
    data: APIKeyCreate,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Create a new API key."""
    if not can_use_feature(tenant.plan, "api_access"):
        raise HTTPException(403, "API access requires Pro plan or higher")
    
    # Generate key
    key = f"ih_live_{secrets.token_urlsafe(32)}"
    prefix = key[:8]
    key_hash = pwd_context.hash(key)
    
    api_key = models.APIKey(
        tenant_id=tenant.id,
        name=data.name,
        key_hash=key_hash,
        prefix=prefix
    )
    db.add(api_key)
    db.commit()
    
    return {"api_key": key, "name": data.name, "prefix": prefix}


@router.get("/api-keys", response_model=List[APIKeyResponse])
async def list_api_keys(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """List API keys (without showing the actual key)."""
    if not can_use_feature(tenant.plan, "api_access"):
        raise HTTPException(403, "API access requires Pro plan or higher")
    
    keys = db.query(models.APIKey).filter(
        models.APIKey.tenant_id == tenant.id,
        models.APIKey.is_active == True
    ).all()
    
    return keys


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Revoke an API key."""
    key = db.query(models.APIKey).filter(
        models.APIKey.id == key_id,
        models.APIKey.tenant_id == tenant.id
    ).first()
    
    if not key:
        raise HTTPException(404, "API key not found")
    
    key.is_active = False
    db.commit()
    
    return {"status": "revoked"}


# ============================================================================
# MEMBERS / TEAM
# ============================================================================

@router.get("/members")
async def list_tenant_members(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """List all members of the tenant."""
    tenant_users = db.query(models.TenantUser).filter(
        models.TenantUser.tenant_id == tenant.id,
        models.TenantUser.is_active == True
    ).all()
    
    members = []
    for tu in tenant_users:
        user = db.query(models.User).filter(models.User.id == tu.user_id).first()
        if user:
            members.append({
                "id": tu.id,
                "user_id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": tu.role,
                "joined_at": tu.created_at.isoformat()
            })
    
    return members


# ============================================================================
# GDPR COMPLIANCE
# ============================================================================

@router.get("/export")
async def export_tenant_data(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    GDPR Data Export - Export all tenant data as JSON.
    This endpoint allows users to download all their data.
    """
    try:
        export_data = {
            "export_timestamp": datetime.utcnow().isoformat(),
            "tenant": {
                "id": tenant.id,
                "name": tenant.name,
                "plan": tenant.plan,
                "created_at": tenant.created_at.isoformat()
            },
            "users": [],
            "invoices": [],
            "payments": [],
            "expenses": [],
            "customers": [],
            "connected_accounts": [],
            "workflow_runs": [],
            "reports": [],
            "audit_logs": []
        }
        
        # Export users
        tenant_users = db.query(models.TenantUser).filter(
            models.TenantUser.tenant_id == tenant.id
        ).all()
        for tu in tenant_users:
            user = db.query(models.User).filter(models.User.id == tu.user_id).first()
            if user:
                export_data["users"].append({
                    "id": user.id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": tu.role,
                    "created_at": tu.created_at.isoformat()
                })
        
        # Export invoices
        invoices = db.query(models.Invoice).filter(
            models.Invoice.tenant_id == tenant.id
        ).all()
        for inv in invoices:
            export_data["invoices"].append({
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
                "amount_due": float(inv.amount_due),
                "amount_paid": float(inv.amount_paid),
                "currency": inv.currency,
                "status": inv.status,
                "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
                "created_at": inv.created_at.isoformat()
            })
        
        # Export payments
        payments = db.query(models.Payment).filter(
            models.Payment.tenant_id == tenant.id
        ).all()
        for pay in payments:
            export_data["payments"].append({
                "id": pay.id,
                "payment_number": pay.payment_number,
                "amount": float(pay.amount),
                "currency": pay.currency,
                "payment_date": pay.payment_date.isoformat() if pay.payment_date else None,
                "vendor_name": pay.vendor_name,
                "invoice_id": pay.invoice_id,
                "created_at": pay.created_at.isoformat()
            })
        
        # Export expenses
        expenses = db.query(models.Expense).filter(
            models.Expense.tenant_id == tenant.id
        ).all()
        for exp in expenses:
            export_data["expenses"].append({
                "id": exp.id,
                "vendor_name": exp.vendor_name,
                "amount": float(exp.amount),
                "currency": exp.currency,
                "category": exp.category,
                "expense_date": exp.expense_date.isoformat() if exp.expense_date else None,
                "description": exp.description,
                "created_at": exp.created_at.isoformat()
            })
        
        # Export customers
        customers = db.query(models.Customer).filter(
            models.Customer.tenant_id == tenant.id
        ).all()
        for cust in customers:
            export_data["customers"].append({
                "id": cust.id,
                "email": cust.email,
                "full_name": cust.full_name,
                "company_name": cust.company_name,
                "created_at": cust.created_at.isoformat()
            })
        
        # Export connected accounts (without sensitive tokens)
        accounts = db.query(models.ConnectedAccount).filter(
            models.ConnectedAccount.tenant_id == tenant.id
        ).all()
        for acc in accounts:
            export_data["connected_accounts"].append({
                "id": acc.id,
                "provider": acc.provider,
                "provider_account_id": acc.provider_account_id,
                "is_active": acc.is_active,
                "last_synced_at": acc.last_synced_at.isoformat() if acc.last_synced_at else None,
                "created_at": acc.created_at.isoformat()
            })
        
        # Export workflow runs
        workflows = db.query(models.WorkflowRun).filter(
            models.WorkflowRun.tenant_id == tenant.id
        ).all()
        for wf in workflows:
            export_data["workflow_runs"].append({
                "id": wf.id,
                "workflow_type": wf.workflow_type,
                "status": wf.status,
                "progress": wf.progress,
                "created_at": wf.created_at.isoformat(),
                "completed_at": wf.completed_at.isoformat() if wf.completed_at else None
            })
        
        # Export reports
        reports = db.query(models.Report).filter(
            models.Report.tenant_id == tenant.id
        ).all()
        for rep in reports:
            export_data["reports"].append({
                "id": rep.id,
                "report_type": rep.report_type,
                "title": rep.title,
                "generated_at": rep.generated_at.isoformat()
            })
        
        # Export audit logs (limited to last 1000)
        audit_logs = db.query(models.AuditLog).filter(
            models.AuditLog.tenant_id == tenant.id
        ).order_by(models.AuditLog.created_at.desc()).limit(1000).all()
        for log in audit_logs:
            export_data["audit_logs"].append({
                "id": log.id,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "created_at": log.created_at.isoformat()
            })
        
        return export_data
        
    except Exception as e:
        raise HTTPException(500, f"Failed to export data: {str(e)}")


@router.delete("/account")
async def delete_tenant_account(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    GDPR Account Deletion - Permanently delete all tenant data.
    This action is irreversible. All data associated with the tenant
    will be permanently deleted.
    """
    try:
        tenant_id = tenant.id
        
        # Delete in order to respect foreign key constraints
        # 1. Anonymize audit logs (GDPR compliance - retain for retention period)
        db.query(models.AuditLog).filter(
            models.AuditLog.tenant_id == tenant_id
        ).update({
            "user_id": None,
            "ip_address": "anonymized",
            "user_agent": "anonymized",
            "old_values": None,
            "new_values": None
        }, synchronize_session=False)
        
        # 2. Delete payment followups
        db.query(models.PaymentFollowup).filter(
            models.PaymentFollowup.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 3. Delete reconciliation history
        db.query(models.ReconciliationHistory).filter(
            models.ReconciliationHistory.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 4. Delete Plaid transactions
        db.query(models.PlaidTransaction).filter(
            models.PlaidTransaction.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 5. Delete invoices (cascades to related records)
        db.query(models.Invoice).filter(
            models.Invoice.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 6. Delete payments
        db.query(models.Payment).filter(
            models.Payment.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 7. Delete expenses
        db.query(models.Expense).filter(
            models.Expense.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 8. Delete customers
        db.query(models.Customer).filter(
            models.Customer.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 9. Delete connected accounts
        db.query(models.ConnectedAccount).filter(
            models.ConnectedAccount.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 10. Delete workflow runs
        db.query(models.WorkflowRun).filter(
            models.WorkflowRun.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 11. Delete reports
        db.query(models.Report).filter(
            models.Report.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 12. Delete API keys
        db.query(models.APIKey).filter(
            models.APIKey.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 13. Delete usage records
        db.query(models.UsageRecord).filter(
            models.UsageRecord.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 14. Delete tenant users
        db.query(models.TenantUser).filter(
            models.TenantUser.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        
        # 15. Finally delete the tenant itself
        db.query(models.Tenant).filter(
            models.Tenant.id == tenant_id
        ).delete(synchronize_session=False)
        
        db.commit()
        
        return {
            "status": "deleted",
            "message": "All tenant data has been permanently deleted"
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Failed to delete account: {str(e)}")
