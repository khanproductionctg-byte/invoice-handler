"""
Tenant-aware rate limiting utilities.
Provides per-tenant rate limiting based on plan limits.
"""
import os
import logging
from typing import Callable, Optional
from functools import wraps

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger(__name__)

# Default rate limits per plan (requests per minute)
PLAN_RATE_LIMITS = {
    "free": 30,
    "pro": 100,
    "enterprise": 500,
}


def get_tenant_rate_limit(plan: str) -> int:
    """
    Get rate limit for a plan.
    
    Args:
        plan: Plan name (free, pro, enterprise)
        
    Returns:
        Rate limit per minute
    """
    return PLAN_RATE_LIMITS.get(plan, PLAN_RATE_LIMITS["free"])


def get_rate_limit_key(request) -> str:
    """
    Get rate limit key from request.
    Uses tenant_id if available, otherwise falls back to IP.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Rate limit key (tenant_id or IP)
    """
    # Try to get tenant_id from request state (set by auth middleware)
    if hasattr(request.state, 'tenant_id') and request.state.tenant_id:
        return f"tenant:{request.state.tenant_id}"
    
    # Try to get from header
    tenant_header = request.headers.get("X-Tenant-ID")
    if tenant_header:
        return f"tenant:{tenant_header}"
    
    # Fall back to IP address
    return get_remote_address(request)


def create_limiter() -> Limiter:
    """
    Create a tenant-aware rate limiter.
    
    Returns:
        Configured Limiter instance
    """
    limiter = Limiter(key_func=get_rate_limit_key)
    return limiter


class TenantRateLimiter:
    """
    Tenant-aware rate limiter that applies different limits based on plan.
    """
    
    def __init__(self):
        self._limiter = Limiter(key_func=self._get_key)
    
    def _get_key(self, request) -> str:
        """Get rate limit key with plan awareness."""
        # Get tenant info from request state
        if hasattr(request.state, 'tenant_id') and request.state.tenant_id:
            return f"tenant:{request.state.tenant_id}"
        
        # Fall back to IP
        return get_remote_address(request)
    
    def limit(self, plan: str = "free"):
        """
        Rate limit decorator with plan-based limits.
        
        Args:
            plan: Tenant plan (determines rate limit)
            
        Returns:
            Rate limit decorator
        """
        limit_value = get_tenant_rate_limit(plan)
        
        # Allow override via environment
        env_limit = os.getenv(f"RATE_LIMIT_{plan.upper()}")
        if env_limit:
            limit_value = int(env_limit)
        
        return self._limiter.limit(f"{limit_value}/minute")
    
    @property
    def limiter(self) -> Limiter:
        return self._limiter


# Global instance
_tenant_rate_limiter: Optional[TenantRateLimiter] = None


def get_tenant_rate_limiter() -> TenantRateLimiter:
    """Get or create the global tenant rate limiter."""
    global _tenant_rate_limiter
    if _tenant_rate_limiter is None:
        _tenant_rate_limiter = TenantRateLimiter()
    return _tenant_rate_limiter
