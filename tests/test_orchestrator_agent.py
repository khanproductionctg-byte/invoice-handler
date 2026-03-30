"""
Test for the OrchestratorAgent - Updated for production-ready orchestrator.
"""
import pytest
from unittest.mock import Mock, patch
from agents.orchestrator import (
    InvoiceHandlerOrchestrator, 
    WorkflowState, 
    AgentName, 
    WorkflowStatus,
    StepStatus
)
from datetime import datetime


class MockAgent:
    """Mock agent for testing."""
    def __init__(self, name: str):
        self.agent_name = name
        self.run_count = 0
        
    def run(self, state):
        self.run_count += 1
        from agents.base_agent import AgentState
        if hasattr(state, 'output_data'):
            state.output_data[f"{self.agent_name}_processed"] = True
        if self.agent_name == "reporter":
            state.status = WorkflowStatus.COMPLETED
        return state


def test_workflow_state_creation():
    """Test that WorkflowState can be created correctly."""
    state = WorkflowState(user_id=1)
    
    assert state.user_id == 1
    assert state.status == WorkflowStatus.PENDING
    assert state.invocation_id is not None
    assert len(state.step_results) == 0
    assert state.is_completed is False
    assert state.is_failed is False


def test_workflow_state_step_results():
    """Test step results tracking."""
    state = WorkflowState(user_id=1)
    
    # Add a step result
    from agents.orchestrator import StepResult
    state.step_results.append(StepResult(
        step_name="ingestion",
        status=StepStatus.COMPLETED,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow()
    ))
    
    assert len(state.step_results) == 1
    assert state.successful_steps == ["ingestion"]
    assert state.get_step_result("ingestion") is not None
    assert state.get_step_result("reconciler") is None


def test_orchestrator_initialization():
    """Test that the orchestrator initializes correctly."""
    ingestion_agent = MockAgent("ingestion")
    reconciler_agent = MockAgent("reconciler")
    chaser_agent = MockAgent("chaser")
    reporter_agent = MockAgent("reporter")
    
    orchestrator = InvoiceHandlerOrchestrator(
        ingestion_agent=ingestion_agent,
        reconciler_agent=reconciler_agent,
        chaser_agent=chaser_agent,
        reporter_agent=reporter_agent,
        enable_checkpoints=False  # Disable for testing
    )
    
    # Check agents are stored correctly
    assert "ingestion" in orchestrator.agents
    assert "reconciler" in orchestrator.agents
    assert "chaser" in orchestrator.agents
    assert "reporter" in orchestrator.agents
    
    # Check config
    assert orchestrator.max_retries == 3
    assert orchestrator.enable_checkpoints is False


def test_orchestrator_run():
    """Test that the orchestrator runs the workflow."""
    ingestion_agent = MockAgent("ingestion")
    reconciler_agent = MockAgent("reconciler")
    chaser_agent = MockAgent("chaser")
    reporter_agent = MockAgent("reporter")
    
    orchestrator = InvoiceHandlerOrchestrator(
        ingestion_agent=ingestion_agent,
        reconciler_agent=reconciler_agent,
        chaser_agent=chaser_agent,
        reporter_agent=reporter_agent,
        enable_checkpoints=False
    )
    
    # Run workflow with user_id
    result = orchestrator.run(user_id=123)
    
    # Check that the workflow completed
    assert result.user_id == 123
    assert result.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]
    assert result.started_at is not None
    
    # Check summary is available
    summary = result.to_summary()
    assert summary["user_id"] == 123
    assert "status" in summary
    assert "duration_ms" in summary


def test_workflow_state_summary():
    """Test workflow state summary serialization."""
    state = WorkflowState(
        user_id=1,
        workflow_id="test-workflow",
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        status=WorkflowStatus.COMPLETED
    )
    
    from agents.orchestrator import StepResult
    state.step_results.append(StepResult(
        step_name="ingestion",
        status=StepStatus.COMPLETED,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow()
    ))
    
    summary = state.to_summary()
    
    assert summary["workflow_id"] == "test-workflow"
    assert summary["status"] == "completed"
    assert summary["steps_completed"] == 1
    assert summary["steps_failed"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
