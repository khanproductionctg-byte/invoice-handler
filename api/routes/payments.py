"""
API routes for payments - WITH TENANT ISOLATION.
All endpoints filter by tenant_id to ensure data isolation.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List, Optional

from db.database import get_db
from db import models
from schemas import payment as payment_schema
from middleware import get_current_tenant

# Rate limiting
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    limiter = Limiter(key_func=get_remote_address)
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    limiter = None
    RATE_LIMITING_AVAILABLE = False

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/", response_model=payment_schema.Payment)
@limiter.limit("60/minute") if RATE_LIMITING_AVAILABLE else lambda request: None
def create_payment(
    request: Request,
    payment: payment_schema.PaymentCreate,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Create a new payment for the current tenant.
    If invoice_id is provided, validates it belongs to this tenant.
    """
    if payment.invoice_id:
        invoice = db.query(models.Invoice).filter(
            models.Invoice.id == payment.invoice_id,
            models.Invoice.tenant_id == tenant.id
        ).first()
        if not invoice:
            raise HTTPException(
                status_code=400,
                detail="Invoice not found or does not belong to your organization"
            )
    
    db_payment = models.Payment(
        **payment.model_dump(),
        tenant_id=tenant.id
    )
    db.add(db_payment)
    db.commit()
    db.refresh(db_payment)
    return db_payment


@router.get("/", response_model=List[payment_schema.Payment])
def read_payments(
    skip: int = 0,
    limit: int = 100,
    invoice_id: Optional[int] = None,
    vendor_name: Optional[str] = None,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Retrieve payments for the current tenant only.
    Filters by tenant_id to ensure data isolation.
    Supports pagination with skip/limit. Maximum limit is 500.
    """
    limit = min(limit, 500)
    
    query = db.query(models.Payment).filter(
        models.Payment.tenant_id == tenant.id
    )
    
    if invoice_id is not None:
        query = query.filter(models.Payment.invoice_id == invoice_id)
    
    if vendor_name:
        query = query.filter(models.Payment.vendor_name.ilike(f"%{vendor_name}%"))
    
    payments = query.order_by(models.Payment.payment_date.desc()).offset(skip).limit(limit).all()
    return payments


@router.get("/{payment_id}", response_model=payment_schema.Payment)
def read_payment(
    payment_id: int,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Retrieve a specific payment by ID.
    Only returns if the payment belongs to the current tenant.
    """
    payment = db.query(models.Payment).filter(
        models.Payment.id == payment_id,
        models.Payment.tenant_id == tenant.id
    ).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.put("/{payment_id}", response_model=payment_schema.Payment)
def update_payment(
    payment_id: int,
    payment: payment_schema.PaymentUpdate,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Update a payment.
    Only allows updating payments belonging to the current tenant.
    If invoice_id is provided, validates it belongs to this tenant.
    """
    db_payment = db.query(models.Payment).filter(
        models.Payment.id == payment_id,
        models.Payment.tenant_id == tenant.id
    ).first()
    if db_payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    update_data = payment.model_dump(exclude_unset=True)
    
    if 'invoice_id' in update_data and update_data['invoice_id'] is not None:
        invoice = db.query(models.Invoice).filter(
            models.Invoice.id == update_data['invoice_id'],
            models.Invoice.tenant_id == tenant.id
        ).first()
        if not invoice:
            raise HTTPException(
                status_code=400,
                detail="Invoice not found or does not belong to your organization"
            )
    
    for key, value in update_data.items():
        setattr(db_payment, key, value)
    
    db.commit()
    db.refresh(db_payment)
    return db_payment


@router.delete("/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment(
    payment_id: int,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Delete a payment.
    Only allows deleting payments belonging to the current tenant.
    """
    db_payment = db.query(models.Payment).filter(
        models.Payment.id == payment_id,
        models.Payment.tenant_id == tenant.id
    ).first()
    if db_payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    db.delete(db_payment)
    db.commit()
    return None


@router.get("/unmatched/list")
def list_unmatched_payments(
    skip: int = 0,
    limit: int = 100,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Get payments that are not matched to any invoice.
    Only returns payments for the current tenant.
    """
    payments = db.query(models.Payment).filter(
        models.Payment.tenant_id == tenant.id,
        models.Payment.invoice_id.is_(None)
    ).order_by(models.Payment.payment_date.desc()).offset(skip).limit(limit).all()
    
    return payments


@router.get("/stats/summary")
def get_payment_summary(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Get summary statistics for payments.
    Returns stats only for the current tenant.
    """
    from sqlalchemy import func
    
    total = db.query(func.count(models.Payment.id)).filter(
        models.Payment.tenant_id == tenant.id
    ).scalar()
    
    total_amount = db.query(func.sum(models.Payment.amount)).filter(
        models.Payment.tenant_id == tenant.id
    ).scalar() or 0
    
    matched = db.query(func.count(models.Payment.id)).filter(
        models.Payment.tenant_id == tenant.id,
        models.Payment.invoice_id.isnot(None)
    ).scalar()
    
    unmatched = total - matched
    
    return {
        "total": total,
        "total_amount": float(total_amount),
        "matched": matched,
        "unmatched": unmatched
    }
