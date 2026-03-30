"""
API routes for customers - WITH TENANT ISOLATION.
All endpoints filter by tenant_id to ensure data isolation.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from db.database import get_db
from db import models
from schemas import customer as customer_schema
from middleware import get_current_tenant

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("/", response_model=customer_schema.Customer)
def create_customer(
    customer: customer_schema.CustomerCreate,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Create a new customer for the current tenant."""
    # Check if email already exists for this tenant
    existing = db.query(models.Customer).filter(
        models.Customer.tenant_id == tenant.id,
        models.Customer.email == customer.email
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Customer with this email already exists"
        )
    
    db_customer = models.Customer(
        **customer.model_dump(),
        tenant_id=tenant.id
    )
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer


@router.get("/", response_model=List[customer_schema.Customer])
def read_customers(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Retrieve customers for the current tenant only.
    Filters by tenant_id to ensure data isolation.
    Supports pagination with skip/limit. Maximum limit is 500.
    """
    limit = min(limit, 500)
    
    query = db.query(models.Customer).filter(
        models.Customer.tenant_id == tenant.id
    )
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (models.Customer.full_name.ilike(search_term)) |
            (models.Customer.company_name.ilike(search_term)) |
            (models.Customer.email.ilike(search_term))
        )
    
    customers = query.order_by(models.Customer.created_at.desc()).offset(skip).limit(limit).all()
    return customers


@router.get("/{customer_id}", response_model=customer_schema.Customer)
def read_customer(
    customer_id: int,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Retrieve a specific customer by ID.
    Only returns if the customer belongs to the current tenant.
    """
    customer = db.query(models.Customer).filter(
        models.Customer.id == customer_id,
        models.Customer.tenant_id == tenant.id
    ).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.put("/{customer_id}", response_model=customer_schema.Customer)
def update_customer(
    customer_id: int,
    customer: customer_schema.CustomerUpdate,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Update a customer.
    Only allows updating customers belonging to the current tenant.
    """
    db_customer = db.query(models.Customer).filter(
        models.Customer.id == customer_id,
        models.Customer.tenant_id == tenant.id
    ).first()
    if db_customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Check email uniqueness if changing
    if customer.email and customer.email != db_customer.email:
        existing = db.query(models.Customer).filter(
            models.Customer.tenant_id == tenant.id,
            models.Customer.email == customer.email,
            models.Customer.id != customer_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Customer with this email already exists"
            )
    
    for key, value in customer.model_dump(exclude_unset=True).items():
        setattr(db_customer, key, value)
    
    db.commit()
    db.refresh(db_customer)
    return db_customer


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: int,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Delete a customer.
    Only allows deleting customers belonging to the current tenant.
    """
    db_customer = db.query(models.Customer).filter(
        models.Customer.id == customer_id,
        models.Customer.tenant_id == tenant.id
    ).first()
    if db_customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    db.delete(db_customer)
    db.commit()
    return None


@router.get("/stats/summary")
def get_customer_summary(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Get summary statistics for customers.
    Returns stats only for the current tenant.
    """
    from sqlalchemy import func
    
    total = db.query(func.count(models.Customer.id)).filter(
        models.Customer.tenant_id == tenant.id
    ).scalar()
    
    with_email = db.query(func.count(models.Customer.id)).filter(
        models.Customer.tenant_id == tenant.id,
        models.Customer.email.isnot(None)
    ).scalar()
    
    with_phone = db.query(func.count(models.Customer.id)).filter(
        models.Customer.tenant_id == tenant.id,
        models.Customer.phone.isnot(None)
    ).scalar()
    
    opted_out_email = db.query(func.count(models.Customer.id)).filter(
        models.Customer.tenant_id == tenant.id,
        models.Customer.opt_out_email == True
    ).scalar()
    
    opted_out_sms = db.query(func.count(models.Customer.id)).filter(
        models.Customer.tenant_id == tenant.id,
        models.Customer.opt_out_sms == True
    ).scalar()
    
    return {
        "total": total,
        "with_email": with_email,
        "with_phone": with_phone,
        "opted_out_email": opted_out_email,
        "opted_out_sms": opted_out_sms
    }
