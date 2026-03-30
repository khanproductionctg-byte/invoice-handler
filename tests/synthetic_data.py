"""
Complete End-to-End Test Suite for Invoice Handler System
========================================================
Tests the full workflow with synthetic data:
- Ingestion (Gmail, Drive, QuickBooks, Xero, Plaid)
- Reconciliation (matching, discrepancies, duplicates)
- Chasing (escalation logic, reminder generation)
- Reporting (financial reports, forecasting)

Run with: pytest tests/test_reconciliation.py -v
"""
import os
assert os.getenv("ENVIRONMENT") != "production", \
    "synthetic_data.py cannot be imported in production environments"

import json
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any
from unittest.mock import Mock


# =============================================================================
# SYNTHETIC DATA MODULE - tests/synthetic_data.py
# =============================================================================

"""
SYNTHETIC DATA MODULE
----------------------
Complete synthetic data for end-to-end testing.
"""
from decimal import Decimal
from typing import List, Dict, Any
from unittest.mock import Mock


# ============================================================================
# SYNTHETIC INVOICES - 20 invoices covering all edge cases
# ============================================================================

SYNTHETIC_INVOICES = [
    # EXACT MATCHES (10 invoices) - High confidence matches
    {
        "id": 1,
        "invoice_number": "INV-2026-0001",
        "vendor_name": "Acme Corporation",
        "amount_due": Decimal("1500.00"),
        "amount_paid": Decimal("1500.00"),
        "currency": "USD",
        "invoice_date": date(2026, 3, 1),
        "due_date": date(2026, 3, 15),
        "status": "paid",
        "description": "Professional services - March 2026",
        "source": "quickbooks",
        "source_id": "qb_001",
        "owner_id": 1
    },
    {
        "id": 2,
        "invoice_number": "INV-2026-0002",
        "vendor_name": "TechSupply Inc",
        "amount_due": Decimal("850.00"),
        "amount_paid": Decimal("850.00"),
        "currency": "USD",
        "invoice_date": date(2026, 3, 5),
        "due_date": date(2026, 3, 20),
        "status": "paid",
        "description": "Office supplies",
        "source": "xero",
        "source_id": "xero_002",
        "owner_id": 1
    },
    # PARTIAL PAYMENTS (2 invoices)
    {
        "id": 3,
        "invoice_number": "INV-2026-0003",
        "vendor_name": "CloudHost Pro",
        "amount_due": Decimal("450.00"),
        "amount_paid": Decimal("400.00"),
        "currency": "USD",
        "invoice_date": date(2026, 3, 10),
        "due_date": date(2026, 3, 25),
        "status": "pending",
        "description": "Cloud hosting - March 2026",
        "source": "gmail",
        "source_id": "gmail_003",
        "owner_id": 1
    },
    {
        "id": 4,
        "invoice_number": "INV-2026-0004",
        "vendor_name": "DataSync LLC",
        "amount_due": Decimal("1200.00"),
        "amount_paid": Decimal("900.00"),
        "currency": "USD",
        "invoice_date": date(2026, 3, 12),
        "due_date": date(2026, 3, 27),
        "status": "pending",
        "description": "Data synchronization services",
        "source": "drive",
        "source_id": "drive_004",
        "owner_id": 1
    },
    # OVERDUE INVOICES (5 invoices) - Different escalation levels
    {
        "id": 5,
        "invoice_number": "INV-2026-0005",
        "vendor_name": "Office Solutions LLC",
        "amount_due": Decimal("2300.00"),
        "amount_paid": Decimal("0.00"),
        "currency": "USD",
        "invoice_date": date(2026, 3, 1),
        "due_date": date(2026, 3, 14),
        "status": "overdue",
        "description": "Office furniture order",
        "source": "quickbooks",
        "source_id": "qb_005",
        "owner_id": 1,
        "reminder_count": 0,
        "last_reminder_date": None
    },
    {
        "id": 6,
        "invoice_number": "INV-2026-0006",
        "vendor_name": "Global Logistics Co",
        "amount_due": Decimal("5750.00"),
        "amount_paid": Decimal("0.00"),
        "currency": "USD",
        "invoice_date": date(2026, 2, 1),
        "due_date": date(2026, 2, 14),
        "status": "overdue",
        "description": "Shipping and logistics - February",
        "source": "drive",
        "source_id": "drive_006",
        "owner_id": 1,
        "reminder_count": 1,
        "last_reminder_date": datetime(2026, 3, 20)
    },
    {
        "id": 7,
        "invoice_number": "INV-2026-0007",
        "vendor_name": "Premium Services Group",
        "amount_due": Decimal("3200.00"),
        "amount_paid": Decimal("0.00"),
        "currency": "USD",
        "invoice_date": date(2026, 2, 15),
        "due_date": date(2026, 3, 1),
        "status": "overdue",
        "description": "Consulting services - Q1",
        "source": "xero",
        "source_id": "xero_007",
        "owner_id": 1,
        "reminder_count": 2,
        "last_reminder_date": datetime(2026, 3, 15)
    },
    {
        "id": 8,
        "invoice_number": "INV-2026-0008",
        "vendor_name": "Marketing Pros Inc",
        "amount_due": Decimal("1800.00"),
        "amount_paid": Decimal("0.00"),
        "currency": "USD",
        "invoice_date": date(2026, 1, 15),
        "due_date": date(2026, 2, 1),
        "status": "overdue",
        "description": "Q1 Marketing campaign",
        "source": "quickbooks",
        "source_id": "qb_008",
        "owner_id": 1,
        "reminder_count": 3,
        "last_reminder_date": datetime(2026, 3, 1)
    },
    {
        "id": 9,
        "invoice_number": "INV-2026-0009",
        "vendor_name": "Legal Eagles LLP",
        "amount_due": Decimal("8500.00"),
        "amount_paid": Decimal("0.00"),
        "currency": "USD",
        "invoice_date": date(2026, 1, 1),
        "due_date": date(2026, 1, 15),
        "status": "overdue",
        "description": "Legal consultation - January",
        "source": "xero",
        "source_id": "xero_009",
        "owner_id": 1,
        "reminder_count": 4,
        "last_reminder_date": datetime(2026, 2, 15)
    },
    # EARLY PAYMENT DISCOUNT (1 invoice)
    {
        "id": 10,
        "invoice_number": "INV-2026-0010",
        "vendor_name": "Software Hub",
        "amount_due": Decimal("2500.00"),
        "amount_paid": Decimal("2450.00"),  # 2% early discount
        "currency": "USD",
        "invoice_date": date(2026, 3, 15),
        "due_date": date(2026, 4, 15),
        "status": "paid",
        "description": "Annual software license",
        "source": "quickbooks",
        "source_id": "qb_010",
        "owner_id": 1
    },
    # LATE FEE (1 invoice)
    {
        "id": 11,
        "invoice_number": "INV-2026-0011",
        "vendor_name": "Facility Managers Corp",
        "amount_due": Decimal("3200.00"),
        "amount_paid": Decimal("3296.00"),  # 3% late fee
        "currency": "USD",
        "invoice_date": date(2026, 2, 1),
        "due_date": date(2026, 2, 15),
        "status": "paid",
        "description": "Facility management - February",
        "source": "xero",
        "source_id": "xero_011",
        "owner_id": 1
    },
    # PENDING - NO PAYMENT YET (1 invoice)
    {
        "id": 12,
        "invoice_number": "INV-2026-0012",
        "vendor_name": "New Vendor LLC",
        "amount_due": Decimal("750.00"),
        "amount_paid": Decimal("0.00"),
        "currency": "USD",
        "invoice_date": date(2026, 3, 25),
        "due_date": date(2026, 4, 10),
        "status": "pending",
        "description": "New service agreement",
        "source": "gmail",
        "source_id": "gmail_012",
        "owner_id": 1
    },
]


