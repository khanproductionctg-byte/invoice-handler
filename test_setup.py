"""
Local test setup script for audit_test_suite.py

Run this first to:
1. Install dependencies
2. Start local services (PostgreSQL, Redis)
3. Set up database with RLS policies
4. Configure environment variables
"""

import os
import subprocess
import sys

def check_services():
    """Check if PostgreSQL and Redis are running."""
    print("\n[*] Checking services...")
    
    # Check PostgreSQL
    try:
        result = subprocess.run(
            ["pg_isready", "-h", "localhost", "-p", "5432"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("  [+] PostgreSQL is running")
        else:
            print("  [-] PostgreSQL is not running")
            print("     Start with: docker run -d -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15")
            return False
    except FileNotFoundError:
        print("  [!] pg_isready not found, trying docker...")
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=postgres"],
            capture_output=True, text=True
        )
        if "postgres" not in result.stdout:
            print("  [-] PostgreSQL container not running")
            return False
        print("  [+] PostgreSQL container running")

    # Check Redis
    try:
        import redis
        r = redis.from_url("redis://localhost:6379")
        r.ping()
        print("  [+] Redis is running")
    except Exception as e:
        print(f"  [-] Redis is not running: {e}")
        print("     Start with: docker run -d -p 6379:6379 redis:7")
        return False
    
    return True


def install_dependencies():
    """Install required Python packages."""
    print("\n[*] Installing dependencies...")
    
    packages = [
        "pytest",
        "pytest-asyncio", 
        "asyncpg",
        "redis",
        "langchain-core",
        "langgraph",
        "python-dotenv",
        "pydantic"
    ]
    
    for pkg in packages:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg])
    
    print("  [+] Dependencies installed")


def setup_database():
    """Set up PostgreSQL database with RLS policies."""
    print("\n[*] Setting up database...")
    
    # Create database URLs
    superuser_url = os.getenv(
        "DATABASE_SUPERUSER_URL",
        "postgresql://postgres:postgres@localhost:5432/invoice_handler"
    )
    app_url = os.getenv(
        "DATABASE_URL",
        "postgresql://app_user:app_password@localhost:5432/invoice_handler"
    )
    
    import asyncpg
    
    async def _setup():
        # Connect as superuser
        conn = await asyncpg.connect(superuser_url)
        
        # Create app_user if not exists
        await conn.execute("""
            DO $$
            BEGIN
                CREATE USER app_user WITH PASSWORD 'app_password';
            EXCEPTION WHEN duplicate_object THEN
                NULL;
            END
            $$;
        """)
        
        # Create tables
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
                thread_id VARCHAR(255) NOT NULL,
                checkpoint_id VARCHAR(255) NOT NULL,
                tenant_id VARCHAR(255) NOT NULL,
                payload JSONB,
                created_at TIMESTAMP DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS invoices (
                id SERIAL PRIMARY KEY,
                tenant_id VARCHAR(255) NOT NULL,
                invoice_number VARCHAR(255),
                vendor VARCHAR(255),
                amount DECIMAL(12,2),
                currency VARCHAR(10),
                due_date DATE,
                status VARCHAR(50),
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        # Enable RLS
        await conn.execute("ALTER TABLE langgraph_checkpoints ENABLE ROW LEVEL SECURITY;")
        await conn.execute("ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;")
        
        # Create RLS policies
        await conn.execute("""
            DROP POLICY IF EXISTS langgraph_checkpoints_tenant_policy ON langgraph_checkpoints;
            CREATE POLICY langgraph_checkpoints_tenant_policy ON langgraph_checkpoints
                USING (tenant_id::text = current_setting('app.current_tenant_id', true)::text);
        """)
        
        await conn.execute("""
            DROP POLICY IF EXISTS invoices_tenant_policy ON invoices;
            CREATE POLICY invoices_tenant_policy ON invoices
                USING (tenant_id::text = current_setting('app.current_tenant_id', true)::text);
        """)
        
        # Grant permissions to app_user
        await conn.execute("GRANT ALL ON langgraph_checkpoints TO app_user;")
        await conn.execute("GRANT ALL ON invoices TO app_user;")
        await conn.execute("GRANT USAGE ON SCHEMA public TO app_user;")
        
        await conn.close()
        print("  [+] Database configured with RLS")
    
    import asyncio
    asyncio.run(_setup())


def create_env_file():
    """Create/update .env.test file with test-specific variables."""
    print("\n[*] Creating test environment file...")
    
    env_content = """
# Test Environment Variables
# Copy from .env and update these values

# Database - use app_user (non-superuser) for RLS tests
DATABASE_URL=postgresql://app_user:app_password@localhost:5432/invoice_handler

# Database - use superuser for setup/teardown
DATABASE_SUPERUSER_URL=postgresql://postgres:postgres@localhost:5432/invoice_handler

# Redis
REDIS_URL=redis://localhost:6379

# LangSmith (optional - for tracing tests)
LANGSMITH_API_KEY=
LANGCHAIN_TRACING_V2=false
"""
    
    with open(".env.test", "w") as f:
        f.write(env_content)
    
    print("  [+] Created .env.test")
    print("  [!] Edit .env.test to match your database credentials")


def main():
    print("=" * 60)
    print("  AUDIT TEST SUITE - LOCAL SETUP")
    print("=" * 60)
    
    # Check/install dependencies
    install_dependencies()
    
    # Check services
    if not check_services():
        print("\n[-] Please start required services first")
        return
    
    # Create env file
    create_env_file()
    
    # Setup database
    try:
        setup_database()
    except Exception as e:
        print(f"\n[!] Database setup skipped: {e}")
        print("   You may need to run setup manually or update DATABASE_SUPERUSER_URL")
    
    print("\n" + "=" * 60)
    print("  SETUP COMPLETE!")
    print("=" * 60)
    print("\nTo run tests:")
    print("  1. Update .env.test with your database credentials")
    print("  2. Run: pytest audit_test_suite.py -v --tb=short")
    print("\nTo run specific test sections:")
    print("  pytest audit_test_suite.py::TestRLSIsolation -v")
    print("  pytest audit_test_suite.py::TestInvoiceIdempotency -v")
    print("  pytest audit_test_suite.py::TestPromptInjection -v")
    print("  pytest audit_test_suite.py::TestStateGraphResilience -v")
    print("  pytest audit_test_suite.py::TestRedisDLQ -v")
    print("  pytest audit_test_suite.py::TestPlaidTokenLeak -v")


if __name__ == "__main__":
    main()
