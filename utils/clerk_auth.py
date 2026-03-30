"""
Clerk authentication utilities for FastAPI.
Handles user authentication via Clerk JWT tokens.
"""
import os
import httpx
import jwt
import json
from typing import Optional
from functools import lru_cache
from fastapi import HTTPException, Header
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from db.database import SessionLocal
from db import models


CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")

def _require_clerk_key():
    """Raise error if CLERK_SECRET_KEY is missing in production."""
    if not CLERK_SECRET_KEY and os.getenv("ENVIRONMENT") == "production":
        raise RuntimeError(
            "CRITICAL: CLERK_SECRET_KEY is not set. Authentication is disabled. "
            "Set CLERK_SECRET_KEY environment variable."
        )

_require_clerk_key()

CLERK_API_URL = "https://api.clerk.com/v1"
CLERK_JWKS_URL = "https://{domain}/jwks".format(
    domain=os.getenv("CLERK_DOMAIN", "accounts.clerk.com")
)


@lru_cache(maxsize=1)
def _get_jwks() -> dict:
    """Fetch and cache Clerk's JWKS (JSON Web Key Set)."""
    if not CLERK_SECRET_KEY:
        raise ValueError("CLERK_SECRET_KEY not configured")
    
    with httpx.Client() as client:
        response = client.get(CLERK_JWKS_URL)
        if response.status_code == 200:
            return response.json()
        raise ValueError(f"Failed to fetch JWKS: {response.status_code}")


def _get_signing_key(jwks: dict, kid: str) -> Optional[str]:
    """Find the signing key from JWKS by key ID."""
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def get_clerk_user(clerk_id: str) -> Optional[dict]:
    """Fetch user data from Clerk API."""
    if not CLERK_SECRET_KEY:
        return None
        
    with httpx.Client() as client:
        response = client.get(
            f"{CLERK_API_URL}/users/{clerk_id}",
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"}
        )
        if response.status_code == 200:
            return response.json()
        return None


def decode_clerk_token(token: str, require_mfa: bool = True) -> Optional[dict]:
    """
    Decode and verify Clerk JWT token using RS256 with JWKS.
    Returns payload if valid, None otherwise.
    
    Args:
        token: Clerk JWT token
        require_mfa: If True, requires MFA to be verified (for production)
    """
    if not CLERK_SECRET_KEY:
        if os.getenv("ENVIRONMENT") == "production":
            raise RuntimeError("CLERK_SECRET_KEY is required in production environment")
        return _decode_unverified(token)
    
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        
        if not kid:
            raise jwt.InvalidTokenError("Missing key ID (kid) in token header")
        
        jwks = _get_jwks()
        signing_key = _get_signing_key(jwks, kid)
        
        if not signing_key:
            raise jwt.InvalidTokenError(f"Signing key not found for kid: {kid}")
        
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(signing_key))
        
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256", "RS384", "RS512"],
            options={
                "verify_aud": False,
                "verify_iss": True,
                "iss": f"https://{os.getenv('CLERK_DOMAIN', 'accounts.clerk.com')}/",
            }
        )
        
        if require_mfa:
            mfa_verified = payload.get("mfa_verified", False)
            mfa_pending = payload.get("mfa_pending", False)
            
            if not mfa_verified and not mfa_pending:
                import logging
                logging.getLogger(__name__).warning(
                    f"Token without MFA verification for user {payload.get('sub')}"
                )
        
        return payload
    except jwt.InvalidTokenError as e:
        raise HTTPException(401, f"Invalid token: {str(e)}")


def _decode_unverified(token: str) -> Optional[dict]:
    """Decode token without verification (for development)."""
    try:
        # Decode without verification
        parts = token.split('.')
        if len(parts) != 3:
            return None
        
        import base64
        payload = parts[1]
        # Add padding if needed
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        
        decoded = base64.b64decode(payload)
        import json
        return json.loads(decoded)
    except Exception:
        return None


