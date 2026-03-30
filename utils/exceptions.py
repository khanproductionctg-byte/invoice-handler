"""
Workflow-specific exceptions for the Invoice Handler system.
"""
from fastapi import HTTPException, status


class WorkflowAlreadyRunningError(HTTPException):
    """Raised when a workflow is already running for a tenant."""
    def __init__(self, tenant_id: int, message: str = None):
        detail = message or f"Workflow already running for tenant {tenant_id}. Please wait for it to complete."
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail
        )


class WorkflowTimeoutError(HTTPException):
    """Raised when a workflow exceeds its timeout."""
    def __init__(self, workflow_id: str, timeout_seconds: int):
        super().__init__(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Workflow {workflow_id} timed out after {timeout_seconds} seconds."
        )


class WorkflowNotFoundError(HTTPException):
    """Raised when a workflow is not found."""
    def __init__(self, workflow_id: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found."
        )


class MaxStepsExceededError(HTTPException):
    """Raised when workflow exceeds max steps limit."""
    def __init__(self, max_steps: int):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Workflow exceeded maximum step limit of {max_steps}."
        )
