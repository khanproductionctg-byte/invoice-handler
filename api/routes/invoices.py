"""
API routes for invoices - WITH TENANT ISOLATION.
All endpoints filter by tenant_id to ensure data isolation.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Header
from sqlalchemy.orm import Session
from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel

from db.database import get_db
from db import models
from schemas import invoice as invoice_schema
from middleware import get_current_tenant
from config.plan_limits import check_limit, HIGH_VALUE_INVOICE_THRESHOLD
from utils.mfa import is_mfa_required, is_mfa_verified
from utils.clerk_auth import decode_clerk_token


class PaginatedInvoiceResponse(BaseModel):
    data: List[Any]
    total: int
    page: int
    per_page: int
    total_pages: int

# Rate limiting
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    limiter = Limiter(key_func=get_remote_address)
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    limiter = None
    RATE_LIMITING_AVAILABLE = False

router = APIRouter(prefix="/invoices", tags=["invoices"])


def get_rate_limit_decorator(limit: str):
    """Get rate limiter decorator, or a no-op if limiter unavailable."""
    if limiter and RATE_LIMITING_AVAILABLE:
        return limiter.limit(limit)
    return lambda func: func


# Apply rate limiting decorator
create_invoice_rate_limit = get_rate_limit_decorator("60/minute")
approve_invoice_rate_limit = get_rate_limit_decorator("10/minute")
reject_invoice_rate_limit = get_rate_limit_decorator("10/minute")
list_invoices_rate_limit = get_rate_limit_decorator("100/minute")


@router.post("/", response_model=invoice_schema.Invoice)
@create_invoice_rate_limit
def create_invoice(
    request: Request,
    invoice: invoice_schema.InvoiceCreate,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Create a new invoice for the current tenant."""
    month = datetime.utcnow().strftime("%Y-%m")
    
    usage = db.query(models.UsageRecord).filter(
        models.UsageRecord.tenant_id == tenant.id,
        models.UsageRecord.month == month
    ).first()
    
    current_count = usage.invoices_processed if usage else 0
    can_proceed, msg = check_limit(tenant.plan, "invoices_per_month", current_count)
    if not can_proceed:
        raise HTTPException(status_code=402, detail=msg)
    
    db_invoice = models.Invoice(
        **invoice.model_dump(),
        tenant_id=tenant.id
    )
    db.add(db_invoice)
    
    if not usage:
        usage = models.UsageRecord(tenant_id=tenant.id, month=month, invoices_processed=1)
        db.add(usage)
    else:
        usage.invoices_processed += 1
    
    db.commit()
    db.refresh(db_invoice)
    return db_invoice


@router.get("/", response_model=PaginatedInvoiceResponse)
def read_invoices(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    vendor_name: Optional[str] = Query(None, description="Filter by vendor name"),
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Retrieve invoices for the current tenant only.
    Filters by tenant_id to ensure data isolation.
    Returns paginated response with total count and page info.
    """
    per_page = min(per_page, 100)
    
    query = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id
    )
    
    if status:
        query = query.filter(models.Invoice.status == status)
    
    if vendor_name:
        query = query.filter(models.Invoice.vendor_name.ilike(f"%{vendor_name}%"))
    
    total = query.count()
    invoices = query.order_by(
        models.Invoice.created_at.desc()
    ).offset((page - 1) * per_page).limit(per_page).all()
    
    return PaginatedInvoiceResponse(
        data=invoices,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=(total + per_page - 1) // per_page
    )


@router.get("/{invoice_id}", response_model=invoice_schema.Invoice)
def read_invoice(
    invoice_id: int,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Retrieve a specific invoice by ID.
    Only returns if the invoice belongs to the current tenant.
    """
    invoice = db.query(models.Invoice).filter(
        models.Invoice.id == invoice_id,
        models.Invoice.tenant_id == tenant.id
    ).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.put("/{invoice_id}", response_model=invoice_schema.Invoice)
def update_invoice(
    invoice_id: int,
    invoice: invoice_schema.InvoiceUpdate,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Update an invoice.
    Only allows updating invoices belonging to the current tenant.
    """
    db_invoice = db.query(models.Invoice).filter(
        models.Invoice.id == invoice_id,
        models.Invoice.tenant_id == tenant.id
    ).first()
    if db_invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    for key, value in invoice.model_dump(exclude_unset=True).items():
        setattr(db_invoice, key, value)
    
    db.commit()
    db.refresh(db_invoice)
    return db_invoice


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(
    invoice_id: int,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Delete an invoice.
    Only allows deleting invoices belonging to the current tenant.
    """
    db_invoice = db.query(models.Invoice).filter(
        models.Invoice.id == invoice_id,
        models.Invoice.tenant_id == tenant.id
    ).first()
    if db_invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    db.delete(db_invoice)
    db.commit()
    return None


@router.get("/stats/summary")
def get_invoice_summary(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Get summary statistics for invoices.
    Returns stats only for the current tenant.
    """
    total = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id
    ).count()
    
    pending = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id,
        models.Invoice.status == "pending"
    ).count()
    
    paid = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id,
        models.Invoice.status == "paid"
    ).count()
    
    overdue = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id,
        models.Invoice.status == "overdue"
    ).count()
    
    return {
        "total": total,
        "pending": pending,
        "paid": paid,
        "overdue": overdue
    }


class InvoiceApprovalRequest(BaseModel):
    action: str
    review_notes: Optional[str] = None


@router.post("/{invoice_id}/approve")
@approve_invoice_rate_limit
def approve_invoice(
    invoice_id: int,
    request: InvoiceApprovalRequest,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None)
):
    """
    Approve or reject an invoice pending review.
    
    Args:
        invoice_id: The invoice ID to approve/reject
        request: Contains action ('approve' or 'reject') and optional review_notes
    
    Returns:
        Updated invoice with new status
    """
    invoice = db.query(models.Invoice).filter(
        models.Invoice.id == invoice_id,
        models.Invoice.tenant_id == tenant.id
    ).first()
    
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice.status not in ["pending_review", "pending"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve invoice with status '{invoice.status}'"
        )
    
    # MFA check for high-value invoices
    if invoice.amount_due and invoice.amount_due >= HIGH_VALUE_INVOICE_THRESHOLD:
        if is_mfa_required():
            if authorization and authorization.startswith("Bearer "):
                token = authorization.replace("Bearer ", "")
                claims = decode_clerk_token(token, require_mfa=False)
                if claims and not is_mfa_verified(claims):
                    raise HTTPException(
                        status_code=403,
                        detail=f"MFA required for approving invoices over ${HIGH_VALUE_INVOICE_THRESHOLD}"
                    )
            else:
                raise HTTPException(
                    status_code=403,
                    detail=f"MFA required for approving invoices over ${HIGH_VALUE_INVOICE_THRESHOLD}"
                )
    
    if request.action == "approve":
        invoice.status = "approved"
    elif request.action == "reject":
        invoice.status = "rejected"
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'approve' or 'reject'")
    
    if request.review_notes:
        invoice.review_notes = request.review_notes
    
    invoice.needs_review = False
    
    db.commit()
    db.refresh(invoice)
    
    return {"status": "success", "invoice": invoice}
