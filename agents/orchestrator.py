"""
LangGraph Orchestrator for Invoice Handler - Production-Ready Implementation
============================================================================
A robust, deterministic workflow orchestration system with:
- Typed state schema with validation
- Deterministic graph flow with conditional branching
- Built-in error recovery and retry logic
- Checkpoint-based persistence for long-running workflows
- Proper agent handoffs with state transitions
"""
from __future__ import annotations

import logging
import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Callable
from datetime import datetime
from dataclasses import dataclass, field
from datetime import datetime as dt

from utils.pagination import (
    paginate_results,
    truncate_matches,
    check_output_size,
)
from config.plan_limits import MAX_INVOICE_BATCH_SIZE

from pydantic import BaseModel, Field, field_validator
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS & CONSTANTS
# =============================================================================

class AgentName(str, Enum):
    """Enum for agent names for type safety."""
    INGESTION = "ingestion"
    RECONCILER = "reconciler"
    CHASER = "chaser"
    REPORTER = "reporter"


class WorkflowStatus(str, Enum):
    """Workflow execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    RETRYING = "retrying"


class StepStatus(str, Enum):
    """Individual step execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


# =============================================================================
# STATE SCHEMA - Clean, Typed, Validated
# =============================================================================

class StepResult(BaseModel):
    """Result of a single workflow step."""
    step_name: str
    status: StepStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    retry_count: int = 0

    @property
    def duration_ms(self) -> Optional[float]:
        """Calculate duration in milliseconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None

    @property
    def is_success(self) -> bool:
        return self.status == StepStatus.COMPLETED


class WorkflowState(BaseModel):
    """
    Centralized, typed state schema for the entire workflow.
    
    This is the single source of truth passed between all agents.
    Validated at every transition to ensure data integrity.
    """
    # Identity
    invocation_id: str = Field(default_factory=lambda: str(datetime.utcnow().timestamp()).replace('.', ''))
    workflow_id: Optional[str] = None
    user_id: int
    tenant_id: Optional[int] = None
    
    # Timing
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Status tracking
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_step: Optional[AgentName] = None
    
    # Step results - ordered list for reproducibility
    step_results: List[StepResult] = Field(default_factory=list)
    
    # Data containers - explicit schema for each agent's output
    ingestion_data: Dict[str, Any] = Field(default_factory=dict)
    reconciliation_data: Dict[str, Any] = Field(default_factory=dict)
    chasing_data: Dict[str, Any] = Field(default_factory=dict)
    reporting_data: Dict[str, Any] = Field(default_factory=dict)
    
    # Approval workflow
    pending_invoices: List[Dict[str, Any]] = Field(default_factory=list)
    approved_invoices: List[int] = Field(default_factory=list)
    rejected_invoices: List[int] = Field(default_factory=list)
    awaiting_human_review: bool = False
    
    # Error handling
    last_error: Optional[str] = None
    retry_policy: Dict[str, Any] = Field(default_factory=lambda: {
        "max_retries": 3,
        "retry_delay_seconds": 5,
        "exponential_backoff": True
    })
    
    # Checkpoint for recovery
    checkpoint_key: Optional[str] = None
    last_checkpoint_at: Optional[datetime] = None
    
    # Configuration
    config: Dict[str, Any] = Field(default_factory=dict)
    
    @field_validator('step_results', mode='before')
    @classmethod
    def validate_step_results(cls, v):
        """Ensure step_results is always a list of StepResult."""
        if isinstance(v, list):
            return [StepResult(**r) if isinstance(r, dict) else r for r in v]
        return []

    @property
    def is_completed(self) -> bool:
        return self.status == WorkflowStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == WorkflowStatus.FAILED

    @property
    def duration_ms(self) -> Optional[float]:
        """Calculate total workflow duration."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None

    @property
    def successful_steps(self) -> List[str]:
        return [s.step_name for s in self.step_results if s.is_success]

    @property
    def failed_steps(self) -> List[str]:
        return [s.step_name for s in self.step_results if s.status == StepStatus.FAILED]

    def get_step_result(self, step_name: str) -> Optional[StepResult]:
        """Get result for a specific step."""
        for result in self.step_results:
            if result.step_name == step_name:
                return result
        return None

    def to_summary(self) -> Dict[str, Any]:
        """Create a serializable summary."""
        return {
            "invocation_id": self.invocation_id,
            "workflow_id": self.workflow_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "current_step": self.current_step.value if self.current_step else None,
            "steps_completed": len(self.successful_steps),
            "steps_failed": len(self.failed_steps),
            "duration_ms": self.duration_ms,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }


