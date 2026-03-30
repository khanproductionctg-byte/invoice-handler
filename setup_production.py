#!/bin/bash
# ============================================================
# Production Setup - Run ONCE after containers are up
# Creates database tables and default Pro account
# Usage: docker compose -f docker-compose.prod.yml exec api python setup_production.py
# ============================================================

import os
import sys
from dotenv import load_dotenv
load_dotenv()

os.environ["ENVIRONMENT"] = "production"

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup_production():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from db.models import Base, User, Tenant, TenantUser, UsageRecord
    from utils.security import get_password_hash
    import secrets
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set")
        return False
    
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    logger.info(f"Connecting to database...")
    engine = create_engine(database_url, pool_pre_ping=True)
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables created")
    
    # Create RLS policies
    with engine.connect() as conn:
        conn.execute(text("""
            DO $$
            BEGIN
                -- Enable RLS on all tenant tables
                ALTER TABLE IF EXISTS tenants ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS users ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS tenant_users ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS invoices ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS payments ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS customers ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS expenses ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS usage_records ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS connected_accounts ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS workflow_runs ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS reports ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS api_keys ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS payment_followups ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS reconciliation_history ENABLE ROW LEVEL SECURITY;
                ALTER TABLE IF EXISTS audit_logs ENABLE ROW LEVEL SECURITY;

                -- Create policies (skip if exists)
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'invoices' AND policyname = 'tenant_isolation_policy') THEN
                    CREATE POLICY tenant_isolation_policy ON invoices USING (tenant_id = current_setting('app.tenant_id', true)::integer) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::integer);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'payments' AND policyname = 'tenant_isolation_policy') THEN
                    CREATE POLICY tenant_isolation_policy ON payments USING (tenant_id = current_setting('app.tenant_id', true)::integer) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::integer);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'customers' AND policyname = 'tenant_isolation_policy') THEN
                    CREATE POLICY tenant_isolation_policy ON customers USING (tenant_id = current_setting('app.tenant_id', true)::integer) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::integer);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'expenses' AND policyname = 'tenant_isolation_policy') THEN
                    CREATE POLICY tenant_isolation_policy ON expenses USING (tenant_id = current_setting('app.tenant_id', true)::integer) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::integer);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'usage_records' AND policyname = 'tenant_isolation_policy') THEN
                    CREATE POLICY tenant_isolation_policy ON usage_records USING (tenant_id = current_setting('app.tenant_id', true)::integer) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::integer);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'connected_accounts' AND policyname = 'tenant_isolation_policy') THEN
                    CREATE POLICY tenant_isolation_policy ON connected_accounts USING (tenant_id = current_setting('app.tenant_id', true)::integer) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::integer);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'workflow_runs' AND policyname = 'tenant_isolation_policy') THEN
                    CREATE POLICY tenant_isolation_policy ON workflow_runs USING (tenant_id = current_setting('app.tenant_id', true)::integer) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::integer);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'reports' AND policyname = 'tenant_isolation_policy') THEN
                    CREATE POLICY tenant_isolation_policy ON reports USING (tenant_id = current_setting('app.tenant_id', true)::integer) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::integer);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'api_keys' AND policyname = 'tenant_isolation_policy') THEN
                    CREATE POLICY tenant_isolation_policy ON api_keys USING (tenant_id = current_setting('app.tenant_id', true)::integer) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::integer);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'reconciliation_history' AND policyname = 'tenant_isolation_policy') THEN
                    CREATE POLICY tenant_isolation_policy ON reconciliation_history USING (tenant_id = current_setting('app.tenant_id', true)::integer) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::integer);
                END IF;

                -- Superuser policies
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'tenants' AND policyname = 'superuser_policy') THEN
                    CREATE POLICY superuser_policy ON tenants USING (true);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'users' AND policyname = 'superuser_policy') THEN
                    CREATE POLICY superuser_policy ON users USING (true);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'tenant_users' AND policyname = 'superuser_policy') THEN
                    CREATE POLICY superuser_policy ON tenant_users USING (true);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'payment_followups' AND policyname = 'superuser_policy') THEN
                    CREATE POLICY superuser_policy ON payment_followups USING (true);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'audit_logs' AND policyname = 'superuser_policy') THEN
                    CREATE POLICY superuser_policy ON audit_logs USING (true);
                END IF;
            END $$;
        """))
        conn.commit()
    logger.info("✅ RLS policies created")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        # Check if default user exists
        existing = db.query(User).filter(User.email == "admin@invoicehandler.com").first()
        if existing:
            logger.info("ℹ️  Default user already exists")
            return True
        
        # Create default Pro user
        user = User(
            email="admin@invoicehandler.com",
            full_name="Admin User",
            hashed_password=get_password_hash("InvoiceHandler2026!"),
            clerk_id=f"clerk_prod_{secrets.token_hex(8)}",
            is_active=True,
        )
        db.add(user)
        db.flush()
        
        # Create Pro tenant
        tenant = Tenant(
            name="Demo Company",
            slug=f"demo-company-{secrets.token_hex(4)}",
            plan="pro",
            is_active=True,
        )
        db.add(tenant)
        db.flush()
        
        # Link user to tenant
        tenant_user = TenantUser(
            tenant_id=tenant.id,
            user_id=user.id,
            role="owner",
            is_active=True,
        )
        db.add(tenant_user)
        
        # Create usage record
        usage = UsageRecord(
            tenant_id=tenant.id,
            month="2026-03",
            invoices_processed=0,
            invoices_limit=500,
            emails_sent=0,
            emails_limit=200,
            sms_sent=0,
            sms_limit=50,
            api_calls=0,
        )
        db.add(usage)
        db.commit()
        
        logger.info("✅ Production account created")
        logger.info("")
        logger.info("=" * 60)
        logger.info("LOGIN CREDENTIALS")
        logger.info("=" * 60)
        logger.info("  Email:    admin@invoicehandler.com")
        logger.info("  Password: InvoiceHandler2026!")
        logger.info("  Plan:     PRO (500 invoices/month)")
        logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Setup failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = setup_production()
    sys.exit(0 if success else 1)