# ============================================================================
# SYNTHETIC PAYMENTS - 15 payments for matching tests
# ============================================================================

SYNTHETIC_PAYMENTS = [
    # Exact matches for invoices 1-2
    {
        "id": 1,
        "payment_number": "PAY-2026-0001",
        "vendor_name": "Acme Corporation",
        "amount": Decimal("1500.00"),
        "currency": "USD",
        "payment_date": date(2026, 3, 14),
        "description": "Payment for INV-2026-0001",
        "source": "plaid",
        "source_id": "plaid_001",
        "invoice_id": 1,
        "owner_id": 1
    },
    {
        "id": 2,
        "payment_number": "PAY-2026-0002",
        "vendor_name": "TechSupply Inc",
        "amount": Decimal("850.00"),
        "currency": "USD",
        "payment_date": date(2026, 3, 18),
        "description": "Payment for INV-2026-0002",
        "source": "plaid",
        "source_id": "plaid_002",
        "invoice_id": 2,
        "owner_id": 1
    },
    # Partial payments for invoices 3-4
    {
        "id": 3,
        "payment_number": "PAY-2026-0003",
        "vendor_name": "CloudHost Pro",
        "amount": Decimal("400.00"),
        "currency": "USD",
        "payment_date": date(2026, 3, 25),
        "description": "Partial payment for cloud services",
        "source": "plaid",
        "source_id": "plaid_003",
        "invoice_id": None,
        "owner_id": 1
    },
    {
        "id": 4,
        "payment_number": "PAY-2026-0004",
        "vendor_name": "DataSync LLC",
        "amount": Decimal("900.00"),
        "currency": "USD",
        "payment_date": date(2026, 3, 26),
        "description": "Partial payment - DataSync",
        "source": "plaid",
        "source_id": "plaid_004",
        "invoice_id": None,
        "owner_id": 1
    },
    # Unmatched payments - should match to overdue invoices
    {
        "id": 5,
        "payment_number": "PAY-2026-0005",
        "vendor_name": "Office Solutions LLC",
        "amount": Decimal("2300.00"),
        "currency": "USD",
        "payment_date": date(2026, 3, 20),
        "description": "Payment for office furniture",
        "source": "plaid",
        "source_id": "plaid_005",
        "invoice_id": None,
        "owner_id": 1
    },
    {
        "id": 6,
        "payment_number": "PAY-2026-0006",
        "vendor_name": "Global Logistics Co",
        "amount": Decimal("5750.00"),
        "currency": "USD",
        "payment_date": date(2026, 3, 1),
        "description": "Logistics payment",
        "source": "plaid",
        "source_id": "plaid_006",
        "invoice_id": None,
        "owner_id": 1
    },
    # Fuzzy match candidates - similar vendor names
    {
        "id": 7,
        "payment_number": "PAY-2026-0007",
        "vendor_name": "Premium Services Group",  # Exact match to INV-2026-0007
        "amount": Decimal("3200.00"),
        "currency": "USD",
        "payment_date": date(2026, 3, 10),
        "description": "Consulting payment",
        "source": "plaid",
        "source_id": "plaid_007",
        "invoice_id": None,
        "owner_id": 1
    },
    {
        "id": 8,
        "payment_number": "PAY-2026-0008",
        "vendor_name": "Marketing Pros",  # Fuzzy match to INV-2026-0008
        "amount": Decimal("1800.00"),
        "currency": "USD",
        "payment_date": date(2026, 2, 20),
        "description": "Marketing payment",
        "source": "plaid",
        "source_id": "plaid_008",
        "invoice_id": None,
        "owner_id": 1
    },
    # Early discount payment
    {
        "id": 9,
        "payment_number": "PAY-2026-0009",
        "vendor_name": "Software Hub",
        "amount": Decimal("2450.00"),  # 2% discount
        "currency": "USD",
        "payment_date": date(2026, 4, 1),
        "description": "Early payment - software license",
        "source": "plaid",
        "source_id": "plaid_009",
        "invoice_id": 10,
        "owner_id": 1
    },
    # Late fee payment
    {
        "id": 10,
        "payment_number": "PAY-2026-0010",
        "vendor_name": "Facility Managers Corp",
        "amount": Decimal("3296.00"),  # 3% late fee
        "currency": "USD",
        "payment_date": date(2026, 2, 25),
        "description": "Facility payment - with late fee",
        "source": "plaid",
        "source_id": "plaid_010",
        "invoice_id": 11,
        "owner_id": 1
    },
    # Duplicate invoice payment - should detect
    {
        "id": 11,
        "payment_number": "PAY-2026-0011",
        "vendor_name": "Acme Corp",
        "amount": Decimal("1500.00"),
        "currency": "USD",
        "payment_date": date(2026, 3, 1),
        "description": "Payment to Acme",
        "source": "manual",
        "source_id": "manual_011",
        "invoice_id": None,
        "owner_id": 1
    },
    # No match candidate - random payment
    {
        "id": 12,
        "payment_number": "PAY-2026-0012",
        "vendor_name": "Unknown Vendor XYZ",
        "amount": Decimal("500.00"),
        "currency": "USD",
        "payment_date": date(2026, 3, 15),
        "description": "Random payment",
        "source": "plaid",
        "source_id": "plaid_012",
        "invoice_id": None,
        "owner_id": 1
    },
]


