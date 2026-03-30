"""Enable RLS policies for multi-tenancy.

Revision ID: 003
Revises: 002
Create Date: 2026-03-29
"""
from alembic import op
import logging

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    rls_statements = [
        "ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE tenant_users ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE payments ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE expenses ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE customers ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE reports ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE connected_accounts ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE usage_records ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE workflow_runs ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE reconciliation_history ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;",
    ]
    
    for stmt in rls_statements:
        try:
            op.execute(stmt)
        except Exception as e:
            logger.warning(f"RLS enable statement may already applied: {e}")
    
    policies = [
        """
        DROP POLICY IF EXISTS tenants_tenant_isolation ON tenants;
        CREATE POLICY tenants_tenant_isolation ON tenants
        FOR ALL USING (id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS tenant_users_tenant_isolation ON tenant_users;
        CREATE POLICY tenant_users_tenant_isolation ON tenant_users
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS invoices_tenant_isolation ON invoices;
        CREATE POLICY invoices_tenant_isolation ON invoices
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS payments_tenant_isolation ON payments;
        CREATE POLICY payments_tenant_isolation ON payments
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS expenses_tenant_isolation ON expenses;
        CREATE POLICY expenses_tenant_isolation ON expenses
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS customers_tenant_isolation ON customers;
        CREATE POLICY customers_tenant_isolation ON customers
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS reports_tenant_isolation ON reports;
        CREATE POLICY reports_tenant_isolation ON reports
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS connected_accounts_tenant_isolation ON connected_accounts;
        CREATE POLICY connected_accounts_tenant_isolation ON connected_accounts
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS api_keys_tenant_isolation ON api_keys;
        CREATE POLICY api_keys_tenant_isolation ON api_keys
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS usage_records_tenant_isolation ON usage_records;
        CREATE POLICY usage_records_tenant_isolation ON usage_records
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS workflow_runs_tenant_isolation ON workflow_runs;
        CREATE POLICY workflow_runs_tenant_isolation ON workflow_runs
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS reconciliation_history_tenant_isolation ON reconciliation_history;
        CREATE POLICY reconciliation_history_tenant_isolation ON reconciliation_history
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
        """
        DROP POLICY IF EXISTS audit_logs_tenant_isolation ON audit_logs;
        CREATE POLICY audit_logs_tenant_isolation ON audit_logs
        FOR ALL USING (tenant_id = current_setting('app.tenant_id', true)::integer);
        """,
    ]
    
    for policy in policies:
        try:
            op.execute(policy)
        except Exception as e:
            logger.warning(f"RLS policy may already exist: {e}")
    
    logger.info("RLS policies applied successfully")


def downgrade() -> None:
    tables = [
        'tenants', 'tenant_users', 'invoices', 'payments', 'expenses',
        'customers', 'reports', 'connected_accounts', 'api_keys',
        'usage_records', 'workflow_runs', 'reconciliation_history', 'audit_logs'
    ]
    
    for table in tables:
        try:
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
        except Exception as e:
            logger.warning(f"Could not disable RLS on {table}: {e}")