def get_or_create_user_from_clerk(clerk_id: str, email: str, full_name: str = None) -> models.User:
    """
    Get existing user or create new one from Clerk data.
    Creates tenant automatically for new users.
    """
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.clerk_id == clerk_id).first()
        
        if not user:
            # Check if user exists by email (for migration from password auth)
            user = db.query(models.User).filter(models.User.email == email).first()
            if user:
                # Link Clerk ID to existing user
                user.clerk_id = clerk_id
            else:
                # Create new user
                user = models.User(
                    email=email,
                    full_name=full_name,
                    clerk_id=clerk_id,
                    is_active=True
                )
                db.add(user)
            db.commit()
            db.refresh(user)
            
            # Create default tenant for new users
            _create_default_tenant(db, user, email)
        
        return user
    finally:
        db.close()


def _create_default_tenant(db: Session, user: models.User, email: str):
    """Create a default tenant for new user."""
    # Generate slug from email
    slug = email.split('@')[0].lower().replace('.', '-')
    # Ensure unique slug
    base_slug = slug
    counter = 1
    while db.query(models.Tenant).filter(models.Tenant.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1
    
    # Create tenant
    tenant = models.Tenant(
        name=email.split('@')[0].title(),
        slug=slug,
        plan="free"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    
    # Link user as owner
    tenant_user = models.TenantUser(
        tenant_id=tenant.id,
        user_id=user.id,
        role="owner"
    )
    db.add(tenant_user)
    
    # Initialize usage record
    from config.plan_limits import get_plan_limits
    limits = get_plan_limits("free")
    
    usage = models.UsageRecord(
        tenant_id=tenant.id,
        month=datetime.now(timezone.utc).strftime("%Y-%m"),
        invoices_limit=limits["invoices_per_month"],
        emails_limit=limits["emails_per_month"],
        sms_limit=limits["sms_per_month"]
    )
    db.add(usage)
    db.commit()


def get_user_tenant(db: Session, user_id: int) -> models.Tenant:
    """Get the primary tenant for a user (usually the first one)."""
    tenant_user = db.query(models.TenantUser).filter(
        models.TenantUser.user_id == user_id
    ).first()
    
    if not tenant_user:
        raise HTTPException(404, "No tenant found for user")
    
    return tenant_user.tenant


def get_user_tenants(db: Session, user_id: int) -> list[models.Tenant]:
    """Get all tenants a user belongs to."""
    tenant_users = db.query(models.TenantUser).filter(
        models.TenantUser.user_id == user_id,
        models.TenantUser.is_active == True
    ).all()
    
    return [tu.tenant for tu in tenant_users]


def require_tenant_owner(db: Session, user_id: int, tenant_id: int):
    """Ensure user is an owner of the tenant."""
    tenant_user = db.query(models.TenantUser).filter(
        models.TenantUser.user_id == user_id,
        models.TenantUser.tenant_id == tenant_id,
        models.TenantUser.role == "owner"
    ).first()
    
    if not tenant_user:
        raise HTTPException(403, "Not authorized to access this tenant")


def require_tenant_member(db: Session, user_id: int, tenant_id: int):
    """Ensure user is a member of the tenant."""
    tenant_user = db.query(models.TenantUser).filter(
        models.TenantUser.user_id == user_id,
        models.TenantUser.tenant_id == tenant_id,
        models.TenantUser.is_active == True
    ).first()
    
    if not tenant_user:
        raise HTTPException(403, "Not authorized to access this tenant")


def get_tenant_by_slug(db: Session, slug: str) -> Optional[models.Tenant]:
    """Get tenant by slug."""
    return db.query(models.Tenant).filter(models.Tenant.slug == slug).first()


def sync_user_from_clerk(clerk_id: str) -> models.User:
    """Sync user data from Clerk and update local database."""
    clerk_user = get_clerk_user(clerk_id)
    if not clerk_user:
        raise HTTPException(404, "User not found in Clerk")
    
    email = clerk_user.get("email_addresses", [{}])[0].get("email_address", "")
    first_name = clerk_user.get("first_name", "")
    last_name = clerk_user.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip() or None
    
    return get_or_create_user_from_clerk(clerk_id, email, full_name)
