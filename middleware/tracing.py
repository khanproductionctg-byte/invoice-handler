"""
Request tracing middleware for adding request_id to all logs.
Provides distributed tracing capability across the application.
"""
import uuid
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "x-request-id"


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds a unique request_id to each request.
    The request_id is added to:
    - Response headers
    - Log records (via contextvars)
    - Request state (accessible in route handlers)
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate or extract request_id
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        
        # Store in request state for access in handlers
        request.state.request_id = request_id
        
        # Add to response headers
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        
        return response


def get_request_id(request: Request) -> str:
    """
    Get request_id from request state.
    Returns a default if not set.
    """
    return getattr(request.state, "request_id", "unknown")


class RequestIdFilter(logging.Filter):
    """
    Logging filter that adds request_id to log records.
    Use with structlog or standard logging.
    """
    
    def __init__(self, request: Request = None):
        super().__init__()
        self.request = request
    
    def filter(self, record: logging.LogRecord) -> bool:
        if self.request:
            record.request_id = getattr(self.request.state, "request_id", "unknown")
        else:
            record.request_id = "background"
        return True
