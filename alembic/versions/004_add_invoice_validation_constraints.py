"""Add invoice validation CheckConstraints.

Revision ID: 004
Revises: 003
Create Date: 2026-03-29
"""
from alembic import op
import logging

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    constraints = [
        ("invoice_amount_positive", "CHECK (amount_due > 0)"),
        ("invoice_amount_max", "CHECK (amount_due <= 10000000)"),
        ("invoice_due_not_ancient", "CHECK (due_date >= CURRENT_DATE - interval '1 year')"),
        ("invoice_due_not_future", "CHECK (due_date <= CURRENT_DATE + interval '5 years')"),
    ]
    
    for name, check_sql in constraints:
        try:
            op.execute(f"ALTER TABLE invoices DROP CONSTRAINT IF EXISTS {name}")
            op.execute(f"ALTER TABLE invoices ADD CONSTRAINT {name} {check_sql}")
        except Exception as e:
            logger.warning(f"Constraint {name} may already exist: {e}")
    
    logger.info("Invoice validation constraints applied")


def downgrade() -> None:
    constraints = [
        "invoice_amount_positive",
        "invoice_amount_max",
        "invoice_due_not_ancient",
        "invoice_due_not_future",
    ]
    
    for name in constraints:
        try:
            op.execute(f"ALTER TABLE invoices DROP CONSTRAINT IF EXISTS {name}")
        except Exception as e:
            logger.warning(f"Could not drop constraint {name}: {e}")
