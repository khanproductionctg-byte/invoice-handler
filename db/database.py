from sqlalchemy import create_engine, event, text
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
    pool_size=20,
    max_overflow=40,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Get database session."""
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
        # Set tenant context for RLS (Row Level Security)
        # Using parameterized query to prevent SQL injection
        db.execute(text("SET LOCAL app.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        yield db
    finally:
        db.close()


def get_tenant_session(tenant_id: int) -> SessionLocal:
    """
    Get a database session with tenant context set for RLS.
    Use this in background tasks and agents that don't use FastAPI dependencies.
    
    IMPORTANT: Always close the session after use:
        db = get_tenant_session(tenant_id)
        try:
            # use db
        finally:
            db.close()
    """
    db = SessionLocal()
    db.execute(text("SET LOCAL app.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    return db


from contextlib import contextmanager


@contextmanager
def tenant_context(tenant_id: int):
    """
    Context manager for tenant-scoped database operations.
    Sets and resets tenant_id for RLS.
    
    Usage:
        with tenant_context(tenant_id):
            invoices = db.query(Invoice).all()
    """
    db = SessionLocal()
    try:
        db.execute(text("SET LOCAL app.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        yield db
    finally:
        db.close()


# Row Level Security (RLS) - Enable at database level
RLS_POLICIES = """
-- Enable RLS on all tenant tables
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE expenses ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE connected_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconciliation_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- Create tenant isolation policies
-- Each policy restricts rows to those matching the current tenant_id
"""


def setup_rls_policies(engine):
    """Set up Row Level Security policies for multi-tenancy.
    
    MUST be called after tables are created.
    Enables RLS and creates tenant isolation policies for all business tables.
    """
    import logging
    logger = logging.getLogger(__name__)
    
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

    with engine.connect() as conn:
        for stmt in rls_statements:
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                logger.warning(f"RLS statement failed (may already exist): {e}")

    logger.info("RLS policies applied to all tenant-scoped tables")


def setup_rlsPolicies(engine):
    """Backward-compatible alias for setup_rls_policies."""
    setup_rls_policies(engine)