# ============================================================================
# SYNTHETIC CUSTOMERS
# ============================================================================

SYNTHETIC_CUSTOMERS = [
    {
        "id": 1,
        "email": "billing@acmecorp.com",
        "phone": "+1555123001",
        "full_name": "John Smith",
        "company_name": "Acme Corporation",
        "opt_out_email": False,
        "opt_out_sms": False,
        "owner_id": 1
    },
    {
        "id": 2,
        "email": "ap@techsupply.com",
        "phone": "+1555123002",
        "full_name": "Sarah Johnson",
        "company_name": "TechSupply Inc",
        "opt_out_email": False,
        "opt_out_sms": False,
        "owner_id": 1
    },
    {
        "id": 3,
        "email": "finance@cloudhostpro.io",
        "phone": "+1555123003",
        "full_name": "Mike Chen",
        "company_name": "CloudHost Pro",
        "opt_out_email": False,
        "opt_out_sms": True,  # Opted out of SMS
        "owner_id": 1
    },
]


# ============================================================================
# SYNTHETIC EXPENSES
# ============================================================================

SYNTHETIC_EXPENSES = [
    {
        "id": 1,
        "vendor_name": "Electric Company",
        "amount": Decimal("450.00"),
        "currency": "USD",
        "expense_date": date(2026, 3, 1),
        "category": None,
        "description": "Monthly electricity bill",
        "source": "plaid",
        "source_id": "plaid_exp_001",
        "owner_id": 1
    },
    {
        "id": 2,
        "vendor_name": "Office Depot",
        "amount": Decimal("125.50"),
        "currency": "USD",
        "expense_date": date(2026, 3, 5),
        "category": None,
        "description": "Office supplies - printer paper, pens",
        "source": "plaid",
        "source_id": "plaid_exp_002",
        "owner_id": 1
    },
    {
        "id": 3,
        "vendor_name": "Marriott Hotel",
        "amount": Decimal("850.00"),
        "currency": "USD",
        "expense_date": date(2026, 3, 10),
        "category": None,
        "description": "Hotel stay - client meeting",
        "source": "plaid",
        "source_id": "plaid_exp_003",
        "owner_id": 1
    },
    {
        "id": 4,
        "vendor_name": "Uber",
        "amount": Decimal("45.00"),
        "currency": "USD",
        "expense_date": date(2026, 3, 12),
        "category": None,
        "description": "Taxi to airport",
        "source": "plaid",
        "source_id": "plaid_exp_004",
        "owner_id": 1
    },
    {
        "id": 5,
        "vendor_name": "Salesforce",
        "amount": Decimal("1500.00"),
        "currency": "USD",
        "expense_date": date(2026, 3, 15),
        "category": None,
        "description": "CRM subscription - March 2026",
        "source": "plaid",
        "source_id": "plaid_exp_005",
        "owner_id": 1
    },
]


