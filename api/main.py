from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import uvicorn
import os
from dotenv import load_dotenv
import time
import logging
import uuid
import json
import sys

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "tenant_id"):
            log_data["tenant_id"] = record.tenant_id
        return json.dumps(log_data)

def setup_json_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = []
    root_logger.addHandler(handler)
    
    for logger_name in ["uvicorn", "uvicorn.access", "sqlalchemy.engine"]:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.WARNING)
        logger.handlers = []
        logger.addHandler(handler)

setup_json_logging()

try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logging.warning("prometheus_client not installed - metrics disabled")

if PROMETHEUS_AVAILABLE:
    REQUEST_COUNT = Counter(
        'http_requests_total', 'Total HTTP requests',
        ['method', 'endpoint', 'status']
    )
    REQUEST_LATENCY = Histogram(
        'http_request_duration_seconds', 'HTTP request latency in seconds',
        ['method', 'endpoint']
    )
    ACTIVE_REQUESTS = Gauge(
        'http_requests_active', 'Number of active HTTP requests'
    )
    DB_QUERY_DURATION = Histogram(
        'db_query_duration_seconds', 'Database query duration in seconds',
        ['query_type']
    )
    RECONCILIATION_RUNS = Counter(
        'reconciliation_runs_total', 'Total reconciliation runs',
        ['status']
    )
    PAYMENT_CHASE_RUNS = Counter(
        'payment_chase_runs_total', 'Total payment chase runs',
        ['status']
    )
    AGENT_RUNS = Counter(
        'agent_runs_total', 'Total agent executions',
        ['agent_type', 'status']
    )
    WORKFLOW_TOKEN_COST = Counter(
        'workflow_token_cost_usd_total', 'Total workflow token cost in USD',
        ['tenant_id', 'model']
    )

# Rate limiting - MANDATORY for production
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from utils.rate_limiter import get_rate_limit_key

# Load environment variables
load_dotenv()

# LLM Observability - LangChain tracing (Tier 1)
os.environ["LANGCHAIN_TRACING_V2"] = os.getenv("LANGCHAIN_TRACING_V2", "true")
os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "invoice-handler")
os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGSMITH_API_KEY", "")

# Initialize Sentry (optional - only if DSN is configured)
import sentry_sdk
sentry_dsn = os.getenv("SENTRY_DSN")

if sentry_dsn:
    try:
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration
        
        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=os.getenv("ENVIRONMENT", "production"),
            traces_sample_rate=0.1,
            integrations=[
                SqlalchemyIntegration(),
                RedisIntegration(),
                CeleryIntegration(),
            ],
            send_default_pii=False
        )
    except ImportError as e:
        print(f"Warning: Could not initialize Sentry: {e}")
        sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.1)
else:
    print("Sentry DSN not configured - skipping Sentry initialization")

# Internal imports
from db.database import get_db, engine
from db import models
from schemas import user as user_schema
from schemas import invoice as invoice_schema
from schemas import expense as expense_schema
from schemas import payment as payment_schema
from schemas import report as report_schema
from agents.orchestrator import InvoiceHandlerOrchestrator
from middleware.auth import get_current_user
from utils.auth import authenticate_user, create_access_token
from utils.security import get_password_hash
from utils.exceptions import WorkflowAlreadyRunningError

# Import API routes
from api.routes import auth, invoices, expenses, payments, reports, customers, admin, webhooks, saas, oauth, billing

# Create database tables (only in development)
if os.getenv("ENVIRONMENT", "development").lower() != "production":
    models.Base.metadata.create_all(bind=engine)

# Apply RLS policies after table creation
from db.database import setup_rls_policies
import logging
logger = logging.getLogger(__name__)
try:
    setup_rls_policies(engine)
    logger.info("RLS policies applied successfully")
except Exception as e:
    logger.error(f"RLS policy setup failed: {e}")
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        logger.warning("Continuing without RLS policies - will retry on next request")

app = FastAPI(
    title="Invoice Handler API",
    description="AI-Powered Invoice & Expense Reconciliation + Payment Chasing Agent",
    version="1.0.0"
)