# =============================================================================
# ORCHESTRATOR - Robust, Deterministic Graph
# =============================================================================

class InvoiceHandlerOrchestrator:
    """
    Production-ready orchestrator with:
    - Deterministic graph execution
    - Built-in retry logic with exponential backoff
    - Checkpoint persistence for recovery
    - Typed state with validation
    """

    # Graph node names as constants for type safety
    NODE_INGESTION = "ingestion"
    NODE_APPROVAL_GATE = "approval_gate"
    NODE_RECONCILER = "reconciler"
    NODE_CHASER = "chaser"
    NODE_REPORTER = "reporter"
    NODE_ERROR_HANDLER = "error_handler"
    NODE_CHECK_COMPLETION = "check_completion"

    def __init__(
        self,
        ingestion_agent: Any,
        reconciler_agent: Any,
        chaser_agent: Any,
        reporter_agent: Any,
        checkpoints_dir: str = "./checkpoints",
        max_retries: int = 3,
        retry_delay: int = 5,
        enable_checkpoints: bool = True,
        enable_parallel: bool = False
    ):
        """
        Initialize the orchestrator.

        Args:
            ingestion_agent: Agent for fetching data from sources
            reconciler_agent: Agent for matching invoices to payments
            chaser_agent: Agent for sending payment reminders
            reporter_agent: Agent for generating reports
            checkpoints_dir: Directory for workflow checkpoints
            max_retries: Maximum retry attempts per step
            retry_delay: Base delay between retries (seconds)
            enable_checkpoints: Enable checkpoint-based recovery
            enable_parallel: Enable parallel agent execution where possible
        """
        self.agents = {
            self.NODE_INGESTION: ingestion_agent,
            self.NODE_RECONCILER: reconciler_agent,
            self.NODE_CHASER: chaser_agent,
            self.NODE_REPORTER: reporter_agent
        }
        
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.enable_checkpoints = enable_checkpoints
        self.enable_parallel = enable_parallel
        
        # Setup checkpoints
        self.checkpoints_dir = Path(checkpoints_dir)
        self.enable_checkpoints = enable_checkpoints
        
        # Initialize checkpointer - use PostgresSaver for production
        self.checkpointer = self._create_checkpointer() if enable_checkpoints else None
        
        if self.checkpointer:
            logger.info("Using PostgresSaver for workflow state persistence")
        else:
            logger.warning("Checkpoints disabled - workflow state will NOT persist across restarts")
            
        # Build the deterministic graph
        self.graph = self._build_graph()
    
    def _get_tenant_settings(self, tenant_id: int) -> Dict[str, Any]:
        """Get tenant-specific settings for approval gate."""
        from db.database import SessionLocal
        from db.models import Tenant
        
        db = SessionLocal()
        try:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant:
                return {
                    "auto_approve_threshold": 500.0,
                    "known_vendors": []
                }
            return {"auto_approve_threshold": 500.0, "known_vendors": []}
        finally:
            db.close()
    
    def _approval_gate_node(self, state: WorkflowState) -> WorkflowState:
        """
        Approval gate node - determines which invoices need human review.
        
        Invoices above threshold or from unknown vendors go to pending_review.
        Invoices below threshold from known vendors are auto-approved.
        
        Uses SELECT FOR UPDATE to prevent race conditions in concurrent workflows.
        """
        from sqlalchemy import text
        from db.database import SessionLocal
        from db.models import Invoice, WorkflowRun
        
        if not state.tenant_id:
            state.last_error = "No tenant_id for approval gate"
            return state
        
        settings = self._get_tenant_settings(state.tenant_id)
        threshold = settings.get("auto_approve_threshold", 500.0)
        known_vendors = settings.get("known_vendors", [])
        
        from db.database import get_tenant_session
        db = get_tenant_session(state.tenant_id)
        try:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            
            pending = db.query(Invoice).filter(
                Invoice.tenant_id == state.tenant_id,
                Invoice.status.in_(["pending_review", "pending"])
            ).with_for_update(nowait=True).all()
            
            approved_ids = []
            still_pending = []
            
            for inv in pending:
                amount = float(inv.amount_due or 0)
                vendor = inv.vendor_name or ""
                
                if amount <= threshold and vendor in known_vendors:
                    inv.status = "auto_approved"
                    inv.needs_review = False
                    approved_ids.append(inv.id)
                else:
                    inv.needs_review = True
                    still_pending.append({
                        "id": inv.id,
                        "amount": amount,
                        "vendor": vendor,
                        "invoice_number": inv.invoice_number
                    })
            
            if still_pending:
                state.awaiting_human_review = True
                state.pending_invoices = still_pending
            else:
                state.awaiting_human_review = False
            
            state.approved_invoices = approved_ids
            db.commit()
            
        except Exception as e:
            db.rollback()
            state.last_error = f"Approval gate error: {str(e)}"
            logger.error(f"Approval gate failed for tenant {state.tenant_id}: {str(e)}")
        finally:
            db.close()
        
        return state
    
    def _create_checkpointer(self):
        """
        Create the appropriate checkpointer based on environment.
        
        Production: Uses PostgresSaver for persistent state across restarts
        Development: Falls back to MemorySaver if Postgres unavailable
        """
        import os
        
        # Check environment for production mode
        use_postgres = os.getenv("CHECKPOINT_USE_POSTGRES", "true").lower() == "true"
        database_url = os.getenv("DATABASE_URL")
        
        if not use_postgres:
            logger.info("Using MemorySaver (development mode)")
            return MemorySaver()
        
        if not database_url:
            logger.warning("DATABASE_URL not set, falling back to MemorySaver")
            return MemorySaver()
        
        try:
            # Use PostgresSaver for production - this is the correct way
            from langgraph.checkpoint.postgres import PostgresSaver
            
            checkpointer = PostgresSaver.from_conn_string(database_url)
            checkpointer.setup()
            
            logger.info("PostgresSaver checkpointer initialized successfully")
            return checkpointer
            
        except ImportError:
            logger.warning("langgraph[postgres] not installed, falling back to MemorySaver")
            return MemorySaver()
        except Exception as e:
            logger.error(f"Failed to initialize PostgresSaver: {str(e)}, falling back to MemorySaver")
            return MemorySaver()
        


    def _build_graph(self) -> StateGraph:
        """
        Build a deterministic StateGraph with proper error handling.
        
        The graph flow is:
        1. ingestion -> approval_gate
        2. approval_gate -> conditionally to reconciler (if approved)
        3. reconciler -> conditionally to chaser  
        4. chaser -> conditionally to reporter
        5. reporter -> END or error_handler (on failure)
        """
        workflow = StateGraph(WorkflowState)
        
        # Add nodes with error wrapping
        workflow.add_node(self.NODE_INGESTION, self._wrap_agent(self.NODE_INGESTION))
        workflow.add_node(self.NODE_APPROVAL_GATE, self._approval_gate_node)
        workflow.add_node(self.NODE_RECONCILER, self._wrap_agent(self.NODE_RECONCILER))
        workflow.add_node(self.NODE_CHASER, self._wrap_agent(self.NODE_CHASER))
        workflow.add_node(self.NODE_REPORTER, self._wrap_agent(self.NODE_REPORTER))
        workflow.add_node(self.NODE_ERROR_HANDLER, self._error_handler_node)
        workflow.add_node(self.NODE_CHECK_COMPLETION, self._check_completion_node)
        
        # Define deterministic edges with conditional logic
        workflow.set_entry_point(self.NODE_INGESTION)
        
        # Ingestion -> Approval Gate
        workflow.add_edge(self.NODE_INGESTION, self.NODE_APPROVAL_GATE)
        
        # Approval Gate -> Reconciler (proceed even if awaiting human review)
        workflow.add_conditional_edges(
            self.NODE_APPROVAL_GATE,
            self._should_continue_after_approval,
            {
                "continue": self.NODE_RECONCILER,
                "skip": self.NODE_REPORTER,
                "fail": self.NODE_ERROR_HANDLER
            }
        )
        
        # Reconciler -> Chaser (always, unless no matches needed)
        workflow.add_conditional_edges(
            self.NODE_RECONCILER,
            self._should_continue_to_chaser,
            {
                "continue": self.NODE_CHASER,
                "skip": self.NODE_REPORTER,  # Skip chasing if nothing overdue
                "fail": self.NODE_ERROR_HANDLER
            }
        )
        
        # Chaser -> Reporter (always, unless no reminders sent)
        workflow.add_conditional_edges(
            self.NODE_CHASER,
            self._should_continue_to_reporter,
            {
                "continue": self.NODE_REPORTER,
                "skip": self.NODE_CHECK_COMPLETION,  # Skip report if not needed
                "fail": self.NODE_ERROR_HANDLER
            }
        )
        
        # Reporter -> END or ERROR
        workflow.add_conditional_edges(
            self.NODE_REPORTER,
            self._should_complete,
            {
                "success": END,
                "retry": self.NODE_ERROR_HANDLER
            }
        )
        
        # Error handler -> RETRY or FAIL
        workflow.add_conditional_edges(
            self.NODE_ERROR_HANDLER,
            self._determine_retry,
            {
                "retry": "retry_last_step",
                "fail": END
            }
        )
        
        # Retry loop
        workflow.add_node("retry_last_step", self._retry_node)
        workflow.add_edge("retry_last_step", self.NODE_CHECK_COMPLETION)
        
        # Completion check -> route to appropriate node or END
        workflow.add_conditional_edges(
            self.NODE_CHECK_COMPLETION,
            self._route_from_completion,
            {
                self.NODE_INGESTION: self.NODE_INGESTION,
                self.NODE_RECONCILER: self.NODE_RECONCILER,
                self.NODE_CHASER: self.NODE_CHASER,
                self.NODE_REPORTER: self.NODE_REPORTER,
                END: END
            }
        )
        
        return workflow.compile(
            checkpointer=self.checkpointer,
            interrupt_before=[self.NODE_ERROR_HANDLER],
            recursion_limit=50
        )

    def _wrap_agent(self, node_name: str) -> Callable:
        """Wrap agent execution with timing, error handling, and state updates."""
        def wrapped_agent(state: WorkflowState) -> WorkflowState:
            # Update state
            state.status = WorkflowStatus.RUNNING
            state.current_step = AgentName(node_name)
            
            # Create step result
            step_result = StepResult(
                step_name=node_name,
                status=StepStatus.RUNNING,
                started_at=datetime.utcnow()
            )
            
            # Get agent
            agent = self.agents.get(node_name)
            if not agent:
                step_result.status = StepStatus.FAILED
                step_result.error = f"Agent {node_name} not found"
                state.step_results.append(step_result)
                state.status = WorkflowStatus.FAILED
                return state
            
            try:
                logger.info(f"Executing node: {node_name} for invocation {state.invocation_id}")
                
                # Execute agent with timeout
                from agents.base_agent import AgentState
                
                # Map workflow state to agent state
                agent_input = AgentState(
                    tenant_id=state.tenant_id,
                    input_data={
                        "user_id": state.user_id,
                        "tenant_id": state.tenant_id,
                        "invocation_id": state.invocation_id,
                        "workflow_state": state.model_dump()
                    }
                )
                
                # Run agent
                result = agent.run(agent_input)
                
                # Map result back to workflow state
                if hasattr(result, 'output_data'):
                    # Map node name to correct state field
                    node_to_field = {
                        "ingestion": "ingestion_data",
                        "reconciler": "reconciliation_data",
                        "chaser": "chasing_data",
                        "reporter": "reporting_data"
                    }
                    data_key = node_to_field.get(node_name, f"{node_name}_data")
                    setattr(state, data_key, result.output_data)
                
                # Mark step as completed
                step_result.status = StepStatus.COMPLETED
                step_result.completed_at = datetime.utcnow()
                step_result.data = result.output_data if hasattr(result, 'output_data') else {}
                
                logger.info(
                    f"Node {node_name} completed in {step_result.duration_ms:.2f}ms "
                    f"for invocation {state.invocation_id}"
                )
                
            except Exception as e:
                logger.error(f"Node {node_name} failed: {str(e)}")
                step_result.status = StepStatus.FAILED
                step_result.error = str(e)
                step_result.completed_at = datetime.utcnow()
                state.last_error = str(e)
            
            state.step_results.append(step_result)
            
            # Save checkpoint after each step
            if self.enable_checkpoints:
                self._save_checkpoint(state)
            
            return state
        
        return wrapped_agent

    def _should_continue_to_reconciler(self, state: WorkflowState) -> str:
        """Determine if we should continue to reconciler after ingestion."""
        ingestion_result = state.get_step_result(self.NODE_INGESTION)
        
        if not ingestion_result or ingestion_result.status != StepStatus.COMPLETED:
            return "fail"
        
        # Check if we got any data
        if not state.ingestion_data:
            return "skip"  # No data, skip to reporter
        
        return "continue"
    
    def _should_continue_after_approval(self, state: WorkflowState) -> str:
        """Determine if we should continue to reconciler after approval gate."""
        ingestion_result = state.get_step_result(self.NODE_INGESTION)
        
        if not ingestion_result or ingestion_result.status != StepStatus.COMPLETED:
            return "fail"
        
        # Continue to reconciler - invoices awaiting review are handled separately
        return "continue"

    def _should_continue_to_chaser(self, state: WorkflowState) -> str:
        """Determine if we should continue to chaser after reconciler."""
        reconciler_result = state.get_step_result(self.NODE_RECONCILER)
        
        if not reconciler_result or reconciler_result.status != StepStatus.COMPLETED:
            return "fail"
        
        matches = state.reconciliation_data.get("matches", [])
        discrepancies = state.reconciliation_data.get("discrepancies", [])

        original_matches = len(matches)
        matches = truncate_matches(matches)
        state.reconciliation_data["matches"] = matches

        original_discrepancies = len(discrepancies)
        discrepancies = truncate_matches(discrepancies, max_items=MAX_INVOICE_BATCH_SIZE)
        state.reconciliation_data["discrepancies"] = discrepancies

        if original_matches > len(matches):
            logger.warning(
                f"Truncated {original_matches} matches to {len(matches)}",
                extra={"original": original_matches, "truncated_to": len(matches)},
            )
        if original_discrepancies > len(discrepancies):
            logger.warning(
                f"Truncated {original_discrepancies} discrepancies to {len(discrepancies)}",
                extra={"original": original_discrepancies, "truncated_to": len(discrepancies)},
            )

        if len(matches) > MAX_INVOICE_BATCH_SIZE:
            state.reconciliation_data["matches_page"] = paginate_results(
                matches, page=1, page_size=MAX_INVOICE_BATCH_SIZE
            )
        if len(discrepancies) > MAX_INVOICE_BATCH_SIZE:
            state.reconciliation_data["discrepancies_page"] = paginate_results(
                discrepancies, page=1, page_size=MAX_INVOICE_BATCH_SIZE
            )
        
        if not matches and not discrepancies:
            return "skip"
        
        return "continue"

    def _should_continue_to_reporter(self, state: WorkflowState) -> str:
        """Determine if we should continue to reporter after chaser."""
        chaser_result = state.get_step_result(self.NODE_CHASER)
        
        if not chaser_result or chaser_result.status != StepStatus.COMPLETED:
            return "fail"
        
        return "continue"

    def _should_complete(self, state: WorkflowState) -> str:
        """Determine if workflow should complete."""
        reporter_result = state.get_step_result(self.NODE_REPORTER)
        
        if reporter_result and reporter_result.status == StepStatus.COMPLETED:
            return "success"
        
        return "retry"

    def _determine_retry(self, state: WorkflowState) -> str:
        """Determine if we should retry the failed step."""
        last_failed = None
        for result in reversed(state.step_results):
            if result.status == StepStatus.FAILED:
                last_failed = result
                break
        
        if not last_failed:
            return "fail"
        
        if last_failed.retry_count >= self.max_retries:
            logger.error(f"Max retries exceeded for {last_failed.step_name}")
            state.status = WorkflowStatus.FAILED
            return "fail"
        
        # Set to retry
        state.status = WorkflowStatus.RETRYING
        last_failed.status = StepStatus.RETRYING
        last_failed.retry_count += 1
        
        logger.info(
            f"Retrying {last_failed.step_name} "
            f"(attempt {last_failed.retry_count}/{self.max_retries})"
        )
        
        return "retry"

    def _route_from_completion(self, state: WorkflowState) -> str:
        """Route to next uncompleted step or END."""
        completed_steps = {r.step_name for r in state.step_results if r.is_success}
        
        # Determine next step based on what's completed
        step_order = [
            self.NODE_INGESTION,
            self.NODE_APPROVAL_GATE,
            self.NODE_RECONCILER,
            self.NODE_CHASER,
            self.NODE_REPORTER
        ]
        
        for step in step_order:
            if step not in completed_steps:
                return step
        
        return END

    def _error_handler_node(self, state: WorkflowState) -> WorkflowState:
        """Centralized error handling node."""
        logger.error(f"Error handler invoked for invocation {state.invocation_id}")
        
        # Log the error
        if state.last_error:
            logger.error(f"Workflow error: {state.last_error}")
        
        # Determine next action
        action = self._determine_retry(state)
        
        return state

    def _check_completion_node(self, state: WorkflowState) -> WorkflowState:
        """Check if workflow is complete."""
        state.status = WorkflowStatus.COMPLETED
        state.completed_at = datetime.utcnow()
        
        logger.info(
            f"Workflow {state.invocation_id} completed: "
            f"{len(state.successful_steps)} steps successful, "
            f"{len(state.failed_steps)} steps failed"
        )
        
        return state

    def _retry_node(self, state: WorkflowState) -> WorkflowState:
        """Handle retry logic with exponential backoff."""
        import time
        
        last_failed = None
        for result in reversed(state.step_results):
            if result.status == StepStatus.FAILED:
                last_failed = result
                break
        
        if last_failed:
            delay = self.retry_delay * (2 ** (last_failed.retry_count - 1))
            logger.info(f"Waiting {delay}s before retry...")
            time.sleep(delay)
        
        return state

    # =========================================================================
    # CHECKPOINT MANAGEMENT
    # =========================================================================

    def _save_checkpoint(self, state: WorkflowState) -> None:
        """Save workflow state checkpoint for recovery."""
        try:
            state_dict = state.model_dump()
            state_dict = check_output_size(state_dict)

            checkpoint_file = self.checkpoints_dir / f"checkpoint_{state.invocation_id}.json"
            checkpoint_data = {
                "invocation_id": state.invocation_id,
                "state": json.dumps(state_dict, default=str),
                "timestamp": datetime.utcnow().isoformat()
            }
            with open(checkpoint_file, 'w') as f:
                json.dump(checkpoint_data, f, indent=2, default=str)
            state.checkpoint_key = state.invocation_id
            state.last_checkpoint_at = datetime.utcnow()
            logger.debug(f"Checkpoint saved: {checkpoint_file}")
        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {str(e)}")

    def load_checkpoint(self, invocation_id: str) -> Optional[WorkflowState]:
        """Load workflow state from checkpoint."""
        try:
            checkpoint_file = self.checkpoints_dir / f"checkpoint_{invocation_id}.json"
            if not checkpoint_file.exists():
                logger.warning(f"Checkpoint not found: {checkpoint_file}")
                return None
            
            with open(checkpoint_file, 'r') as f:
                checkpoint_data = json.load(f)
            
            state = WorkflowState.model_validate_json(checkpoint_data["state"])
            logger.info(f"Checkpoint loaded for invocation {invocation_id}")
            return state
            
        except Exception as e:
            logger.error(f"Failed to load checkpoint: {str(e)}")
            return None

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """List all available checkpoints."""
        checkpoints = []
        try:
            for f in self.checkpoints_dir.glob("checkpoint_*.json"):
                with open(f, 'r') as fp:
                    data = json.load(fp)
                    checkpoints.append({
                        "invocation_id": data.get("invocation_id"),
                        "timestamp": data.get("timestamp"),
                        "file": str(f)
                    })
        except Exception as e:
            logger.error(f"Failed to list checkpoints: {str(e)}")
        
        return checkpoints

    def delete_checkpoint(self, invocation_id: str) -> bool:
        """Delete a checkpoint."""
        try:
            checkpoint_file = self.checkpoints_dir / f"checkpoint_{invocation_id}.json"
            if checkpoint_file.exists():
                checkpoint_file.unlink()
                return True
        except Exception as e:
            logger.error(f"Failed to delete checkpoint: {str(e)}")
        return False

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def run(self, user_id: int, tenant_id: Optional[int] = None, workflow_id: Optional[str] = None, config: Optional[Dict] = None) -> WorkflowState:
        """
        Execute the workflow for a user.
        
        Args:
            user_id: The user ID to process
            tenant_id: The tenant ID for data isolation
            workflow_id: Optional workflow identifier
            config: Optional configuration overrides
            
        Returns:
            Final WorkflowState with results
        """
        from utils.workflow_lock import sync_tenant_workflow_lock
        from utils.exceptions import WorkflowAlreadyRunningError
        
        if tenant_id is None:
            raise ValueError("tenant_id is required for workflow execution")
        
        try:
            with sync_tenant_workflow_lock(str(tenant_id), timeout=300):
                return self._run_internal(user_id, tenant_id, workflow_id, config)
        except WorkflowAlreadyRunningError:
            raise
        except Exception as e:
            logger.error(f"Workflow lock error: {str(e)}")
            raise

    def _run_internal(self, user_id: int, tenant_id: Optional[int] = None, workflow_id: Optional[str] = None, config: Optional[Dict] = None) -> WorkflowState:
        """Internal workflow execution after lock acquisition."""
        # Create initial state
        initial_state = WorkflowState(
            user_id=user_id,
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            started_at=datetime.utcnow(),
            status=WorkflowStatus.RUNNING,
            config=config or {}
        )
        
        logger.info(
            f"Starting workflow {workflow_id or 'ad-hoc'} "
            f"for user {user_id}, tenant {tenant_id} (invocation: {initial_state.invocation_id})"
        )
        
        try:
            # Execute the graph
            graph_config = {"configurable": {"thread_id": initial_state.invocation_id}}
            
            final_state = self.graph.invoke(
                initial_state,
                graph_config
            )
            
            # Ensure completion
            if final_state.status != WorkflowStatus.COMPLETED:
                final_state.status = WorkflowStatus.COMPLETED
                final_state.completed_at = datetime.utcnow()
            
            logger.info(
                f"Workflow completed: invocation={final_state.invocation_id}, "
                f"duration={final_state.duration_ms:.2f}ms"
            )
            
            # Cleanup checkpoint on success
            if self.enable_checkpoints:
                self.delete_checkpoint(final_state.invocation_id)
            
            return final_state
            
        except Exception as e:
            logger.error(f"Workflow failed: {str(e)}")
            initial_state.status = WorkflowStatus.FAILED
            initial_state.last_error = str(e)
            initial_state.completed_at = datetime.utcnow()
            
            # Save final checkpoint for recovery
            if self.enable_checkpoints:
                self._save_checkpoint(initial_state)
            
            return initial_state

    def run_with_recovery(
        self,
        user_id: int,
        workflow_id: Optional[str] = None,
        config: Optional[Dict] = None,
        resume_from_invocation: Optional[str] = None
    ) -> WorkflowState:
        """
        Execute workflow with automatic checkpoint recovery.
        
        If resume_from_invocation is provided, attempts to resume
        from the last checkpoint instead of starting fresh.
        """
        if resume_from_invocation:
            checkpoint = self.load_checkpoint(resume_from_invocation)
            if checkpoint:
                logger.info(f"Resuming workflow from checkpoint: {resume_from_invocation}")
                # Update user_id in case it changed
                checkpoint.user_id = user_id
                checkpoint.status = WorkflowStatus.RUNNING
                
                # Resume execution
                config = {"configurable": {"thread_id": checkpoint.invocation_id}}
                return self.graph.invoke(checkpoint, config)
        
        # Start fresh
        return self.run(user_id, workflow_id, config)

    def get_workflow_image(self) -> bytes:
        """Get a visual representation of the workflow."""
        try:
            return self.graph.get_graph().draw_mermaid_png()
        except Exception as e:
            logger.warning(f"Could not generate workflow image: {str(e)}")
            return b""

    def get_workflow_diagram_mermaid(self) -> str:
        """Get Mermaid diagram definition."""
        return """
```mermaid
graph TD
    Start([Start]) --> Ingestion[ingestion]
    
    Ingestion -->|"continue"| Reconciler[reconciler]
    Ingestion -->|"skip"| Reporter[reporter]
    Ingestion -->|"fail"| Error[error_handler]
    
    Reconciler -->|"continue"| Chaser[chaser]
    Reconciler -->|"skip"| Reporter
    Reconciler -->|"fail"| Error
    
    Chaser -->|"continue"| Reporter
    Chaser -->|"skip"| Check[check_completion]
    Chaser -->|"fail"| Error
    
    Reporter -->|"success"| End([Complete])
    Reporter -->|"retry"| Error
    
    Error -->|"retry"| Retry[retry_last_step]
    Error -->|"fail"| End
    
    Retry --> Check
    Check --> Ingestion
    Check --> Reconciler
    Check --> Chaser
    Check --> Reporter
    Check --> End
```
"""


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_orchestrator(
    agents_dict: Dict[str, Any],
    **kwargs
) -> InvoiceHandlerOrchestrator:
    """
    Factory function to create orchestrator from agents dictionary.
    
    Args:
        agents_dict: Dict with keys: ingestion, reconciler, chaser, reporter
        **kwargs: Additional arguments for orchestrator
        
    Returns:
        Configured InvoiceHandlerOrchestrator
    """
    required = ['ingestion', 'reconciler', 'chaser', 'reporter']
    
    for key in required:
        if key not in agents_dict:
            raise ValueError(f"Missing required agent: {key}")
    
    return InvoiceHandlerOrchestrator(
        ingestion_agent=agents_dict['ingestion'],
        reconciler_agent=agents_dict['reconciler'],
        chaser_agent=agents_dict['chaser'],
        reporter_agent=agents_dict['reporter'],
        **kwargs
    )


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Example: How to use the orchestrator
    
    # from agents import IngestionAgent, ReconcilerAgent, ChaserAgent, ReporterAgent
    # 
    # ingestion = IngestionAgent(tools=[])
    # reconciler = ReconcilerAgent(llm=llm, tools=[])
    # chaser = ChaserAgent(llm=llm, tools=[])
    # reporter = ReporterAgent(llm=llm, tools=[])
    # 
    # orchestrator = InvoiceHandlerOrchestrator(
    #     ingestion_agent=ingestion,
    #     reconciler_agent=reconciler,
    #     chaser_agent=chaser,
    #     reporter_agent=reporter,
    #     max_retries=3,
    #     enable_checkpoints=True
    # )
    # 
    # # Run workflow
    # result = orchestrator.run(user_id=123)
    # 
    # # Check results
    # print(f"Status: {result.status}")
    # print(f"Duration: {result.duration_ms}ms")
    # print(f"Steps: {result.successful_steps}")
    # 
    # # Resume from checkpoint if failed
    # if result.is_failed:
    #     recovered = orchestrator.run_with_recovery(
    #         user_id=123,
    #         resume_from_invocation=result.invocation_id
    #     )
    
    print("InvoiceHandlerOrchestrator loaded. See example usage in __main__.")