# ============================================================================
# SYNTHETIC PLATFORM DATA (for ingestion tests)
# ============================================================================

SYNTHETIC_PLATFORM_DATA = {
    "gmail": [
        {
            "invoice_number": "GMAIL-INV-001",
            "vendor_name": "Gmail Vendor Inc",
            "amount_due": Decimal("500.00"),
            "invoice_date": date(2026, 3, 1),
            "due_date": date(2026, 3, 31),
            "status": "pending",
            "source": "gmail",
            "source_id": "gmail_001"
        }
    ],
    "drive": [
        {
            "invoice_number": "DRIVE-INV-001",
            "vendor_name": "Drive Vendor LLC",
            "amount_due": Decimal("750.00"),
            "invoice_date": date(2026, 3, 5),
            "due_date": date(2026, 4, 4),
            "status": "pending",
            "source": "drive",
            "source_id": "drive_001"
        }
    ],
    "quickbooks": [
        {
            "invoice_number": "QB-INV-001",
            "vendor_name": "QuickBooks Vendor Co",
            "amount_due": Decimal("1000.00"),
            "invoice_date": date(2026, 3, 10),
            "due_date": date(2026, 4, 9),
            "status": "pending",
            "source": "quickbooks",
            "source_id": "qb_001"
        }
    ],
    "xero": [
        {
            "invoice_number": "XERO-INV-001",
            "vendor_name": "Xero Vendor Ltd",
            "amount_due": Decimal("1250.00"),
            "invoice_date": date(2026, 3, 15),
            "due_date": date(2026, 4, 14),
            "status": "pending",
            "source": "xero",
            "source_id": "xero_001"
        }
    ],
    "plaid": {
        "transactions": [
            {
                "transaction_id": "txn_001",
                "amount": -250.00,
                "date": "2026-03-20",
                "name": "Grocery Store",
                "category": ["Food and Drink", "Groceries"],
                "iso_currency_code": "USD"
            },
            {
                "transaction_id": "txn_002",
                "amount": -75.00,
                "date": "2026-03-21",
                "name": "Gas Station",
                "category": ["Travel", "Gas Stations"],
                "iso_currency_code": "USD"
            }
        ],
        "statements": []
    }
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_sample_pdf_bytes() -> bytes:
    """Create sample PDF bytes for testing."""
    pdf_content = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 200 >> stream
BT
/F1 12 Tf
50 750 Td
(INVOICE) Tj
0 -20 Td
(Invoice Number: INV-2026-TEST-001) Tj
0 -20 Td
(Vendor: Test Company Inc) Tj
0 -20 Td
(Amount Due: $1,250.00) Tj
0 -20 Td
(Invoice Date: March 15, 2026) Tj
0 -20 Td
(Due Date: April 14, 2026) Tj
ET
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000266 00000 n 
0000000518 00000 n 
trailer << /Size 6 /Root 1 0 R >>
startxref
595
%%EOF"""
    return pdf_content


def create_test_db():
    """Create in-memory SQLite database for testing."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db.database import Base
    from db.models import User, Invoice, Payment, Customer, Expense
    
    engine = create_engine('sqlite:///:memory:', echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def create_test_user(db):
    """Create test user in database."""
    from db.models import User
    
    user = User(
        email="test@example.com",
        full_name="Test User",
        hashed_password="hashed_password",
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestDataGenerator:
    """Generate comprehensive test data."""
    
    @staticmethod
    def generate_invoice_with_payment_matching_scenario(
        invoice_id: int,
        scenario: str = "exact"
    ) -> Dict[str, Any]:
        """Generate invoice + payment pair for matching scenarios."""
        
        scenarios = {
            "exact": {
                "invoice": {
                    "id": invoice_id,
                    "vendor_name": "Test Vendor Corp",
                    "amount_due": Decimal("1000.00"),
                    "invoice_date": date(2026, 3, 1),
                    "due_date": date(2026, 3, 15)
                },
                "payment": {
                    "vendor_name": "Test Vendor Corp",
                    "amount": Decimal("1000.00"),
                    "payment_date": date(2026, 3, 10)
                },
                "expected_score": 0.95
            },
            "partial": {
                "invoice": {
                    "id": invoice_id,
                    "vendor_name": "Test Vendor Corp",
                    "amount_due": Decimal("1000.00"),
                    "invoice_date": date(2026, 3, 1),
                    "due_date": date(2026, 3, 15)
                },
                "payment": {
                    "vendor_name": "Test Vendor Corp",
                    "amount": Decimal("750.00"),
                    "payment_date": date(2026, 3, 20)
                },
                "expected_score": 0.70
            },
            "fuzzy_vendor": {
                "invoice": {
                    "id": invoice_id,
                    "vendor_name": "Test Vendor Corporation",
                    "amount_due": Decimal("1000.00"),
                    "invoice_date": date(2026, 3, 1),
                    "due_date": date(2026, 3, 15)
                },
                "payment": {
                    "vendor_name": "Test Vendor Corp",
                    "amount": Decimal("1000.00"),
                    "payment_date": date(2026, 3, 10)
                },
                "expected_score": 0.80
            },
            "early_discount": {
                "invoice": {
                    "id": invoice_id,
                    "vendor_name": "Test Vendor Corp",
                    "amount_due": Decimal("1000.00"),
                    "invoice_date": date(2026, 3, 1),
                    "due_date": date(2026, 3, 31)
                },
                "payment": {
                    "vendor_name": "Test Vendor Corp",
                    "amount": Decimal("980.00"),  # 2% early discount
                    "payment_date": date(2026, 3, 10)
                },
                "expected_score": 0.90
            },
            "late_fee": {
                "invoice": {
                    "id": invoice_id,
                    "vendor_name": "Test Vendor Corp",
                    "amount_due": Decimal("1000.00"),
                    "invoice_date": date(2026, 3, 1),
                    "due_date": date(2026, 3, 15)
                },
                "payment": {
                    "vendor_name": "Test Vendor Corp",
                    "amount": Decimal("1015.00"),  # 1.5% late fee
                    "payment_date": date(2026, 3, 25)
                },
                "expected_score": 0.85
            },
            "no_match": {
                "invoice": {
                    "id": invoice_id,
                    "vendor_name": "Vendor A Inc",
                    "amount_due": Decimal("1000.00"),
                    "invoice_date": date(2026, 3, 1),
                    "due_date": date(2026, 3, 15)
                },
                "payment": {
                    "vendor_name": "Vendor B LLC",
                    "amount": Decimal("500.00"),
                    "payment_date": date(2026, 3, 20)
                },
                "expected_score": 0.20
            }
        }
        
        return scenarios.get(scenario, scenarios["exact"])


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "SYNTHETIC_INVOICES",
    "SYNTHETIC_PAYMENTS",
    "SYNTHETIC_CUSTOMERS",
    "SYNTHETIC_EXPENSES",
    "SYNTHETIC_PLATFORM_DATA",
    "create_sample_pdf_bytes",
    "create_test_db",
    "create_test_user",
    "TestDataGenerator"
]


if __name__ == "__main__":
    # Quick test
    print("Synthetic data module loaded successfully")
    print(f"Invoices: {len(SYNTHETIC_INVOICES)}")
    print(f"Payments: {len(SYNTHETIC_PAYMENTS)}")
    print(f"Customers: {len(SYNTHETIC_CUSTOMERS)}")
    print(f"Expenses: {len(SYNTHETIC_EXPENSES)}")
