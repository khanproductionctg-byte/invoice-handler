"""
FastAPI dependencies for authentication and authorization.
"""
import os
from fastapi import Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session
from typing import Optional
from db.database import get_db
from db import models
from utils import clerk_auth
from config.plan_limits import can_use_feature

# MFA enforcement - enable in production
ENFORCE_MFA = os.getenv("ENFORCE_MFA", "false").lower() == "true"


async def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: Session = Depends(get_db)
) -> models.User:
    """
    Get current authenticated user from Clerk JWT.
    Expects header: Authorization: Bearer <token>
    """
    if not authorization:
        raise HTTPException(401, "Missing authorization header")
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization format. Use: Bearer <token>")
    
    token = authorization.replace("Bearer ", "")
    
    # Decode and verify token (with MFA check)
    claims = clerk_auth.decode_clerk_token(token, require_mfa=ENFORCE_MFA)
    if not claims:
        raise HTTPException(401, "Invalid or expired token")
    
    # Check MFA if enforcing
    if ENFORCE_MFA:
        mfa_verified = claims.get("mfa_verified", False)
        if not mfa_verified:
            raise HTTPException(
                403, 
                "Multi-factor authentication required. Please enable MFA in your account settings."
            )
    
    # Get user ID from token
    clerk_id = claims.get("sub")
    if not clerk_id:
        raise HTTPException(401, "Invalid token claims")
    
    # Get or create user from Clerk
    email = claims.get("email", "")
    name = claims.get("name", "")
    
    user = clerk_auth.get_or_create_user_from_clerk(clerk_id, email, name)
    
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or inactive")
    
    return user


async def get_current_tenant(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> models.Tenant:
    """
    Get the current user's primary tenant.
    Uses the first tenant the user belongs to.
    Sets PostgreSQL RLS app.tenant_id for row-level security.
    """
    tenant = clerk_auth.get_user_tenant(db, user.id)
    
    if not tenant or not tenant.is_active:
        raise HTTPException(403, "Tenant not found or inactive")
    
    # Set RLS context for PostgreSQL row-level security
    import logging
    from sqlalchemy import text
    try:
        db.execute(text("SET LOCAL app.tenant_id = :tenant_id"), {"tenant_id": tenant.id})
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to set tenant RLS context: {e}")
        # In production, fail the request
        if os.getenv("ENVIRONMENT") == "production":
            raise HTTPException(500, "Internal security error - tenant isolation failed")
    
    return tenant


async def get_current_tenant_user(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> models.TenantUser:
    """
    Get the current user's tenant user relationship.
    """
    tenant_user = db.query(models.TenantUser).filter(
        models.TenantUser.user_id == user.id,
        models.TenantUser.is_active == True
    ).first()
    
    if not tenant_user:
        raise HTTPException(403, "User not associated with any tenant")
    
    return tenant_user


def require_plan(
    required_plan: str,
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """
    Check if tenant has required plan level.
    Usage: @require_plan("pro")
    """
    plans_order = {"free": 0, "pro": 1, "enterprise": 2}
    
    current_level = plans_order.get(tenant.plan, 0)
    required_level = plans_order.get(required_plan, 0)
    
    if current_level < required_level:
        raise HTTPException(
            403, 
            f"This feature requires {required_plan.title()} plan or higher. Upgrade to continue."
        )
    
    return tenant


def require_feature(
    feature: str,
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """
    Check if tenant's plan includes the feature.
    Usage: @require_feature("api_access")
    """
    if not can_use_feature(tenant.plan, feature):
        plan_name = tenant.plan.title()
        raise HTTPException(
            403,
            f"This feature is not available on the {plan_name} plan. Upgrade to access."
        )
    
    return tenant


def require_role(
    allowed_roles: list[str],
    tenant_user: models.TenantUser = Depends(get_current_tenant_user)
):
    """
    Check if user has required role.
    Usage: @require_role(["owner", "admin"])
    """
    if tenant_user.role not in allowed_roles:
        raise HTTPException(
            403,
            f"This action requires one of these roles: {', '.join(allowed_roles)}"
        )
    
    return tenant_user


class TenantContext:
    """
    Tenant context for the current request.
    Can be used to automatically filter queries by tenant.
    """
    def __init__(self, tenant: models.Tenant):
        self.tenant = tenant
        self.tenant_id = tenant.id
        self.plan = tenant.plan
    
    def filter_query(self, query, model_class):
        """
        Filter a SQLAlchemy query by tenant_id.
        """
        if hasattr(model_class, 'tenant_id'):
            return query.filter(model_class.tenant_id == self.tenant_id)
        return query


async def get_tenant_context(
    tenant: models.Tenant = Depends(get_current_tenant)
) -> TenantContext:
    """
    Get tenant context for the current request.
    """
    return TenantContext(tenant)


# Optional: Dependency for getting optional auth
async def get_optional_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: Session = Depends(get_db)
) -> Optional[models.User]:
    """
    Get current user if authenticated, None otherwise.
    Useful for public endpoints that show different content for auth users.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    
    try:
        return await get_current_user(authorization, db)
    except HTTPException:
        return None
