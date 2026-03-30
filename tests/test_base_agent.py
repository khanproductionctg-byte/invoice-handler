"""
Test for the base agent and example agent.
"""
import pytest
from unittest.mock import Mock, MagicMock
from agents.base_agent import BaseAgent, AgentState, ExampleAgent

# Mock LLM and tools for testing
class MockLLM:
    def bind(self, tools, tool_choice=None):
        return self
    def invoke(self, prompt, **kwargs):
        # Return a mock response that has a content attribute
        mock_response = Mock()
        mock_response.content = "This is a mock response"
        # Add tool_calls attribute for testing
        mock_response.tool_calls = []
        return mock_response

class MockTool:
    def __init__(self, name, description):
        self.name = name
        self.description = description
    def invoke(self, tool_input):
        return f"Result from {self.name}"

def test_base_agent_initialization():
    """Test that the base agent initializes correctly."""
    llm = MockLLM()
    tools = [MockTool("tool1", "First tool"), MockTool("tool2", "Second tool")]
    agent = ExampleAgent(llm, tools)
    # Override the agent name for testing
    agent.agent_name = "TestAgent"
    
    assert agent.agent_name == "TestAgent"
    assert len(agent.tools) == 2
    assert agent.max_retries == 3

def test_base_agent_invoke_llm_with_tools():
    """Test the _invoke_llm_with_tools method."""
    llm = MockLLM()
    tools = [MockTool("tool1", "First tool")]
    agent = ExampleAgent(llm, tools)
    
    prompt = "Test prompt"
    response = agent._invoke_llm_with_tools(prompt)
    
    assert response.content == "This is a mock response"

def test_base_agent_execute_tool():
    """Test the _execute_tool method."""
    llm = MockLLM()
    tools = [MockTool("tool1", "First tool")]
    agent = ExampleAgent(llm, tools)
    
    result = agent._execute_tool("tool1", {"param": "value"})
    assert result == "Result from tool1"
    
    # Test that it raises an error for unknown tool
    with pytest.raises(ValueError):
        agent._execute_tool("unknown_tool", {})

def test_example_agent_process():
    """Test the ExampleAgent's process method."""
    llm = MockLLM()
    tools = [MockTool("example_tool", "An example tool")]
    agent = ExampleAgent(llm, tools)
    
    state = AgentState(input_data={"test": "data"})
    result_state = agent.process(state)
    
    assert result_state.output_data.get("status") == "completed"
    assert "analysis" in result_state.output_data

def test_execute_tool_emits_record_on_success(monkeypatch):
    """Test that ToolCallRecord is emitted on successful tool execution."""
    captured_record = []

    def mock_emit(record):
        captured_record.append(record)

    monkeypatch.setattr("agents.base_agent.emit_tool_record", mock_emit)

    llm = MockLLM()
    tools = [MockTool("test_tool", "A test tool")]
    agent = ExampleAgent(llm, tools)
    agent.agent_name = "TestAgent"

    agent._execute_tool(
        "test_tool",
        {"param": "value"},
        tenant_id="tenant_123",
        workflow_run_id="run_456"
    )

    assert len(captured_record) == 1
    record = captured_record[0]
    assert record.exit_reason == "success"
    assert record.tool_name == "test_tool"
    assert record.agent_name == "TestAgent"
    assert record.tenant_id == "tenant_123"
    assert record.workflow_run_id == "run_456"


def test_execute_tool_emits_record_on_error(monkeypatch):
    """Test that ToolCallRecord is emitted with error exit_reason on exception."""
    captured_record = []

    def mock_emit(record):
        captured_record.append(record)

    monkeypatch.setattr("agents.base_agent.emit_tool_record", mock_emit)

    class FailingTool:
        name = "failing_tool"
        description = "A tool that fails"
        def invoke(self, tool_input):
            raise RuntimeError("Tool execution failed")

    llm = MockLLM()
    agent = ExampleAgent(llm, [FailingTool()])
    agent.agent_name = "TestAgent"

    with pytest.raises(RuntimeError):
        agent._execute_tool(
            "failing_tool",
            {},
            tenant_id="tenant_789",
            workflow_run_id="run_999"
        )

    assert len(captured_record) == 1
    record = captured_record[0]
    assert record.exit_reason == "error"
    assert record.error_detail == "Tool execution failed"


def test_execute_tool_emits_record_on_rate_limit(monkeypatch):
    """Test that ToolCallRecord is emitted with rate_limit exit_reason."""
    captured_record = []

    def mock_emit(record):
        captured_record.append(record)

    monkeypatch.setattr("agents.base_agent.emit_tool_record", mock_emit)

    class RateLimitedTool:
        name = "rate_limited_tool"
        description = "A tool with rate limit"
        def invoke(self, tool_input):
            raise Exception("Rate limit exceeded")

    llm = MockLLM()
    agent = ExampleAgent(llm, [RateLimitedTool()])
    agent.agent_name = "TestAgent"

    with pytest.raises(Exception):
        agent._execute_tool(
            "rate_limited_tool",
            {},
            tenant_id="tenant_111",
            workflow_run_id="run_222"
        )

    assert len(captured_record) == 1
    record = captured_record[0]
    assert record.exit_reason == "rate_limit"


if __name__ == "__main__":
    pytest.main([__file__])