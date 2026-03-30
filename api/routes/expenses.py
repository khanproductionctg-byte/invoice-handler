"""
API routes for expenses - WITH TENANT ISOLATION.
All endpoints filter by tenant_id to ensure data isolation.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List, Optional

from db.database import get_db
from db import models
from schemas import expense as expense_schema
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

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.post("/", response_model=expense_schema.Expense)
@limiter.limit("60/minute") if RATE_LIMITING_AVAILABLE else lambda request: None
def create_expense(
    request: Request,
    expense: expense_schema.ExpenseCreate,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Create a new expense for the current tenant."""
    db_expense = models.Expense(
        **expense.model_dump(),
        tenant_id=tenant.id
    )
    db.add(db_expense)
    db.commit()
    db.refresh(db_expense)
    return db_expense


@router.get("/", response_model=List[expense_schema.Expense])
def read_expenses(
    skip: int = 0,
    limit: int = 100,
    category: Optional[str] = None,
    vendor_name: Optional[str] = None,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Retrieve expenses for the current tenant only.
    Filters by tenant_id to ensure data isolation.
    """
    query = db.query(models.Expense).filter(
        models.Expense.tenant_id == tenant.id
    )
    
    if category:
        query = query.filter(models.Expense.category == category)
    
    if vendor_name:
        query = query.filter(models.Expense.vendor_name.ilike(f"%{vendor_name}%"))
    
    expenses = query.order_by(models.Expense.created_at.desc()).offset(skip).limit(limit).all()
    return expenses


@router.get("/{expense_id}", response_model=expense_schema.Expense)
def read_expense(
    expense_id: int,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Retrieve a specific expense by ID.
    Only returns if the expense belongs to the current tenant.
    """
    expense = db.query(models.Expense).filter(
        models.Expense.id == expense_id,
        models.Expense.tenant_id == tenant.id
    ).first()
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


@router.put("/{expense_id}", response_model=expense_schema.Expense)
def update_expense(
    expense_id: int,
    expense: expense_schema.ExpenseUpdate,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Update an expense.
    Only allows updating expenses belonging to the current tenant.
    """
    db_expense = db.query(models.Expense).filter(
        models.Expense.id == expense_id,
        models.Expense.tenant_id == tenant.id
    ).first()
    if db_expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    
    for key, value in expense.model_dump(exclude_unset=True).items():
        setattr(db_expense, key, value)
    
    db.commit()
    db.refresh(db_expense)
    return db_expense


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    expense_id: int,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Delete an expense.
    Only allows deleting expenses belonging to the current tenant.
    """
    db_expense = db.query(models.Expense).filter(
        models.Expense.id == expense_id,
        models.Expense.tenant_id == tenant.id
    ).first()
    if db_expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    
    db.delete(db_expense)
    db.commit()
    return None


@router.get("/categories/list")
def list_categories(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Get list of expense categories used by this tenant.
    """
    categories = db.query(models.Expense.category).filter(
        models.Expense.tenant_id == tenant.id,
        models.Expense.category.isnot(None)
    ).distinct().all()
    
    return [c[0] for c in categories if c[0]]


@router.get("/stats/summary")
def get_expense_summary(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Get summary statistics for expenses.
    Returns stats only for the current tenant.
    """
    from sqlalchemy import func
    
    total = db.query(func.count(models.Expense.id)).filter(
        models.Expense.tenant_id == tenant.id
    ).scalar()
    
    total_amount = db.query(func.sum(models.Expense.amount)).filter(
        models.Expense.tenant_id == tenant.id
    ).scalar() or 0
    
    by_category = db.query(
        models.Expense.category,
        func.count(models.Expense.id).label('count'),
        func.sum(models.Expense.amount).label('total')
    ).filter(
        models.Expense.tenant_id == tenant.id
    ).group_by(models.Expense.category).all()
    
    return {
        "total": total,
        "total_amount": float(total_amount),
        "by_category": [
            {"category": c[0], "count": c[1], "total": float(c[2] or 0)}
            for c in by_category
        ]
    }
