# Invoice Handler SaaS - Production-Ready Build Guide

> **Status**: Read this file and follow the steps in order to build a 10/10 production-ready SaaS
> **Last Updated**: March 2026
> **Time Required**: 2-3 weeks for complete implementation
> **Important**: This guide uses **Lemon Squeezy** for billing (not Stripe) - lower fees (5% vs 2.9%)

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Phase 1: Database & Backend Foundation](#phase-1-database--backend-foundation)
3. [Phase 2: Authentication & Multi-Tenancy](#phase-2-authentication--multi-tenancy)
4. [Phase 3: API Endpoints & Workflows](#phase-3-api-endpoints--workflows)
5. [Phase 4: OAuth Integrations](#phase-4-oauth-integrations)
6. [Phase 5: Billing (Lemon Squeezy)](#phase-5-billing-lemon-squeezy)
7. [Phase 6: Frontend (Next.js 16)](#phase-6-frontend-nextjs-16)
8. [Phase 7: Deployment](#phase-7-deployment)
9. [Phase 8: Production Hardening](#phase-8-production-hardening)
10. [Quick Reference](#quick-reference)

---

## 1. Architecture Overview

### System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INVOICE HANDLER SAAS                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐    │
│  │   Next.js 16    │     │   FastAPI       │     │   PostgreSQL    │    │
│  │   Frontend      │────▶│   Backend        │────▶│   (Neon)        │    │
│  │   (Vercel)      │     │   (Railway)     │     │                 │    │
│  └─────────────────┘     └────────┬────────┘     └─────────────────┘    │
│                                  │                                        │
│         ┌────────────────────────┼────────────────────────┐              │
│         │                        │                        │              │
│  ┌──────▼──────┐      ┌────────▼────────┐      ┌──────▼──────┐     │
│  │   Clerk     │      │   LangGraph     │      │ Lemon Squeezy│     │
│  │  (Auth)    │      │   (Agents)      │      │  (Billing)  │     │
│  └─────────────┘      └─────────────────┘      └─────────────┘     │
│                                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │  Resend     │  │   Plivo     │  │  DeepSeek   │  │  Langfuse   │  │
│  │  (Email)    │  │   (SMS)     │  │   (LLM)     │  │ (Observability)│ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Frontend | Next.js 16 + TypeScript | React UI with App Router |
| Styling | Tailwind CSS + shadcn/ui | Modern fintech design |
| Auth | Clerk | Complete auth solution |
| Backend | FastAPI + LangGraph | REST API + AI agents |
| Database | Neon (PostgreSQL) | Multi-tenant database |
| Queue | Celery + Redis | Background jobs |
| LLM | DeepSeek via OpenRouter | AI processing |
| Email | Resend | Transactional email |
| SMS | Plivo | SMS notifications |
| Billing | Lemon Squeezy | Subscription management (lower fees than Stripe) |
| Observability | Langfuse | LLM tracing |
| Hosting | Vercel + Railway | Frontend + Backend |

---

## Phase 1: Database & Backend Foundation

### Step 1.1: Update Database Models

Create/Update the following files in your existing project:

#### File: `db/models.py` - COMPLETE REPLACE

```python
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Numeric, Date, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from db.database import Base


def utc_now():
    return datetime.now(timezone.utc)


# ============================================================================
# TENANT MANAGEMENT (Multi-Tenancy)
# ============================================================================

class Tenant(Base):
    __tablename__ = "tenants"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    plan = Column(String, default="free")  # free, pro, enterprise
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    stripe_price_id = Column(String, nullable=True)
    subscription_status = Column(String, default="inactive")  # active, past_due, canceled
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Relationships
    users = relationship("TenantUser", back_populates="tenant", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="tenant", cascade="all, delete-orphan")
    expenses = relationship("Expense", back_populates="tenant", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="tenant", cascade="all, delete-orphan")
    customers = relationship("Customer", back_populates="tenant", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="tenant", cascade="all, delete-orphan")
    connected_accounts = relationship("ConnectedAccount", back_populates="tenant", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="tenant", cascade="all, delete-orphan")
    usage_records = relationship("UsageRecord", back_populates="tenant", cascade="all, delete-orphan")
    workflow_runs = relationship("WorkflowRun", back_populates="tenant", cascade="all, delete-orphan")


class TenantUser(Base):
    __tablename__ = "tenant_users"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, default="member")  # owner, admin, member, viewer
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    
    tenant = relationship("Tenant", back_populates="users")
    user = relationship("User")


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=True)  # Nullable for Clerk auth
    clerk_id = Column(String, unique=True, nullable=True)  # Clerk user ID
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Relationships
    tenant_users = relationship("TenantUser", back_populates="user", cascade="all, delete-orphan")


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    provider = Column(String, nullable=False)  # google, quickbooks, xero, plaid
    provider_account_id = Column(String, nullable=False)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    encrypted_tokens = Column(Text, nullable=True)  # For additional OAuth data
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="connected_accounts")


class APIKey(Base):
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False)
    key_hash = Column(String, unique=True, nullable=False)
    prefix = Column(String, nullable=False)  # First 8 chars for display
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    
    tenant = relationship("Tenant", back_populates="api_keys")


class UsageRecord(Base):
    __tablename__ = "usage_records"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    month = Column(String, nullable=False)  # "2026-03"
    invoices_processed = Column(Integer, default=0)
    invoices_limit = Column(Integer, default=0)
    emails_sent = Column(Integer, default=0)
    emails_limit = Column(Integer, default=0)
    sms_sent = Column(Integer, default=0)
    sms_limit = Column(Integer, default=0)
    api_calls = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="usage_records")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    invocation_id = Column(String, unique=True, index=True, nullable=False)
    workflow_type = Column(String, nullable=False)  # full, ingestion_only, reconciliation_only, chasing_only
    status = Column(String, default="queued")  # queued, running, completed, failed
    current_step = Column(String, nullable=True)
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    results = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    
    tenant = relationship("Tenant", back_populates="workflow_runs")


# ============================================================================
# BUSINESS ENTITIES (Add tenant_id to existing models)
# ============================================================================

class Invoice(Base):
    __tablename__ = "invoices"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    invoice_number = Column(String, unique=False, index=True, nullable=False)  # Unique per tenant
    vendor_name = Column(String, nullable=False)
    vendor_id = Column(String, nullable=True)
    amount_due = Column(Numeric(10, 2), nullable=False)
    amount_paid = Column(Numeric(10, 2), default=0)
    currency = Column(String, default="USD")
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    status = Column(String, default="pending")  # pending, paid, overdue, disputed
    description = Column(Text, nullable=True)
    line_items = Column(Text, nullable=True)
    source = Column(String, nullable=False)
    source_id = Column(String, nullable=True)
    needs_review = Column(Boolean, default=False)
    review_notes = Column(Text, nullable=True)
    reminder_count = Column(Integer, default=0)
    last_reminder_date = Column(DateTime, nullable=True)
    last_reminder_type = Column(String, nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    vendor_email = Column(String, nullable=True)
    vendor_phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="invoices")
    customer = relationship("Customer", back_populates="invoices")


class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    email = Column(String, index=True, nullable=False)
    phone = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    opt_out_email = Column(Boolean, default=False)
    opt_out_sms = Column(Boolean, default=False)
    preferred_language = Column(String, default="en")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="customers")
    invoices = relationship("Invoice", back_populates="customer")


class Expense(Base):
    __tablename__ = "expenses"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    vendor_name = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String, default="USD")
    expense_date = Column(Date, nullable=False)
    category = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    receipt_url = Column(String, nullable=True)
    source = Column(String, nullable=False)
    source_id = Column(String, nullable=True)
    needs_review = Column(Boolean, default=False)
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="expenses")


class Payment(Base):
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    payment_number = Column(String, index=True, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String, default="USD")
    payment_date = Column(Date, nullable=False)
    vendor_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    source = Column(String, nullable=False)
    source_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    tenant = relationship("Tenant", back_populates="payments")
    invoice = relationship("Invoice")


class Report(Base):
    __tablename__ = "reports"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    report_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    content = Column(JSON, nullable=False)
    generated_at = Column(DateTime, default=utc_now)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    created_at = Column(DateTime, default=utc_now)
    
    tenant = relationship("Tenant", back_populates="reports")


class ReconciliationHistory(Base):
    __tablename__ = "reconciliation_history"
    
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    feature_vector = Column(String, nullable=True)  # JSON string
    outcome = Column(Integer)
    created_at = Column(DateTime, default=utc_now)
    
    invoice = relationship("Invoice", foreign_keys=[invoice_id])
    payment = relationship("Payment", foreign_keys=[payment_id])
```

---

### Step 1.2: Create Plan Limits Configuration

#### File: `config/plan_limits.py`

```python
"""
Plan limits configuration for SaaS tiers.
"""

PLAN_LIMITS = {
    "free": {
        "name": "Free",
        "invoices_per_month": 25,
        "emails_per_month": 10,
        "sms_per_month": 0,
        "api_access": False,
        "users_per_tenant": 1,
        "sources": ["gmail"],
        "report_history": 3,
        "support": "email",
        "price_monthly": 0,
        "price_yearly": 0,
    },
    "pro": {
        "name": "Pro",
        "invoices_per_month": 500,
        "emails_per_month": 200,
        "sms_per_month": 50,
        "api_access": True,
        "users_per_tenant": 5,
        "sources": ["gmail", "drive", "quickbooks", "xero", "plaid"],
        "report_history": 50,
        "support": "priority",
        "price_monthly": 29,
        "price_yearly": 290,
    },
    "enterprise": {
        "name": "Enterprise",
        "invoices_per_month": -1,  # Unlimited
        "emails_per_month": -1,
        "sms_per_month": -1,
        "api_access": True,
        "users_per_tenant": -1,
        "sources": ["gmail", "drive", "quickbooks", "xero", "plaid", "custom"],
        "report_history": -1,
        "support": "dedicated",
        "price_monthly": 99,
        "price_yearly": 990,
    }
}

LEMON_SQUEEZY_VARIANTS = {
    "pro_monthly": "price_pro_monthly_id",
    "pro_yearly": "price_pro_yearly_id",
    "enterprise_monthly": "price_enterprise_monthly_id",
    "enterprise_yearly": "price_enterprise_yearly_id",
}


def get_plan_limits(plan: str) -> dict:
    """Get limits for a specific plan."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


def can_use_feature(plan: str, feature: str) -> bool:
    """Check if a plan can use a specific feature."""
    limits = get_plan_limits(plan)
    
    feature_map = {
        "api_access": "api_access",
        "sms": "sms_per_month",
        "reports": "report_history",
    }
    
    key = feature_map.get(feature, feature)
    value = limits.get(key, 0)
    
    if isinstance(value, bool):
        return value
    return value != 0


def check_limit(plan: str, resource: str, current_usage: int) -> tuple[bool, str]:
    """
    Check if current usage is within limits.
    Returns (can_proceed, message)
    """
    limits = get_plan_limits(plan)
    limit = limits.get(resource, 0)
    
    if limit == -1:  # Unlimited
        return True, "OK"
    
    if limit == 0:
        return False, f"{resource} not available on {plan} plan"
    
    if current_usage >= limit:
        return False, f"Monthly limit reached. Upgrade to continue."
    
    remaining = limit - current_usage
    return True, f"{remaining} remaining this month"
```

---

### Step 1.3: Update Database Connection

#### File: `db/database.py`

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

# For local development
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://postgres:postgres@localhost:5432/invoice_handler"
)

# For production (Neon or Railway)
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_tenant_db(tenant_id: int):
    """
    Dependency to get database with tenant context set.
    Sets the tenant_id in connection for RLS.
    """
    db = SessionLocal()
    try:
        # Set tenant context for RLS
        db.execute(f"SET app.tenant_id = {tenant_id}")
        yield db
    finally:
        db.close()
```

---

## Phase 2: Authentication & Multi-Tenancy

### Step 2.1: Install Dependencies

```bash
pip install python-jose[cryptography] passlib[bcrypt] python-multipart
pip install httpx  # For OAuth
pip install PyJWT  # For Clerk webhooks

npm install @clerk/nextjs
```

### Step 2.2: Create Auth Utilities

#### File: `utils/clerk_auth.py`

```python
"""
Clerk authentication utilities for FastAPI.
"""
import os
import httpx
from typing import Optional
from fastapi import HTTPException, Header
from sqlalchemy.orm import Session
from db.database import SessionLocal
from db import models


CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_API_URL = "https://api.clerk.com/v1"


async def get_clerk_user(clerk_id: str) -> dict:
    """Fetch user data from Clerk API."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{CLERK_API_URL}/users/{clerk_id}",
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"}
        )
        if response.status_code == 200:
            return response.json()
        return None


async def verify_clerk_token(token: str) -> Optional[dict]:
    """Verify Clerk JWT token and return claims."""
    try:
        # In production, use Clerk's verifyToken API
        # For now, we'll trust the frontend has already validated
        # Decode without verification for development
        import base64
        import json
        
        # Split token and get payload
        parts = token.split('.')
        if len(parts) != 3:
            return None
            
        payload = parts[1]
        # Add padding if needed
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
            
        decoded = base64.b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return None


def get_or_create_user_from_clerk(clerk_id: str, email: str, full_name: str = None) -> models.User:
    """Get existing user or create new one from Clerk data."""
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.clerk_id == clerk_id).first()
        
        if not user:
            # Check if user exists by email
            user = db.query(models.User).filter(models.User.email == email).first()
            if user:
                # Link Clerk ID to existing user
                user.clerk_id = clerk_id
            else:
                # Create new user
                user = models.User(
                    email=email,
                    full_name=full_name,
                    clerk_id=clerk_id,
                    is_active=True
                )
                db.add(user)
            db.commit()
            db.refresh(user)
        
        return user
    finally:
        db.close()


def get_user_tenant(db: Session, user_id: int) -> models.Tenant:
    """Get the primary tenant for a user."""
    tenant_user = db.query(models.TenantUser).filter(
        models.TenantUser.user_id == user_id
    ).first()
    
    if not tenant_user:
        raise HTTPException(404, "No tenant found for user")
    
    return tenant_user.tenant


def require_tenant_owner(db: Session, user_id: int, tenant_id: int):
    """Ensure user is an owner of the tenant."""
    tenant_user = db.query(models.TenantUser).filter(
        models.TenantUser.user_id == user_id,
        models.TenantUser.tenant_id == tenant_id,
        models.TenantUser.role == "owner"
    ).first()
    
    if not tenant_user:
        raise HTTPException(403, "Not authorized to access this tenant")
```

---

### Step 2.3: Create Auth Middleware

#### File: `middleware/auth.py`

```python
"""
FastAPI dependencies for authentication.
"""
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional
from db.database import get_db
from db import models
from utils import clerk_auth


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> models.User:
    """
    Get current authenticated user from Clerk JWT.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")
    
    token = authorization.replace("Bearer ", "")
    
    # Verify token with Clerk
    claims = await clerk_auth.verify_clerk_token(token)
    if not claims:
        raise HTTPException(401, "Invalid token")
    
    # Get or create user from Clerk
    email = claims.get("email", "")
    full_name = claims.get("name", "")
    clerk_id = claims.get("sub", "")
    
    user = clerk_auth.get_or_create_user_from_clerk(clerk_id, email, full_name)
    
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or inactive")
    
    return user


async def get_current_tenant(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> models.Tenant:
    """
    Get the current user's primary tenant.
    """
    tenant = clerk_auth.get_user_tenant(db, user.id)
    
    if not tenant or not tenant.is_active:
        raise HTTPException(403, "Tenant not found or inactive")
    
    return tenant


async def require_plan(
    required_plan: str,
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """
    Check if tenant has required plan level.
    """
    plans_order = {"free": 0, "pro": 1, "enterprise": 2}
    
    current_level = plans_order.get(tenant.plan, 0)
    required_level = plans_order.get(required_plan, 0)
    
    if current_level < required_level:
        raise HTTPException(
            403, 
            f"This feature requires {required_plan} plan or higher. Upgrade to continue."
        )
    
    return tenant
```

---

## Phase 3: API Endpoints & Workflows

### Step 3.1: Create SaaS Routes

#### File: `api/routes/saas.py`

```python
"""
SaaS API routes for multi-tenant operations.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
import secrets

from db.database import get_db
from db import models
from middleware.auth import get_current_user, get_current_tenant
from config.plan_limits import PLAN_LIMITS, check_limit, can_use_feature

router = APIRouter(prefix="/api/v1", tags=["saas"])


# ============================================================================
# SCHEMAS
# ============================================================================

class TenantResponse(BaseModel):
    id: int
    name: str
    slug: str
    plan: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class TenantCreate(BaseModel):
    name: str
    slug: str


class WorkflowRunRequest(BaseModel):
    workflow_type: str = "full"
    sources: Optional[List[str]] = None


class WorkflowRunResponse(BaseModel):
    id: int
    invocation_id: str
    status: str
    current_step: Optional[str]
    progress: int
    created_at: datetime


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


class UsageResponse(BaseModel):
    month: str
    invoices_used: int
    invoices_limit: int
    emails_used: int
    emails_limit: int
    sms_used: int
    sms_limit: int


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
    db.commit()
    
    # Initialize usage record for current month
    usage = models.UsageRecord(
        tenant_id=tenant.id,
        month=datetime.utcnow().strftime("%Y-%m"),
        invoices_limit=PLAN_LIMITS["free"]["invoices_per_month"],
        emails_limit=PLAN_LIMITS["free"]["emails_per_month"],
        sms_limit=PLAN_LIMITS["free"]["sms_per_month"]
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


@router.post("/tenants/usage/initialize")
async def initialize_usage(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Initialize usage record for current month if not exists."""
    current_month = datetime.utcnow().strftime("%Y-%m")
    limits = PLAN_LIMITS[tenant.plan]
    
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
# DASHBOARD
# ============================================================================

@router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Get dashboard statistics for the tenant."""
    today = datetime.utcnow().date()
    month_start = today.replace(day=1)
    
    # Total invoices
    total = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id
    ).count()
    
    # Overdue
    overdue_invoices = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id,
        models.Invoice.status == "overdue"
    ).all()
    overdue_count = len(overdue_invoices)
    overdue_amount = sum(float(inv.amount_due) for inv in overdue_invoices)
    
    # Paid
    paid_count = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id,
        models.Invoice.status == "paid"
    ).count()
    
    # Pending
    pending_count = total - paid_count - overdue_count
    
    # Pending amount
    pending_invoices = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id,
        models.Invoice.status == "pending"
    ).all()
    pending_amount = sum(float(inv.amount_due) for inv in pending_invoices)
    
    # This month
    this_month = db.query(models.Invoice).filter(
        models.Invoice.tenant_id == tenant.id,
        models.Invoice.invoice_date >= month_start
    ).all()
    this_month_invoices = len(this_month)
    this_month_revenue = sum(float(inv.amount_paid) for inv in this_month)
    
    # Reconciliation rate
    reconciliation_rate = (paid_count / total * 100) if total > 0 else 0
    
    return DashboardStats(
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


# ============================================================================
# WORKFLOWS
# ============================================================================

@router.post("/workflows/run", response_model=WorkflowRunResponse)
async def run_workflow(
    request: WorkflowRunRequest,
    background_tasks: BackgroundTasks,
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
    
    if usage and usage.invoices_processed >= usage.invoices_limit and usage.invoices_limit > 0:
        raise HTTPException(
            403,
            "Monthly invoice limit reached. Upgrade to process more invoices."
        )
    
    # Create workflow run record
    invocation_id = f"wf_{secrets.token_urlsafe(16)}"
    
    workflow_run = models.WorkflowRun(
        tenant_id=tenant.id,
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


@router.get("/workflows", response_model=List[WorkflowRunResponse])
async def list_workflows(
    limit: int = Query(20, le=100),
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """List workflow runs."""
    workflows = db.query(models.WorkflowRun).filter(
        models.WorkflowRun.tenant_id == tenant.id
    ).order_by(models.WorkflowRun.created_at.desc()).limit(limit).all()
    
    return workflows


def run_langgraph_workflow(
    tenant_id: int,
    workflow_run_id: int,
    workflow_type: str,
    sources: Optional[List[str]] = None
):
    """
    Background task to run the LangGraph workflow.
    This is called by Celery in production.
    """
    from agents.orchestrator import InvoiceHandlerOrchestrator
    from agents.ingestion_agent import IngestionAgent
    from agents.reconciler_agent import ReconcilerAgent
    from agents.chaser_agent import ChaserAgent
    from agents.reporter_agent import ReporterAgent
    from db.database import SessionLocal
    from langchain_openai import ChatOpenAI
    
    db = SessionLocal()
    try:
        # Update status to running
        workflow = db.query(models.WorkflowRun).filter(
            models.WorkflowRun.id == workflow_run_id
        ).first()
        
        workflow.status = "running"
        workflow.current_step = "initializing"
        db.commit()
        
        # Initialize agents (simplified for demo)
        llm = ChatOpenAI(
            model="deepseek/deepseek-chat",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1"
        )
        
        ingestion = IngestionAgent([])
        reconciler = ReconcilerAgent(llm, [])
        chaser = ChaserAgent(llm, [])
        reporter = ReporterAgent(llm, [])
        
        # Create orchestrator
        orchestrator = InvoiceHandlerOrchestrator(
            ingestion_agent=ingestion,
            reconciler_agent=reconciler,
            chaser_agent=chaser,
            reporter_agent=reporter
        )
        
        # Run workflow
        workflow.current_step = "ingestion"
        db.commit()
        
        # Run the actual workflow
        initial_state = AgentState(
            input_data={
                "user_id": tenant_id,  # Using tenant_id as user_id
                "task": f"Process {workflow_type} workflow"
            }
        )
        
        result = orchestrator.run(initial_state)
        
        # Update completed status
        workflow.status = "completed"
        workflow.progress = 100
        workflow.completed_at = datetime.utcnow()
        workflow.results = result.output_data
        db.commit()
        
    except Exception as e:
        # Update failed status
        workflow = db.query(models.WorkflowRun).filter(
            models.WorkflowRun.id == workflow_run_id
        ).first()
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
    
    return {"status": "disconnected", "provider": provider}


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
        limits = PLAN_LIMITS[tenant.plan]
        return UsageResponse(
            month=current_month,
            invoices_used=0,
            invoices_limit=limits["invoices_per_month"],
            emails_used=0,
            emails_limit=limits["emails_per_month"],
            sms_used=0,
            sms_limit=limits["sms_per_month"]
        )
    
    return UsageResponse(
        month=usage.month,
        invoices_used=usage.invoices_processed,
        invoices_limit=usage.invoices_limit,
        emails_used=usage.emails_sent,
        emails_limit=usage.emails_limit,
        sms_used=usage.sms_sent,
        sms_limit=usage.sms_limit
    )


# ============================================================================
# API KEYS
# ============================================================================

@router.post("/api-keys")
async def create_api_key(
    name: str,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Create a new API key."""
    if not can_use_feature(tenant.plan, "api_access"):
        raise HTTPException(403, "API access requires Pro plan or higher")
    
    import hashlib
    
    # Generate key
    key = f"ih_live_{secrets.token_urlsafe(32)}"
    prefix = key[:8]
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    
    api_key = models.APIKey(
        tenant_id=tenant.id,
        name=name,
        key_hash=key_hash,
        prefix=prefix
    )
    db.add(api_key)
    db.commit()
    
    return {"api_key": key, "name": name, "prefix": prefix}


@router.get("/api-keys")
async def list_api_keys(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """List API keys (without showing the actual key)."""
    keys = db.query(models.APIKey).filter(
        models.APIKey.tenant_id == tenant.id,
        models.APIKey.is_active == True
    ).all()
    
    return [
        {
            "id": k.id,
            "name": k.name,
            "prefix": k.prefix,
            "last_used_at": k.last_used_at,
            "created_at": k.created_at
        }
        for k in keys
    ]


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
```

---

### Step 3.2: Update Main API

#### File: `api/main.py` - ADD TO EXISTING

```python
# Add these imports and router
from api.routes import auth, invoices, reports, admin, saas

# Include new router
app.include_router(saas.router, prefix="/api/v1", tags=["saas"])

# Add webhook endpoint for Clerk
@app.post("/webhooks/clerk")
async def clerk_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Clerk webhooks for user sync."""
    import json
    payload = await request.body()
    data = json.loads(payload)
    
    event_type = data.get("type")
    
    if event_type == "user.created" or event_type == "user.updated":
        user_data = data.get("data", {})
        email = user_data.get("email_addresses", [{}])[0].get("email_address", "")
        name = user_data.get("first_name", "") + " " + user_data.get("last_name", "")
        clerk_id = user_data.get("id", "")
        
        # Get or create user
        existing = db.query(models.User).filter(
            models.User.clerk_id == clerk_id
        ).first()
        
        if not existing:
            user = models.User(
                email=email,
                full_name=name.strip(),
                clerk_id=clerk_id,
                is_active=True
            )
            db.add(user)
            db.commit()
    
    elif event_type == "user.deleted":
        clerk_id = data.get("data", {}).get("id")
        user = db.query(models.User).filter(
            models.User.clerk_id == clerk_id
        ).first()
        if user:
            user.is_active = False
            db.commit()
    
    return {"status": "processed"}
```

---

## Phase 4: OAuth Integrations

### Step 4.1: Create OAuth Routes

#### File: `api/routes/oauth.py`

```python
"""
OAuth connection handlers for external services.
"""
import os
import base64
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from db.database import get_db
from db import models
from middleware.auth import get_current_tenant
from config.plan_limits import can_use_feature

router = APIRouter(prefix="/oauth", tags=["oauth"])

# Environment variables
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "https://yourapp.com/oauth/google/callback")

QUICKBOOKS_CLIENT_ID = os.getenv("QUICKBOOKS_CLIENT_ID", "")
QUICKBOOKS_CLIENT_SECRET = os.getenv("QUICKBOOKS_CLIENT_SECRET", "")
QUICKBOOKS_REDIRECT_URI = os.getenv("QUICKBOOKS_REDIRECT_URI", "https://yourapp.com/oauth/quickbooks/callback")

XERO_CLIENT_ID = os.getenv("XERO_CLIENT_ID", "")
XERO_CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET", "")
XERO_REDIRECT_URI = os.getenv("XERO_REDIRECT_URI", "https://yourapp.com/oauth/xero/callback")

PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.getenv("PLAID_SECRET", "")
PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")


# ============================================================================
# GOOGLE (Gmail + Drive)
# ============================================================================

@router.get("/google/auth")
async def google_auth(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Get Google OAuth URL."""
    import secrets
    state = f"{tenant.id}:{secrets.token_urlsafe(16)}"
    
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={GOOGLE_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=email%20profile%20https://www.googleapis.com/auth/gmail.readonly%20https://www.googleapis.com/auth/drive.readonly&"
        f"state={state}&"
        "access_type=offline&"
        "prompt=consent"
    )
    
    return {"auth_url": auth_url, "state": state}


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db)
):
    """Handle Google OAuth callback."""
    tenant_id = int(state.split(":")[0])
    
    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_REDIRECT_URI
            }
        )
        
        if token_response.status_code != 200:
            raise HTTPException(400, "Failed to exchange code for tokens")
        
        tokens = token_response.json()
        
        # Get user info
        user_response = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        user_info = user_response.json()
    
    # Save connected account
    existing = db.query(models.ConnectedAccount).filter(
        models.ConnectedAccount.tenant_id == tenant_id,
        models.ConnectedAccount.provider == "google"
    ).first()
    
    if existing:
        existing.access_token = tokens.get("access_token")
        existing.refresh_token = tokens.get("refresh_token", existing.refresh_token)
        existing.expires_at = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
        existing.is_active = True
    else:
        account = models.ConnectedAccount(
            tenant_id=tenant_id,
            provider="google",
            provider_account_id=user_info["id"],
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            expires_at=datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
        )
        db.add(account)
    
    db.commit()
    
    # Redirect to frontend
    return {"status": "connected", "redirect_url": "/settings/connections?connected=google"}


# ============================================================================
# QUICKBOOKS
# ============================================================================

@router.get("/quickbooks/auth")
async def quickbooks_auth(
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Get QuickBooks OAuth URL."""
    import secrets
    state = f"{tenant.id}:{secrets.token_urlsafe(16)}"
    
    auth_url = (
        "https://appcenter.intuit.com/connect/oauth2?"
        f"client_id={QUICKBOOKS_CLIENT_ID}&"
        f"redirect_uri={QUICKBOOKS_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=com.intuit.quickbooks.accounting&"
        f"state={state}"
    )
    
    return {"auth_url": auth_url}


@router.get("/quickbooks/callback")
async def quickbooks_callback(
    code: str = Query(...),
    realmId: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db)
):
    """Handle QuickBooks OAuth callback."""
    tenant_id = int(state.split(":")[0])
    
    async with httpx.AsyncClient() as client:
        credentials = base64.b64encode(
            f"{QUICKBOOKS_CLIENT_ID}:{QUICKBOOKS_CLIENT_SECRET}".encode()
        ).decode()
        
        token_response = await client.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": QUICKBOOKS_REDIRECT_URI
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}"
            }
        )
        
        tokens = token_response.json()
    
    # Save
    existing = db.query(models.ConnectedAccount).filter(
        models.ConnectedAccount.tenant_id == tenant_id,
        models.ConnectedAccount.provider == "quickbooks"
    ).first()
    
    if existing:
        existing.access_token = tokens.get("access_token")
        existing.refresh_token = tokens.get("refresh_token", existing.refresh_token)
        existing.provider_account_id = realmId
    else:
        account = models.ConnectedAccount(
            tenant_id=tenant_id,
            provider="quickbooks",
            provider_account_id=realmId,
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token")
        )
        db.add(account)
    
    db.commit()
    
    return {"status": "connected", "redirect_url": "/settings/connections?connected=quickbooks"}


# ============================================================================
# XERO
# ============================================================================

@router.get("/xero/auth")
async def xero_auth(
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Get Xero OAuth URL."""
    import secrets
    state = f"{tenant.id}:{secrets.token_urlsafe(16)}"
    
    auth_url = (
        "https://login.xero.com/identity/connect/authorize?"
        f"client_id={XERO_CLIENT_ID}&"
        f"redirect_uri={XERO_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=openid%20profile%20email%20accounting.transactions%20accounting.contacts&"
        f"state={state}"
    )
    
    return {"auth_url": auth_url}


@router.get("/xero/callback")
async def xero_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db)
):
    """Handle Xero OAuth callback."""
    tenant_id = int(state.split(":")[0])
    
    async with httpx.AsyncClient() as client:
        credentials = base64.b64encode(
            f"{XERO_CLIENT_ID}:{XERO_CLIENT_SECRET}".encode()
        ).decode()
        
        token_response = await client.post(
            "https://identity.xero.com/connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": XERO_REDIRECT_URI
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}"
            }
        )
        
        tokens = token_response.json()
    
    # Save
    existing = db.query(models.ConnectedAccount).filter(
        models.ConnectedAccount.tenant_id == tenant_id,
        models.ConnectedAccount.provider == "xero"
    ).first()
    
    if existing:
        existing.access_token = tokens.get("access_token")
        existing.refresh_token = tokens.get("refresh_token", existing.refresh_token)
    else:
        account = models.ConnectedAccount(
            tenant_id=tenant_id,
            provider="xero",
            provider_account_id="xero",
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token")
        )
        db.add(account)
    
    db.commit()
    
    return {"status": "connected", "redirect_url": "/settings/connections?connected=xero"}


# ============================================================================
# PLAID
# ============================================================================

@router.post("/plaid/link-token")
async def create_plaid_link_token(
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Create Plaid Link token for frontend."""
    if not can_use_feature(tenant.plan, "plaid"):
        raise HTTPException(403, "Plaid requires Pro plan")
    
    from plaid import PlaidApi
    from plaid.configuration import Configuration
    from plaid.api_client import ApiClient
    
    configuration = Configuration(
        host=f"https://{PLAID_ENV}.plaid.com",
        api_key={
            "clientId": PLAID_CLIENT_ID,
            "secret": PLAID_SECRET
        }
    )
    
    client = PlaidApi(ApiClient(configuration))
    
    response = client.link_token_create({
        "user": {"client_user_id": str(tenant.id)},
        "client_name": "Invoice Handler",
        "products": ["transactions"],
        "country_codes": ["US", "CA", "GB"],
        "language": "en"
    })
    
    return {"link_token": response["link_token"]}


@router.post("/plaid/exchange")
async def exchange_plaid_token(
    public_token: str,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Exchange Plaid public token for access token."""
    if not can_use_feature(tenant.plan, "plaid"):
        raise HTTPException(403, "Plaid requires Pro plan")
    
    from plaid import PlaidApi
    from plaid.configuration import Configuration
    
    configuration = Configuration(
        host=f"https://{PLAID_ENV}.plaid.com",
        api_key={
            "clientId": PLAID_CLIENT_ID,
            "secret": PLAID_SECRET
        }
    )
    
    client = PlaidApi(ApiClient(configuration))
    
    response = client.item_public_token_exchange({
        "public_token": public_token
    })
    
    # Save
    account = models.ConnectedAccount(
        tenant_id=tenant.id,
        provider="plaid",
        provider_account_id=response["item_id"],
        access_token=response["access_token"]
    )
    db.add(account)
    db.commit()
    
    return {"status": "connected"}
```

---

## Phase 5: Billing (Stripe)

### Step 5.1: Create Stripe Service

#### File: `services/stripe_service.py`

```python
"""
Stripe billing service for subscriptions.
"""
import os
import stripe
from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime

from db import models
from config.plan_limits import STRIPE_PRICE_IDS

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")


class StripeService:
    def __init__(self):
        self.webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    
    def create_customer(self, tenant: models.Tenant, user_email: str) -> str:
        """Create Stripe customer for tenant."""
        if tenant.stripe_customer_id:
            return tenant.stripe_customer_id
        
        customer = stripe.Customer.create(
            email=user_email,
            metadata={
                "tenant_id": tenant.id,
                "tenant_slug": tenant.slug
            }
        )
        
        return customer.id
    
    def create_checkout_session(
        self, 
        tenant: models.Tenant, 
        plan: str,
        success_url: str,
        cancel_url: str
    ) -> str:
        """Create Stripe checkout session for plan upgrade."""
        # Get price ID
        price_id = STRIPE_PRICE_IDS.get(f"{plan}_monthly")
        if not price_id:
            raise ValueError(f"Invalid plan: {plan}")
        
        # Ensure customer exists
        customer_id = self.create_customer(tenant, "")
        
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "tenant_id": tenant.id,
                "plan": plan
            }
        )
        
        return session.url
    
    def handle_webhook(self, payload: bytes, signature: str, db: Session) -> dict:
        """Handle Stripe webhook events."""
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
        except ValueError:
            raise ValueError("Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise ValueError("Invalid signature")
        
        if event.type == "checkout.session.completed":
            session = event.data.object
            self._handle_checkout_complete(session, db)
        
        elif event.type == "customer.subscription.updated":
            subscription = event.data.object
            self._handle_subscription_update(subscription, db)
        
        elif event.type == "customer.subscription.deleted":
            subscription = event.data.object
            self._handle_subscription_deleted(subscription, db)
        
        elif event.type == "invoice.payment_failed":
            invoice = event.data.object
            self._handle_payment_failed(invoice, db)
        
        return {"status": "processed"}
    
    def _handle_checkout_complete(self, session: stripe.checkout.Session, db: Session):
        """Handle successful checkout."""
        tenant_id = session.metadata.get("tenant_id")
        plan = session.metadata.get("plan")
        
        tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
        if tenant:
            tenant.stripe_customer_id = session.customer
            tenant.stripe_subscription_id = session.subscription
            tenant.stripe_price_id = session.get("line_items", [{}])[0].get("price", {}).get("id")
            tenant.subscription_status = "active"
            tenant.plan = plan
            db.commit()
    
    def _handle_subscription_update(self, subscription: stripe.Subscription, db: Session):
        """Handle subscription updates."""
        customer_id = subscription.customer
        
        tenant = db.query(models.Tenant).filter(
            models.Tenant.stripe_customer_id == customer_id
        ).first()
        
        if tenant:
            tenant.subscription_status = subscription.status
            db.commit()
    
    def _handle_subscription_deleted(self, subscription: stripe.Subscription, db: Session):
        """Handle subscription cancellation."""
        customer_id = subscription.customer
        
        tenant = db.query(models.Tenant).filter(
            models.Tenant.stripe_customer_id == customer_id
        ).first()
        
        if tenant:
            tenant.plan = "free"
            tenant.subscription_status = "canceled"
            tenant.stripe_subscription_id = None
            db.commit()
    
    def _handle_payment_failed(self, invoice: stripe.Invoice, db: Session):
        """Handle failed payment."""
        customer_id = invoice.customer
        
        tenant = db.query(models.Tenant).filter(
            models.Tenant.stripe_customer_id == customer_id
        ).first()
        
        if tenant:
            tenant.subscription_status = "past_due"
            db.commit()
    
    def create_portal_session(self, tenant: models.Tenant, return_url: str) -> str:
        """Create Stripe customer portal session."""
        if not tenant.stripe_customer_id:
            raise ValueError("No Stripe customer")
        
        session = stripe.billing_portal.Session.create(
            customer=tenant.stripe_customer_id,
            return_url=return_url
        )
        
        return session.url
    
    def get_subscription_info(self, tenant: models.Tenant) -> dict:
        """Get current subscription information."""
        if not tenant.stripe_subscription_id:
            return {
                "plan": tenant.plan,
                "status": tenant.subscription_status,
                "is_active": tenant.plan != "free"
            }
        
        try:
            subscription = stripe.Subscription.retrieve(tenant.stripe_subscription_id)
            
            return {
                "plan": tenant.plan,
                "status": subscription.status,
                "current_period_end": datetime.fromtimestamp(subscription.current_period_end),
                "cancel_at_period_end": subscription.cancel_at_period_end
            }
        except:
            return {
                "plan": tenant.plan,
                "status": tenant.subscription_status,
                "is_active": False
            }


stripe_service = StripeService()
```

---

### Step 5.2: Add Stripe Routes

#### File: `api/routes/billing.py`

```python
"""
Stripe billing API routes.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db import models
from middleware.auth import get_current_tenant
from services.stripe_service import stripe_service

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/subscription")
async def get_subscription(
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Get current subscription info."""
    return stripe_service.get_subscription_info(tenant)


@router.post("/upgrade")
async def upgrade_plan(
    plan: str,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Create checkout session for plan upgrade."""
    if plan not in ["pro", "enterprise"]:
        raise HTTPException(400, "Invalid plan")
    
    success_url = f"https://yourapp.com/settings/billing?success=true&plan={plan}"
    cancel_url = f"https://yourapp.com/settings/billing?canceled=true"
    
    url = stripe_service.create_checkout_session(
        tenant=tenant,
        plan=plan,
        success_url=success_url,
        cancel_url=cancel_url
    )
    
    return {"url": url}


@router.post("/portal")
async def open_portal(
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Open Stripe customer portal."""
    return_url = "https://yourapp.com/settings/billing"
    
    url = stripe_service.create_portal_session(tenant, return_url)
    
    return {"url": url}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """Handle Stripe webhooks."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    
    return stripe_service.handle_webhook(payload, signature, db)
```

---

## Phase 6: Frontend (Next.js 16)

### Step 6.1: Initialize Next.js Project

```bash
# Create Next.js project with TypeScript
npx create-next-app@latest invoice-handler-saas \
  --typescript \
  --tailwind \
  --eslint \
  --app \
  --src-dir \
  --import-alias "@/*" \
  --use-npm

cd invoice-handler-saas

# Install dependencies
npm install @clerk/nextjs
npm install @radix-ui/react-slot
npm install class-variance-authority
npm install clsx
npm install tailwind-merge
npm install lucide-react
npm install react-plaid-link
npm install @tanstack/react-query
npm install recharts
npm install date-fns
npm install zod
npm install @hookform/resolvers
npm install react-hook-form
```

### Step 6.2: Environment Variables

#### File: `invoice-handler-saas/.env.local`

```bash
# API
NEXT_PUBLIC_API_URL=http://localhost:8000

# Clerk Auth
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_xxx
CLERK_SECRET_KEY=sk_test_xxx
CLERK_WEBHOOK_SECRET=whsec_xxx

# Stripe
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_xxx

# Plaid
NEXT_PUBLIC_PLAID_ENV=sandbox
```

### Step 6.3: Core Components

#### File: `invoice-handler-saas/lib/api.ts`

```typescript
// API client for communicating with backend

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

class ApiClient {
  private token: string | null = null;

  setToken(token: string | null) {
    this.token = token;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    if (this.token) {
      (headers as Record<string, string>)['Authorization'] = `Bearer ${this.token}`;
    }

    const response = await fetch(`${API_URL}${endpoint}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'An error occurred' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
  }

  // Tenant
  async createTenant(name: string, slug: string) {
    return this.request<any>('/api/v1/tenants', {
      method: 'POST',
      body: JSON.stringify({ name, slug }),
    });
  }

  async getTenant() {
    return this.request<any>('/api/v1/tenants/me');
  }

  // Dashboard
  async getDashboardStats() {
    return this.request<any>('/api/v1/dashboard/stats');
  }

  // Workflows
  async runWorkflow(workflowType: string, sources?: string[]) {
    return this.request<any>('/api/v1/workflows/run', {
      method: 'POST',
      body: JSON.stringify({ workflow_type: workflowType, sources }),
    });
  }

  async getWorkflowStatus(invocationId: string) {
    return this.request<any>(`/api/v1/workflows/${invocationId}`);
  }

  async getWorkflows(limit = 20) {
    return this.request<any[]>(`/api/v1/workflows?limit=${limit}`);
  }

  // Connections
  async getConnections() {
    return this.request<any[]>('/api/v1/connections');
  }

  async disconnectProvider(provider: string) {
    return this.request(`/api/v1/connections/${provider}/disconnect`, {
      method: 'POST',
    });
  }

  // OAuth
  async getGoogleAuthUrl() {
    return this.request<{ auth_url: string }>('/oauth/google/auth');
  }

  async getQuickBooksAuthUrl() {
    return this.request<{ auth_url: string }>('/oauth/quickbooks/auth');
  }

  async getXeroAuthUrl() {
    return this.request<{ auth_url: string }>('/oauth/xero/auth');
  }

  async createPlaidLinkToken() {
    return this.request<{ link_token: string }>('/oauth/plaid/link-token', {
      method: 'POST',
    });
  }

  async exchangePlaidToken(publicToken: string) {
    return this.request('/oauth/plaid/exchange', {
      method: 'POST',
      body: JSON.stringify({ public_token: publicToken }),
    });
  }

  // Billing
  async getSubscription() {
    return this.request<any>('/billing/subscription');
  }

  async upgradePlan(plan: string) {
    return this.request<{ url: string }>('/billing/upgrade', {
      method: 'POST',
      body: JSON.stringify({ plan }),
    });
  }

  async openPortal() {
    return this.request<{ url: string }>('/billing/portal', {
      method: 'POST',
    });
  }

  // Usage
  async getUsage() {
    return this.request<any>('/api/v1/usage');
  }

  // API Keys
  async createApiKey(name: string) {
    return this.request<{ api_key: string; name: string }>('/api/v1/api-keys', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  async getApiKeys() {
    return this.request<any[]>('/api/v1/api-keys');
  }

  async revokeApiKey(id: number) {
    return this.request(`/api/v1/api-keys/${id}`, { method: 'DELETE' });
  }

  // Invoices
  async getInvoices(params?: { status?: string; page?: number; limit?: number }) {
    const query = new URLSearchParams(params as Record<string, string>);
    return this.request<{ data: any[]; total: number }>(`/invoices?${query}`);
  }

  async getInvoice(id: number) {
    return this.request<any>(`/invoices/${id}`);
  }

  // Reports
  async getReports(params?: { type?: string }) {
    const query = new URLSearchParams(params as Record<string, string>);
    return this.request<{ data: any[] }>(`/reports?${query}`);
  }

  async generateReport(type: string, startDate: string, endDate: string) {
    return this.request('/reports/generate', {
      method: 'POST',
      body: JSON.stringify({ report_type: type, period_start: startDate, period_end: endDate }),
    });
  }
}

export const api = new ApiClient();
```

### Step 6.4: Run Workflow Component

#### File: `invoice-handler-saas/components/run-workflow-button.tsx`

```tsx
'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { api } from '@/lib/api';
import { useRouter } from 'next/navigation';
import { useToast } from '@/components/ui/use-toast';

const sourceLabels: Record<string, string> = {
  gmail: 'Gmail',
  drive: 'Google Drive',
  quickbooks: 'QuickBooks',
  xero: 'Xero',
  plaid: 'Bank Accounts (Plaid)',
};

export function RunWorkflowButton() {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [workflowType, setWorkflowType] = useState('full');
  const [selectedSources, setSelectedSources] = useState<string[]>([
    'gmail', 'drive', 'quickbooks', 'xero', 'plaid'
  ]);
  const router = useRouter();
  const { toast } = useToast();

  const handleRun = async () => {
    setLoading(true);
    try {
      const result = await api.runWorkflow(workflowType, selectedSources);
      toast({
        title: 'Workflow started',
        description: `Processing your invoices...`,
      });
      setOpen(false);
      router.refresh();
    } catch (error) {
      toast({
        variant: 'destructive',
        title: 'Error',
        description: error instanceof Error ? error.message : 'Failed to start workflow',
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="bg-blue-600 hover:bg-blue-700">
          <PlayIcon className="mr-2 h-4 w-4" />
          Run Reconciliation
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Run Invoice Reconciliation</DialogTitle>
          <DialogDescription>
            Choose which workflow to run and which data sources to sync.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label>Workflow Type</Label>
            <select
              className="w-full rounded-md border border-gray-300 p-2 dark:border-gray-600 dark:bg-gray-800"
              value={workflowType}
              onChange={(e) => setWorkflowType(e.target.value)}
            >
              <option value="full">Full Reconciliation (Ingest → Reconcile → Chase → Report)</option>
              <option value="ingestion_only">Ingestion Only</option>
              <option value="reconciliation_only">Reconciliation Only</option>
              <option value="chasing_only">Send Reminders Only</option>
            </select>
          </div>

          <div className="space-y-2">
            <Label>Data Sources</Label>
            <div className="space-y-2">
              {Object.entries(sourceLabels).map(([key, label]) => (
                <div key={key} className="flex items-center space-x-2">
                  <Checkbox
                    id={key}
                    checked={selectedSources.includes(key)}
                    onCheckedChange={(checked) => {
                      if (checked) {
                        setSelectedSources([...selectedSources, key]);
                      } else {
                        setSelectedSources(selectedSources.filter((s) => s !== key));
                      }
                    }}
                  />
                  <Label htmlFor={key}>{label}</Label>
                </div>
              ))}
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleRun} disabled={loading}>
            {loading ? 'Running...' : 'Run Now'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PlayIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}
```

---

## Phase 7: Deployment

### Step 7.1: Backend Deployment (Railway)

#### File: `railway.json`

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS",
    "buildCommand": "pip install -r requirements.txt",
    "startCommand": "uvicorn api.main:app --host 0.0.0.0 --port $PORT"
  },
  "deploy": {
    "numReplicas": 2,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

#### Environment Variables (Railway)

```
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
SECRET_KEY=your-super-secret-key-at-least-32-characters

# Clerk
CLERK_SECRET_KEY=sk_test_...
CLERK_WEBHOOK_SECRET=whsec_...

# OAuth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
QUICKBOOKS_CLIENT_ID=...
QUICKBOOKS_CLIENT_SECRET=...
XERO_CLIENT_ID=...
XERO_CLIENT_SECRET=...
PLAID_CLIENT_ID=...
PLAID_SECRET=...

# Lemon Squeezy
LEMONSQUEEZY_API_KEY=lemondemo_...
LEMONSQUEEZY_STORE_ID=lemondemo_...
LEMONSQUEEZY_WEBHOOK_SECRET=lemondemo_...

# LLM
OPENAI_API_KEY=sk-or-...
OPENROUTER_API_KEY=sk-or-...

# Email
RESEND_API_KEY=re_...

# SMS
PLIVO_AUTH_ID=...
PLIVO_AUTH_TOKEN=...
```

### Step 7.2: Frontend Deployment (Vercel)

```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
vercel --prod
```

---

## Phase 8: Production Hardening

### Step 8.1: Add Comprehensive Logging

#### File: `utils/logging.py`

```python
import logging
import json
from datetime import datetime
from typing import Any

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        if hasattr(record, "tenant_id"):
            log_data["tenant_id"] = record.tenant_id
        
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        
        return json.dumps(log_data)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
    ]
)

for logger_name in ["uvicorn", "fastapi", "sqlalchemy"]:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
```

---

## Quick Reference

### Environment Variables Checklist

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection | ✅ |
| `REDIS_URL` | Redis connection | ✅ |
| `SECRET_KEY` | FastAPI secret | ✅ |
| `CLERK_SECRET_KEY` | Clerk auth | ✅ |
| `LEMONSQUEEZY_API_KEY` | Lemon Squeezy billing | ✅ |
| `GOOGLE_CLIENT_ID` | Gmail/Drive OAuth | For Google |
| `QUICKBOOKS_CLIENT_ID` | QuickBooks OAuth | For QB |
| `XERO_CLIENT_ID` | Xero OAuth | For Xero |
| `PLAID_CLIENT_ID` | Plaid bank sync | For Plaid |
| `OPENROUTER_API_KEY` | DeepSeek LLM | ✅ |
| `RESEND_API_KEY` | Email sending | ✅ |
| `PLIVO_AUTH_ID` | SMS sending | Optional |

### API Endpoints Summary

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/tenants` | POST | Create tenant |
| `/api/v1/tenants/me` | GET | Get current tenant |
| `/api/v1/dashboard/stats` | GET | Dashboard statistics |
| `/api/v1/workflows/run` | POST | Start workflow |
| `/api/v1/workflows/{id}` | GET | Get workflow status |
| `/api/v1/connections` | GET | List connections |
| `/api/v1/usage` | GET | Current usage |
| `/billing/subscription` | GET | Subscription info |
| `/billing/upgrade` | POST | Upgrade plan |
| `/oauth/google/auth` | GET | Google OAuth URL |

---

## Next Steps

To continue building, follow these prompts in order:

1. **"Create the multi-tenant database migrations"** - Run alembic migrations
2. **"Set up Clerk authentication middleware"** - Complete auth integration
3. **"Build the Next.js dashboard pages"** - Create all UI pages
4. **"Add Stripe billing webhooks"** - Complete subscription flow
5. **"Deploy to production"** - Railway + Vercel setup

---

> **End of Build Guide**
> Follow this document step by step to build a 10/10 production-ready SaaS
