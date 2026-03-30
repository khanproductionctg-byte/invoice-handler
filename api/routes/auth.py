"""
Authentication API routes with rate limiting.
NOTE: This file is kept for backward compatibility.
For production, use Clerk OAuth via /oauth/* routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from typing import Optional

from db.database import get_db
from db import models
from schemas import user as user_schema
from middleware.auth import get_current_user
from utils.security import get_password_hash
from utils.audit_logger import get_audit_logger

# Import for backward compatibility (deprecated - use Clerk instead)
from utils.auth import authenticate_user, create_access_token

# Rate limiting
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    
    limiter = Limiter(key_func=get_remote_address)
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    limiter = None
    RATE_LIMITING_AVAILABLE = False

router = APIRouter(prefix="/auth", tags=["auth"])


def get_client_ip(request: Request) -> str:
    """Get client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

@router.post("/token", response_model=dict)
@limiter.limit("5/minute")  # 5 login attempts per minute
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    audit_logger = get_audit_logger()
    
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if user.locked_until and user.locked_until > datetime.utcnow():
        raise HTTPException(
            status_code=423,
            detail="Account is temporarily locked due to too many failed login attempts",
        )
    
    user_authenticated = authenticate_user(db, form_data.username, form_data.password)
    
    if not user_authenticated:
        user.failed_login_attempts += 1
        
        if user.failed_login_attempts >= 5:
            user.locked_until = datetime.utcnow() + timedelta(minutes=30)
            audit_logger.log_login(
                tenant_id=1,
                user_id=user.id,
                status="locked",
                ip_address=get_client_ip(request),
                user_agent=request.headers.get("User-Agent"),
                request_method="POST",
                request_path="/auth/token",
                error_message="Account locked after 5 failed attempts"
            )
            db.commit()
            raise HTTPException(
                status_code=423,
                detail="Account locked due to too many failed login attempts. Try again in 30 minutes.",
            )
        
        db.commit()
        
        audit_logger.log_login(
            tenant_id=1,
            user_id=user.id,
            status="failure",
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
            request_method="POST",
            request_path="/auth/token",
            error_message=f"Invalid credentials ({user.failed_login_attempts}/5)"
        )
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    
    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/users/", response_model=user_schema.User)
@limiter.limit("3/minute")  # 3 signups per minute
def create_user(
    request: Request,
    user: user_schema.UserCreate, 
    db: Session = Depends(get_db)
):
    from utils.security import validate_password_strength
    
    is_valid, error = validate_password_strength(user.password)
    if not is_valid:
        raise HTTPException(400, error)
    
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
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

@router.get("/users/me/", response_model=user_schema.User)
async def read_users_me(current_user: user_schema.User = Depends(get_current_user)):
    return current_user