@app.on_event("startup")
async def validate_required_env():
    """Validate required environment variables at startup."""
    import logging
    required = ["CLERK_SECRET_KEY", "TOKEN_ENCRYPTION_KEY", "SECRET_KEY", "DATABASE_URL"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        if os.getenv("ENVIRONMENT") == "production":
            raise RuntimeError(f"Missing required env vars for production: {missing}")
        else:
            logging.warning(f"Missing env vars (dev mode): {missing}")


def validate_rls_setup() -> None:
    """Validate RLS is properly configured at startup.
    
    Raises:
        RuntimeError: If RLS is not properly configured.
    """
    import logging
    from sqlalchemy import text
    from db.database import engine
    
    logger = logging.getLogger(__name__)
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT usename, usesuper FROM pg_user WHERE usename = current_user"))
        row = result.fetchone()
        
        if row and row[1]:
            logger.warning("Database user is a superuser - RLS policies may not be enforced!")
        
        rls_required_tables = [
            'invoices', 'payments', 'expenses', 'customers',
            'connected_accounts', 'api_keys', 'audit_logs'
        ]
        
        for table in rls_required_tables:
            result = conn.execute(text(
                "SELECT relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE relname = :table AND nspname = 'public'"
            ), {"table": table})
            row = result.fetchone()
            
            if not row or not row[0]:
                raise RuntimeError(
                    f"RLS is NOT enabled on table '{table}'. "
                    f"Run: alembic upgrade head"
                )
        
        result = conn.execute(text(
            "SELECT COUNT(*) FROM pg_policies WHERE policyname = 'invoices_tenant_isolation'"
        ))
        policy_count = result.scalar()
        
        if policy_count == 0:
            raise RuntimeError(
                "RLS tenant isolation policies not found. "
                "Run: alembic upgrade head"
            )
    
    logger.info("RLS validation passed - all tables have RLS enabled")


@app.on_event("startup")
async def startup_rls_validation():
    """Validate RLS configuration at startup in production."""
    if os.getenv("ENVIRONMENT") == "production":
        try:
            validate_rls_setup()
        except RuntimeError as e:
            logging.getLogger(__name__).error(f"RLS validation FAILED: {e}")
            raise


def validate_secrets() -> None:
    """Validate that secrets are properly configured.
    
    Raises:
        RuntimeError: If any secret is a placeholder value.
    """
    import logging
    from cryptography.fernet import Fernet
    
    logger = logging.getLogger(__name__)
    
    placeholder_patterns = ['REPLACE', 'your-secret', 'your_secret']
    
    secret_key = os.getenv('SECRET_KEY', '')
    jwt_secret = os.getenv('JWT_SECRET_KEY', '')
    token_encryption_key = os.getenv('TOKEN_ENCRYPTION_KEY', '')
    
    if len(secret_key) < 32:
        raise RuntimeError("SECRET_KEY must be at least 32 characters")
    
    if any(p in secret_key.upper() for p in placeholder_patterns):
        raise RuntimeError("SECRET_KEY contains placeholder value")
    
    if len(jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET_KEY must be at least 32 characters")
    
    if any(p in jwt_secret.upper() for p in placeholder_patterns):
        raise RuntimeError("JWT_SECRET_KEY contains placeholder value")
    
    if any(p in token_encryption_key.upper() for p in placeholder_patterns):
        raise RuntimeError("TOKEN_ENCRYPTION_KEY contains placeholder value")
    
    try:
        Fernet(token_encryption_key.encode())
    except Exception:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key")
    
    logger.info("Secret validation passed")


@app.on_event("startup")
async def startup_secret_validation():
    """Validate secrets configuration at startup."""
    if os.getenv("ENVIRONMENT") == "production":
        try:
            validate_secrets()
        except RuntimeError as e:
            logging.getLogger(__name__).error(f"Secret validation FAILED: {e}")
            raise

# CORS Middleware
origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# HTTPS enforcement for production
if os.getenv("ENVIRONMENT") == "production":
    @app.middleware("http")
    async def add_hsts_header(request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

# Request ID tracing (Tier 3)
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# Security headers (Tier 2 - XSS protection)
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
    return response

# CSRF Protection (Tier 1)
@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            origin = request.headers.get("Origin", "")
            allowed = os.getenv("CORS_ORIGINS", "").split(",")
            if origin and origin not in allowed:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed"}
                )
    return await call_next(request)

# Auth Context Middleware - Sets request.state.user_id and tenant_id for audit logging
@app.middleware("http")
async def set_auth_context(request: Request, call_next):
    """Set user_id and tenant_id in request state for audit logging."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            token = auth[7:]
            from utils import clerk_auth
            claims = clerk_auth.decode_clerk_token(token, require_mfa=False)
            if claims:
                clerk_id = claims.get("sub")
                if clerk_id:
                    from db.database import SessionLocal
                    from db import models
                    db = SessionLocal()
                    try:
                        user = db.query(models.User).filter(models.User.clerk_id == clerk_id).first()
                        if user:
                            request.state.user_id = user.id
                            tenant_user = db.query(models.TenantUser).filter(
                                models.TenantUser.user_id == user.id
                            ).first()
                            if tenant_user:
                                request.state.tenant_id = tenant_user.tenant_id
                    finally:
                        db.close()
        except Exception:
            pass
    return await call_next(request)

# Audit Logging Middleware (SOC 2 compliance) - MANDATORY for production
from utils.audit_middleware import auto_audit_middleware
app = auto_audit_middleware(app)
import logging
logging.getLogger(__name__).info("Audit logging middleware enabled")

# Rate Limiting - MANDATORY for production
limiter = Limiter(key_func=get_rate_limit_key)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    raise HTTPException(
        status_code=429,
        detail="Rate limit exceeded. Please try again later."
    )

@app.exception_handler(WorkflowAlreadyRunningError)
async def workflow_already_running_handler(request: Request, exc: WorkflowAlreadyRunningError):
    raise HTTPException(
        status_code=409,
        detail=exc.detail
    )

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Include routers
# Password-based auth is disabled in production - use Clerk OAuth instead
if os.getenv("ENABLE_PASSWORD_AUTH", "false").lower() == "true":
    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    logger.warning("⚠️  PASSWORD AUTH ENABLED - FOR DEV ONLY")

app.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
app.include_router(expenses.router, prefix="/expenses", tags=["expenses"])
app.include_router(payments.router, prefix="/payments", tags=["payments"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])
app.include_router(customers.router, prefix="/customers", tags=["customers"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(saas.router, prefix="/api/v1", tags=["saas"])
app.include_router(oauth.router, prefix="/oauth", tags=["oauth"])
app.include_router(billing.router, prefix="/billing", tags=["billing"])

@app.get("/", tags=["root"])
async def root():
    return {"message": "Welcome to Invoice Handler API"}

ENABLE_PASSWORD_AUTH = os.getenv("ENABLE_PASSWORD_AUTH", "false").lower() == "true"

@app.post("/token", response_model=dict)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    if not ENABLE_PASSWORD_AUTH:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password authentication is disabled. Use Clerk OAuth instead."
        )
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30)))
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/users/", response_model=user_schema.User)
def create_user(user: user_schema.UserCreate, db: Session = Depends(get_db)):
    if not ENABLE_PASSWORD_AUTH:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User registration is disabled. Use Clerk OAuth instead."
        )
    # Validate password strength
    from utils.security import validate_password_strength
    is_valid, error = validate_password_strength(user.password)
    if not is_valid:
        raise HTTPException(400, error)
    
    # Check if user already exists
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    # Hash password
    hashed_password = get_password_hash(user.password)
    db_user = models.User(
        email=user.email,
        full_name=user.full_name,
        hashed_password=hashed_password,
        is_active=True
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.get("/users/me/", response_model=user_schema.User)
def read_users_me(current_user: user_schema.User = Depends(get_current_user)):
    return current_user

# Health check endpoint (Tier 2 - dependency checks)
@app.get("/health", tags=["health"])
def health_check():
    checks = {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
    
    # Check database
    try:
        from db.database import SessionLocal
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"
        checks["status"] = "degraded"
    
    # Check Redis
    try:
        import redis
        r = redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"
        checks["status"] = "degraded"
    
    return checks

# Prometheus metrics endpoint
@app.get("/metrics", tags=["monitoring"])
def metrics():
    if not PROMETHEUS_AVAILABLE:
        raise HTTPException(status_code=501, detail="Prometheus metrics not configured")
    from fastapi.responses import Response
    return Response(generate_latest(), media_type="text/plain")

# Metrics middleware
if PROMETHEUS_AVAILABLE:
    @app.middleware("http")
    async def track_metrics(request: Request, call_next):
        method = request.method
        path = request.url.path
        endpoint = path.split("/")[1] if len(path.split("/")) > 1 else "root"
        status = 500  # Default status in case of exception
        
        ACTIVE_REQUESTS.inc()
        start_time = time.time()
        
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            duration = time.time() - start_time
            ACTIVE_REQUESTS.dec()
            REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
            REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(duration)

if __name__ == "__main__":
    uvicorn.run("api.main:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 8000)), reload=True)