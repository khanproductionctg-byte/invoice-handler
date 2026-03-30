"""
Unit tests for max_steps limit in BaseAgent.
Verifies that agent loop stops at max_steps to prevent infinite loops.
"""
import pytest
import os
from unittest.mock import MagicMock, patch

os.environ["ENVIRONMENT"] = "test"

from agents.base_agent import BaseAgent, AgentState
from langchain_core.tools import BaseTool


class MockTool(BaseTool):
    name: str = "mock_tool"
    description: str = "A mock tool for testing"
    
    def _run(self, input_data: str) -> str:
        return f"processed: {input_data}"


class InfiniteLoopAgent(BaseAgent):
    """Agent that would loop forever without max_steps limit."""
    
    def __init__(self, llm=None, tools=None):
        super().__init__(llm=llm, tools=tools or [], agent_name="InfiniteLoopAgent")
        self.call_count = 0
    
    def process(self, state: AgentState) -> AgentState:
        self.call_count += 1
        state.output_data["call_count"] = self.call_count
        state.input_data["loop_trigger"] = True
        return state


class TestMaxStepsLimit:
    """Test suite for max_steps enforcement."""
    
    def test_agent_stops_at_max_steps(self):
        """Test that agent stops exactly at max_steps."""
        agent = InfiniteLoopAgent(tools=[])
        
        state = AgentState(
            max_steps=5,
            steps_taken=0,
            tenant_id=1,
            workflow_id="test-workflow-123"
        )
        
        result = agent.run(state)
        
        assert result.steps_taken == 5
        assert result.error == "max_steps_exceeded"
        assert result.output_data["status"] == "failed"
        assert result.output_data["call_count"] == 5
    
    def test_agent_completes_below_max_steps(self):
        """Test that agent completes normally when under limit."""
        class FiniteAgent(BaseAgent):
            def __init__(self):
                super().__init__(llm=None, tools=[], agent_name="FiniteAgent")
            
            def process(self, state: AgentState) -> AgentState:
                state.output_data["status"] = "completed"
                return state
        
        agent = FiniteAgent()
        
        state = AgentState(
            max_steps=100,
            steps_taken=0,
            tenant_id=1
        )
        
        result = agent.run(state)
        
        assert result.steps_taken == 1
        assert result.error is None
        assert result.output_data["status"] == "completed"
    
    def test_max_steps_default_is_100(self):
        """Test that default max_steps is 100."""
        state = AgentState()
        assert state.max_steps == 100
    
    def test_custom_max_steps_value(self):
        """Test that custom max_steps value is respected."""
        agent = InfiniteLoopAgent(tools=[])
        
        state = AgentState(
            max_steps=3,
            steps_taken=0,
            tenant_id=1,
            workflow_id="test-wf"
        )
        
        result = agent.run(state)
        
        assert result.steps_taken == 3
        assert result.error == "max_steps_exceeded"
    
    def test_step_counter_increments(self):
        """Test that step counter increments on each iteration."""
        class CountingAgent(BaseAgent):
            def __init__(self):
                super().__init__(llm=None, tools=[], agent_name="CountingAgent")
                self.iterations = 0
            
            def process(self, state: AgentState) -> AgentState:
                self.iterations += 1
                if self.iterations >= 3:
                    state.output_data["status"] = "completed"
                return state
        
        agent = CountingAgent()
        
        state = AgentState(
            max_steps=10,
            steps_taken=0,
            tenant_id=1
        )
        
        result = agent.run(state)
        
        assert agent.iterations == 3
        assert result.steps_taken == 3
    
    def test_critical_log_on_max_steps_exceeded(self):
        """Test that CRITICAL log is emitted when max_steps exceeded."""
        agent = InfiniteLoopAgent(tools=[])
        
        state = AgentState(
            max_steps=2,
            steps_taken=0,
            tenant_id=42,
            workflow_id="test-workflow-abc"
        )
        
        with patch('agents.base_agent.logger') as mock_logger:
            result = agent.run(state)
            
            assert result.error == "max_steps_exceeded"
            mock_logger.critical.assert_called_once()
            call_args = mock_logger.critical.call_args[0][0]
            assert "MAX STEPS EXCEEDED" in call_args
            assert "tenant_id=42" in call_args
            assert "workflow_id=test-workflow-abc" in call_args
            assert "max_steps=2" in call_args


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
