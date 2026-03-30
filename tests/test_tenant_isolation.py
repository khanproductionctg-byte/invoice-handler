"""
Test Tenant Isolation - Verify User A cannot see User B's data.

This test demonstrates that the tenant isolation fixes are working correctly.

IMPORTANT: This test requires a PostgreSQL database to be running.
Run: docker-compose up -d db
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import os
import sys

# Set test environment before importing app
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from db.database import Base, get_db
from db import models


# Create in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


# Now import the app after setting up the test database
from api.main import app

app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function")
def db():
    """Create fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def tenant_a(db):
    """Create Tenant A."""
    tenant = models.Tenant(
        name="Company A",
        slug="company-a",
        plan="pro"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def tenant_b(db):
    """Create Tenant B."""
    tenant = models.Tenant(
        name="Company B",
        slug="company-b",
        plan="pro"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def user_a(db, tenant_a):
    """Create User A who belongs to Tenant A."""
    user = models.User(
        email="user-a@companya.com",
        full_name="User A",
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    tenant_user = models.TenantUser(
        tenant_id=tenant_a.id,
        user_id=user.id,
        role="owner"
    )
    db.add(tenant_user)
    db.commit()
    
    return user


@pytest.fixture
def user_b(db, tenant_b):
    """Create User B who belongs to Tenant B."""
    user = models.User(
        email="user-b@companyb.com",
        full_name="User B",
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    tenant_user = models.TenantUser(
        tenant_id=tenant_b.id,
        user_id=user.id,
        role="owner"
    )
    db.add(tenant_user)
    db.commit()
    
    return user


@pytest.fixture
def token_a(user_a):
    """Create JWT token for User A."""
    from utils.auth import create_access_token
    return create_access_token(data={"sub": str(user_a.id), "email": user_a.email})


@pytest.fixture
def token_b(user_b):
    """Create JWT token for User B."""
    from utils.auth import create_access_token
    return create_access_token(data={"sub": str(user_b.id), "email": user_b.email})


@pytest.fixture
def invoice_for_tenant_a(db, tenant_a):
    """Create an invoice belonging to Tenant A."""
    invoice = models.Invoice(
        tenant_id=tenant_a.id,
        invoice_number="INV-A-001",
        vendor_name="Vendor A1",
        amount_due=1000.00,
        amount_paid=0.00,
        currency="USD",
        invoice_date=models.utc_now().date(),
        due_date=models.utc_now().date(),
        status="pending",
        source="manual"
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


@pytest.fixture
def invoice_for_tenant_b(db, tenant_b):
    """Create an invoice belonging to Tenant B."""
    invoice = models.Invoice(
        tenant_id=tenant_b.id,
        invoice_number="INV-B-001",
        vendor_name="Vendor B1",
        amount_due=2000.00,
        amount_paid=0.00,
        currency="USD",
        invoice_date=models.utc_now().date(),
        due_date=models.utc_now().date(),
        status="pending",
        source="manual"
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


class TestInvoiceTenantIsolation:
    """Test tenant isolation for invoice endpoints."""
    
    def test_user_a_cannot_see_tenant_b_invoices(self, client, token_a, invoice_for_tenant_a, invoice_for_tenant_b):
        """
        CRITICAL TEST: User A should only see Tenant A's invoices, not Tenant B's.
        
        This is the main test for the tenant isolation vulnerability fix.
        """
        response = client.get(
            "/invoices/",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        
        assert response.status_code == 200
        invoices = response.json()
        
        # User A should only see 1 invoice (their own)
        assert len(invoices) == 1
        
        # That invoice should be from Tenant A
        assert invoices[0]["invoice_number"] == "INV-A-001"
        assert invoices[0]["vendor_name"] == "Vendor A1"
        
        # User A should NOT see Tenant B's invoice
        invoice_ids = [inv["id"] for inv in invoices]
        assert invoice_for_tenant_b.id not in invoice_ids
    
    def test_user_a_cannot_access_tenant_b_invoice_directly(self, client, token_a, invoice_for_tenant_b):
        """
        User A should not be able to access Tenant B's invoice by ID.
        """
        response = client.get(
            f"/invoices/{invoice_for_tenant_b.id}",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        
        # Should return 404, not 200
        assert response.status_code == 404
    
    def test_user_a_cannot_update_tenant_b_invoice(self, client, token_a, invoice_for_tenant_b):
        """
        User A should not be able to update Tenant B's invoice.
        """
        response = client.put(
            f"/invoices/{invoice_for_tenant_b.id}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"status": "paid"}
        )
        
        # Should return 404
        assert response.status_code == 404
    
    def test_user_a_cannot_delete_tenant_b_invoice(self, client, token_a, invoice_for_tenant_b):
        """
        User A should not be able to delete Tenant B's invoice.
        """
        response = client.delete(
            f"/invoices/{invoice_for_tenant_b.id}",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        
        # Should return 404
        assert response.status_code == 404
    
    def test_user_a_can_create_and_access_own_invoice(self, client, token_a):
        """
        User A should be able to create and access their own invoices.
        """
        # Create invoice
        response = client.post(
            "/invoices/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "invoice_number": "INV-A-NEW",
                "vendor_name": "New Vendor",
                "amount_due": 500.00,
                "currency": "USD",
                "invoice_date": str(models.utc_now().date()),
                "due_date": str(models.utc_now().date()),
                "source": "manual"
            }
        )
        
        assert response.status_code == 200
        invoice = response.json()
        assert invoice["invoice_number"] == "INV-A-NEW"
        
        # Access it
        response = client.get(
            f"/invoices/{invoice['id']}",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        
        assert response.status_code == 200
        assert response.json()["invoice_number"] == "INV-A-NEW"


class TestReportTenantIsolation:
    """Test tenant isolation for report endpoints."""
    
    def test_user_cannot_access_other_tenant_report(self, client, token_a, db, tenant_a, tenant_b, user_a):
        """
        User A should not be able to access Tenant B's reports.
        """
        # Create report for Tenant B
        report = models.Report(
            tenant_id=tenant_b.id,
            report_type="monthly",
            title="Tenant B Report",
            content={"test": "data"},
            period_start=models.utc_now().date(),
            period_end=models.utc_now().date()
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        
        # Try to access as User A
        response = client.get(
            f"/reports/{report.id}",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        
        assert response.status_code == 404


class TestExpenseTenantIsolation:
    """Test tenant isolation for expense endpoints."""
    
    def test_user_cannot_access_other_tenant_expenses(self, client, token_a, db, tenant_a, tenant_b):
        """
        User A should not be able to access Tenant B's expenses.
        """
        # Create expense for Tenant B
        expense = models.Expense(
            tenant_id=tenant_b.id,
            vendor_name="Vendor B",
            amount=100.00,
            currency="USD",
            expense_date=models.utc_now().date(),
            source="manual"
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        
        # Try to access as User A
        response = client.get(
            f"/expenses/{expense.id}",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        
        assert response.status_code == 404
    
    def test_list_expenses_only_shows_own(self, client, token_a, db, tenant_a, tenant_b):
        """
        Listing expenses should only show the user's tenant's expenses.
        """
        # Create expenses for both tenants
        exp_a = models.Expense(
            tenant_id=tenant_a.id,
            vendor_name="Vendor A",
            amount=100.00,
            currency="USD",
            expense_date=models.utc_now().date(),
            source="manual"
        )
        exp_b = models.Expense(
            tenant_id=tenant_b.id,
            vendor_name="Vendor B",
            amount=200.00,
            currency="USD",
            expense_date=models.utc_now().date(),
            source="manual"
        )
        db.add(exp_a)
        db.add(exp_b)
        db.commit()
        
        # List as User A
        response = client.get(
            "/expenses/",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        
        assert response.status_code == 200
        expenses = response.json()
        
        # Should only see 1 expense (Tenant A's)
        assert len(expenses) == 1
        assert expenses[0]["vendor_name"] == "Vendor A"


class TestPaymentTenantIsolation:
    """Test tenant isolation for payment endpoints."""
    
    def test_user_cannot_access_other_tenant_payments(self, client, token_a, db, tenant_a, tenant_b):
        """
        User A should not be able to access Tenant B's payments.
        """
        # Create payment for Tenant B
        payment = models.Payment(
            tenant_id=tenant_b.id,
            payment_number="PAY-B-001",
            amount=500.00,
            currency="USD",
            payment_date=models.utc_now().date(),
            vendor_name="Vendor B",
            source="manual"
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
        
        # Try to access as User A
        response = client.get(
            f"/payments/{payment.id}",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        
        assert response.status_code == 404


class TestUnauthenticatedAccess:
    """Test that unauthenticated requests are rejected."""
    
    def test_unauthenticated_request_rejected(self, client):
        """Requests without auth token should be rejected."""
        response = client.get("/invoices/")
        assert response.status_code == 401
    
    def test_invalid_token_rejected(self, client):
        """Requests with invalid token should be rejected."""
        response = client.get(
            "/invoices/",
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
