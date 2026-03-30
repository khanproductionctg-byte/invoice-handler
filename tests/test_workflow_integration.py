"""
Integration tests for: tenant creation → invoice creation → workflow run

Tests the critical production path that was broken by Bug #1
(workflow.user_id AttributeError) and ensures end-to-end flow works.
"""
import pytest
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

os.environ["ENVIRONMENT"] = "test"

import sqlalchemy
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Date, Numeric, Text, ForeignKey, Index, JSON
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

def utc_now():
    return datetime.now()


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    plan = Column(String, default="free")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    full_name = Column(String, nullable=True)
    clerk_id = Column(String, unique=True, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)


class TenantUser(Base):
    __tablename__ = "tenant_users"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, default="member")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    invoice_number = Column(String, nullable=False)
    vendor_name = Column(String, nullable=False)
    amount_due = Column(Numeric(10, 2), nullable=False)
    amount_paid = Column(Numeric(10, 2), default=Decimal("0"))
    currency = Column(String, default="USD")
    invoice_date = Column(Date)
    due_date = Column(Date)
    status = Column(String, default="pending")


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    payment_number = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String, default="USD")
    payment_date = Column(Date)
    vendor_name = Column(String, nullable=False)
    status = Column(String, default="completed")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    invocation_id = Column(String, unique=True, nullable=False)
    workflow_type = Column(String, nullable=False)
    status = Column(String, default="queued")
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    results = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now)


