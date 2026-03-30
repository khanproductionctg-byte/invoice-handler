"""
FastAPI dependency for automatic audit logging.
Add this to any route that needs audit logging.
"""
from functools import wraps
from typing import Callable, Optional
from fastapi import Request, Depends
from starlette.datastructures import Headers

from utils.audit_logger import get_audit_logger, AuditAction


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    # Check for forwarded headers (behind proxy)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    # Check for real IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fall back to direct client
    if request.client:
        return request.client.host
    
    return "unknown"


def get_user_agent(request: Request) -> str:
    """Extract user agent from request."""
    return request.headers.get("User-Agent", "unknown")


def audit_log(
    action: str,
    resource_type: str,
    resource_id_param: str = "id"
):
    """
    FastAPI dependency factory for audit logging.
    
    Usage:
        @router.post("/invoices")
        def create_invoice(
            invoice: InvoiceCreate,
            audit: dict = Depends(audit_log("create", "invoice"))
        ):
            ...
    
    Or use the automatic version that detects CRUD:
        @router.post("/invoices")
        @auto_audit_log("invoice", "id")
        def create_invoice(invoice: InvoiceCreate, ...):
            ...
    """
    def dependency(request: Request) -> dict:
        return {
            "request": request,
            "action": action,
            "resource_type": resource_type,
            "resource_id_param": resource_id_param,
            "ip_address": get_client_ip(request),
            "user_agent": get_user_agent(request),
            "method": request.method,
            "path": request.url.path
        }
    
    return dependency


def auto_audit_middleware(app):
    """
    ASGI middleware for automatic audit logging on all requests.
    Add to your FastAPI app:
    
        from utils.audit_middleware import auto_audit_middleware
        app = FastAPI()
        app = auto_audit_middleware(app)
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    
    class AuditMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Skip certain paths
            skip_paths = {"/health", "/metrics", "/docs", "/openapi.json", "/redoc"}
            if request.url.path in skip_paths or request.url.path.startswith("/docs"):
                return await call_next(request)
            
            # Get user info if available
            user_id = None
            tenant_id = None
            
            # Try to get user from request state (set by auth middleware)
            if hasattr(request.state, "user_id"):
                user_id = request.state.user_id
            if hasattr(request.state, "tenant_id"):
                tenant_id = request.state.tenant_id
            
            # Get client info
            ip_address = get_client_ip(request)
            user_agent = get_user_agent(request)
            
            # Process request
            response = await call_next(request)
            
            # Log the request (for write operations)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                # Determine resource type from path
                path_parts = request.url.path.strip("/").split("/")
                resource_type = path_parts[0] if path_parts else "unknown"
                
                # Determine action
                action_map = {
                    "POST": AuditAction.CREATE,
                    "PUT": AuditAction.UPDATE,
                    "PATCH": AuditAction.UPDATE,
                    "DELETE": AuditAction.DELETE
                }
                action = action_map.get(request.method, AuditAction.READ)
                
                # Only log if we have tenant info
                if tenant_id:
                    # Get audit logger and log
                    audit_logger = get_audit_logger()
                    
                    # Skip logging for certain endpoints
                    skip_resources = {"auth", "oauth", "webhooks", "admin", "docs"}
                    if resource_type not in skip_resources:
                        audit_logger.log(
                            action=action,
                            resource_type=resource_type,
                            tenant_id=tenant_id,
                            user_id=user_id,
                            request_method=request.method,
                            request_path=request.url.path,
                            ip_address=ip_address,
                            user_agent=user_agent,
                            status="success" if response.status_code < 400 else "failure",
                            error_message=None if response.status_code < 400 else f"HTTP {response.status_code}"
                        )
            
            return response
    
    return AuditMiddleware(app)


# Helper function to manually log audit events from route handlers
async def log_audit_event(
    request: Request,
    action: str,
    resource_type: str,
    tenant_id: int,
    user_id: Optional[int] = None,
    resource_id: Optional[int] = None,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    status: str = "success",
    error_message: Optional[str] = None
):
    """
    Log an audit event from a route handler.
    
    Usage in route:
        await log_audit_event(
            request=request,
            action="create",
            resource_type="invoice",
            tenant_id=tenant.id,
            user_id=user.id,
            resource_id=invoice.id,
            new_values=invoice.model_dump()
        )
    """
    audit_logger = get_audit_logger()
    
    audit_logger.log(
        action=action,
        resource_type=resource_type,
        tenant_id=tenant_id,
        user_id=user_id,
        resource_id=resource_id,
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        request_method=request.method,
        request_path=request.url.path,
        old_values=old_values,
        new_values=new_values,
        status=status,
        error_message=error_message
    )