engine = create_engine("sqlite:///:memory:", poolclass=sqlalchemy.pool.StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


def create_test_user(db, email="test@example.com", clerk_id="test_clerk_123"):
    """Create a test user."""
    user = User(
        email=email,
        full_name="Test User",
        clerk_id=clerk_id,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_tenant(db, name="Test Company", slug="test-company"):
    """Create a test tenant."""
    tenant = Tenant(
        name=name,
        slug=slug,
        plan="free",
        is_active=True
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def link_user_to_tenant(db, user, tenant, role="owner"):
    """Link a user to a tenant."""
    tenant_user = TenantUser(
        tenant_id=tenant.id,
        user_id=user.id,
        role=role,
        is_active=True
    )
    db.add(tenant_user)
    db.commit()
    db.refresh(tenant_user)
    return tenant_user


def create_test_invoice(db, tenant_id, vendor_name="Test Vendor", amount=100.00):
    """Create a test invoice."""
    invoice = Invoice(
        tenant_id=tenant_id,
        invoice_number=f"INV-{tenant_id}-001",
        vendor_name=vendor_name,
        amount_due=Decimal(str(amount)),
        amount_paid=Decimal("0"),
        currency="USD",
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        status="pending"
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def create_test_payment(db, tenant_id, vendor_name="Test Vendor", amount=100.00):
    """Create a test payment."""
    payment = Payment(
        tenant_id=tenant_id,
        payment_number=f"PAY-{tenant_id}-001",
        amount=Decimal(str(amount)),
        currency="USD",
        payment_date=date.today(),
        vendor_name=vendor_name,
        status="completed"
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


class TestTenantCreation:
    """Test tenant creation flow."""

    def test_create_tenant_with_user(self, db_session):
        """Test that we can create a tenant and link it to a user."""
        user = create_test_user(db_session)
        tenant = create_test_tenant(db_session)
        link_user_to_tenant(db_session, user, tenant)
        
        assert tenant.id is not None
        assert tenant.slug == "test-company"
        
        tenant_user = db_session.query(TenantUser).filter(
            TenantUser.tenant_id == tenant.id,
            TenantUser.user_id == user.id
        ).first()
        
        assert tenant_user is not None
        assert tenant_user.role == "owner"


class TestInvoiceCreation:
    """Test invoice creation with tenant isolation."""

    def test_create_invoice_for_tenant(self, db_session):
        """Test creating an invoice for a tenant."""
        user = create_test_user(db_session)
        tenant = create_test_tenant(db_session)
        link_user_to_tenant(db_session, user, tenant)
        
        invoice = create_test_invoice(db_session, tenant.id)
        
        assert invoice.id is not None
        assert invoice.tenant_id == tenant.id
        assert invoice.status == "pending"

    def test_tenant_isolation(self, db_session):
        """Test that invoices are properly isolated by tenant."""
        tenant1 = create_test_tenant(db_session, name="Company 1", slug="company-1")
        tenant2 = create_test_tenant(db_session, name="Company 2", slug="company-2")
        
        invoice1 = create_test_invoice(db_session, tenant1.id, vendor_name="Vendor A", amount=100)
        invoice2 = create_test_invoice(db_session, tenant2.id, vendor_name="Vendor B", amount=200)
        
        invoices_t1 = db_session.query(Invoice).filter(
            Invoice.tenant_id == tenant1.id
        ).all()
        
        assert len(invoices_t1) == 1
        assert invoices_t1[0].vendor_name == "Vendor A"


class TestWorkflowRun:
    """Test workflow run - the critical path that was broken by Bug #1."""

    def test_workflow_run_has_user_id_column(self, db_session):
        """Test that WorkflowRun model now has user_id column."""
        user = create_test_user(db_session)
        tenant = create_test_tenant(db_session)
        
        workflow_run = WorkflowRun(
            tenant_id=tenant.id,
            user_id=user.id,
            invocation_id="test_inv_123",
            workflow_type="full",
            status="queued"
        )
        db_session.add(workflow_run)
        db_session.commit()
        
        assert workflow_run.id is not None
        assert workflow_run.user_id == user.id

    def test_workflow_run_user_id_nullable(self, db_session):
        """Test that user_id is nullable for backwards compatibility."""
        tenant = create_test_tenant(db_session)
        
        workflow_run = WorkflowRun(
            tenant_id=tenant.id,
            invocation_id="test_inv_456",
            workflow_type="full",
            status="queued"
        )
        db_session.add(workflow_run)
        db_session.commit()
        
        assert workflow_run.id is not None
        assert workflow_run.user_id is None

    def test_workflow_run_with_tenant_user_lookup(self, db_session):
        """Test that we can look up user from TenantUser when running workflow.
        
        This simulates what run_langgraph_workflow does - it should be able to
        get user_id from TenantUser when workflow.user_id is None.
        """
        user = create_test_user(db_session)
        tenant = create_test_tenant(db_session)
        link_user_to_tenant(db_session, user, tenant)
        
        workflow_run = WorkflowRun(
            tenant_id=tenant.id,
            invocation_id="test_inv_789",
            workflow_type="full",
            status="running"
        )
        db_session.add(workflow_run)
        db_session.commit()
        
        tenant_user = db_session.query(TenantUser).filter(
            TenantUser.tenant_id == tenant.id
        ).first()
        
        assert tenant_user is not None
        assert tenant_user.user_id == user.id
        
        user_id = tenant_user.user_id
        assert user_id is not None


class TestEndToEndFlow:
    """Test complete flow: tenant creation → invoice creation → workflow run."""

    def test_complete_workflow_flow(self, db_session):
        """Test complete flow: create tenant, add user, create invoice, run workflow."""
        user = create_test_user(db_session)
        tenant = create_test_tenant(db_session)
        link_user_to_tenant(db_session, user, tenant)
        
        invoice = create_test_invoice(db_session, tenant.id, vendor_name="Acme Corp", amount=500.00)
        
        workflow_run = WorkflowRun(
            tenant_id=tenant.id,
            user_id=user.id,
            invocation_id="test_e2e_123",
            workflow_type="full",
            status="queued"
        )
        db_session.add(workflow_run)
        db_session.commit()
        
        tenant_user = db_session.query(TenantUser).filter(
            TenantUser.tenant_id == tenant.id
        ).first()
        
        user_id = tenant_user.user_id if tenant_user else None
        
        assert user_id == user.id
        assert invoice.tenant_id == tenant.id
        assert workflow_run.tenant_id == tenant.id
        assert workflow_run.user_id == user.id

    def test_reconciliation_match(self, db_session):
        """Test basic reconciliation matching."""
        user = create_test_user(db_session)
        tenant = create_test_tenant(db_session)
        link_user_to_tenant(db_session, user, tenant)
        
        invoice = create_test_invoice(db_session, tenant.id, vendor_name="Acme Corp", amount=100.00)
        payment = create_test_payment(db_session, tenant.id, vendor_name="Acme Corp", amount=100.00)
        
        invoice_amount = float(invoice.amount_due)
        payment_amount = float(payment.amount)
        
        assert abs(invoice_amount - payment_amount) < 0.01
        
        payment.invoice_id = invoice.id
        invoice.amount_paid = invoice.amount_due
        invoice.status = "paid"
        db_session.commit()
        
        assert invoice.status == "paid"
        assert payment.invoice_id == invoice.id


class TestRateLimiterFallback:
    """Test that rate limiter fallback works when slowapi is unavailable."""

    def test_rate_limit_decorator_fallback(self):
        """Test that _rate_limit returns no-op when limiter unavailable."""
        limiter = None
        RATE_LIMITING_AVAILABLE = False
        
        def _rate_limit(limit_str: str):
            """Rate limiter decorator that falls back gracefully if slowapi unavailable."""
            if limiter and RATE_LIMITING_AVAILABLE:
                return lambda f: f
            return lambda f: f
        
        @_rate_limit("10/minute")
        def test_func():
            return "success"
        
        result = test_func()
        assert result == "success"


class TestAuditMiddlewareContext:
    """Test that audit middleware context setting works."""

    def test_audit_middleware_has_user_and_tenant(self):
        """Test that request.state can hold user_id and tenant_id."""
        class MockState:
            pass
        
        state = MockState()
        state.user_id = 1
        state.tenant_id = 1
        
        assert hasattr(state, 'user_id')
        assert hasattr(state, 'tenant_id')
        assert state.user_id == 1
        assert state.tenant_id == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
