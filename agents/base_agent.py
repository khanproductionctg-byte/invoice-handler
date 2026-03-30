"""
Base Agent class for the Invoice Handler system.
All specialized agents (ReconcilerAgent, ChaserAgent, ReporterAgent) inherit from this.
Provides common functionality for LLM tool calling, logging, and error handling.
"""
import logging
import time
import traceback
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional, Union
from utils.tool_call_record import ToolCallRecord, emit_tool_record, _hash_content
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseLLM
from langchain_core.tools import BaseTool
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field
import uuid
from datetime import datetime, time as dt_time
import os

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Lightweight in-memory circuit breaker for LLM calls."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "closed"  # closed, open, half-open

    def call(self, func, *args, **kwargs):
        if self.state == "open":
            if self.last_failure_time:
                elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout:
                    self.state = "half-open"
                    logger.info("Circuit breaker entering half-open state")
                else:
                    raise RuntimeError("Circuit breaker is OPEN. LLM provider unavailable.")
        try:
            result = func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.failures = 0
                logger.info("Circuit breaker closed after successful call")
            return result
        except Exception as e:
            self.failures += 1
            self.last_failure_time = datetime.utcnow()
            if self.failures >= self.failure_threshold:
                self.state = "open"
                logger.warning(f"Circuit breaker OPENED after {self.failures} failures")
            raise


_llm_breaker = CircuitBreaker(
    failure_threshold=int(os.getenv("LLM_CIRCUIT_BREAKER_THRESHOLD", 5)),
    recovery_timeout=int(os.getenv("LLM_CIRCUIT_BREAKER_TIMEOUT", 60)),
)


class AgentState(BaseModel):
    """State shared between agent nodes in LangGraph."""
    agent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    invocation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    retry_count: int = Field(default=0)
    max_retries: int = Field(default=3)
    tenant_id: Optional[int] = None
    steps_taken: int = Field(default=0)
    max_steps: int = Field(default=100)
    workflow_id: Optional[str] = None


class BaseAgent(ABC):
    """
    Base agent class providing common functionality for all agents in the system.
    Includes LLM tool calling, error handling, logging, and state management.
    """

    def __init__(
        self,
        llm: BaseLLM,
        tools: List[BaseTool],
        agent_name: str,
        max_retries: int = 3,
    ):
        """
        Initialize the base agent.

        Args:
            llm: Language model instance for tool calling
            tools: List of tools available to this agent
            agent_name: Human-readable name for the agent
            max_retries: Maximum number of retry attempts for failed operations
        """
        self.llm = llm
        self.tools = {tool.name: tool for tool in tools}
        self.agent_name = agent_name
        self.max_retries = max_retries
        logger.info(f"Initialized {self.agent_name} with {len(self.tools)} tools")

    def _invoke_llm_with_tools(
        self,
        prompt: str,
        tool_choice: Optional[str] = None,
        state: Optional["AgentState"] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Invoke the LLM with available tools and handle tool calling.

        Args:
            prompt: The prompt to send to the LLM
            tool_choice: Optional specific tool to force the LLM to use
            state: Optional AgentState for token tracking
            **kwargs: Additional arguments to pass to the LLM

        Returns:
            The LLM's response (either text or tool invocation)

        Raises:
            Exception: If LLM invocation fails after retries
        """
        # Prepare tools in the format expected by LangChain
        tools_format = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.args_schema.model_json_schema()
                    if hasattr(tool, "args_schema")
                    else {"type": "object", "properties": {}},
                },
            }
            for tool in self.tools.values()
        ]

        # Bind tools to LLM
        llm_with_tools = self.llm.bind(tools=tools_format, tool_choice=tool_choice)

        # Invoke through circuit breaker
        def _llm_call():
            return llm_with_tools.invoke(prompt, **kwargs)

        last_exception = None
        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    f"{self.agent_name} invoking LLM (attempt {attempt + 1}/{self.max_retries})"
                )
                response = _llm_breaker.call(_llm_call)
                
                # === INSERT TOKEN TRACKING HERE (after every LLM call) ===
                if state is not None:
                    model_name = getattr(self.llm, 'model_name', None) or getattr(self.llm, 'model', None)
                    try:
                        from utils.token_tracker import _track_token_usage as track_tokens
                        track_tokens(response, state, model_name)
                    except Exception as track_err:
                        logger.warning(f"Token tracking failed: {track_err}")
                # ==========================================================
                
                return response
            except RuntimeError:
                raise
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"{self.agent_name} LLM invocation failed (attempt {attempt + 1}): {str(e)}"
                )
                if attempt == self.max_retries - 1:
                    logger.error(
                        f"{self.agent_name} LLM invocation failed after {self.max_retries} attempts"
                    )
                    raise
                import time
                time.sleep(2 ** attempt)

        raise last_exception

    def _execute_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tenant_id: str = "unknown",
        workflow_run_id: str = "unknown",
    ) -> Any:
        """
        Execute a specific tool with given input.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool
            tenant_id: Tenant identifier for logging
            workflow_run_id: Workflow run identifier for logging

        Returns:
            Tool execution result

        Raises:
            ValueError: If tool is not found
            Exception: If tool execution fails
        """
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not found in agent {self.agent_name}")

        tool = self.tools[tool_name]
        start = time.monotonic()
        tokens_in = 0
        tokens_out = 0
        exit_reason: Literal["success", "error", "timeout", "rate_limit"] = "success"
        error_detail: Optional[str] = None

        try:
            logger.debug(f"{self.agent_name} executing tool '{tool_name}'")
            result = tool.invoke(tool_input)
            logger.debug(f"{self.agent_name} tool '{tool_name}' executed successfully")
            return result
        except Exception as e:
            error_detail = str(e)
            if "rate_limit" in error_detail.lower() or "rate limit" in error_detail.lower():
                exit_reason = "rate_limit"
            elif "timeout" in error_detail.lower():
                exit_reason = "timeout"
            else:
                exit_reason = "error"
            logger.error(
                f"{self.agent_name} tool '{tool_name}' execution failed: {error_detail}"
            )
            raise
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            record = ToolCallRecord(
                timestamp=datetime.utcnow(),
                tenant_id=tenant_id,
                workflow_run_id=workflow_run_id,
                agent_name=self.agent_name,
                tool_name=tool_name,
                input_hash=_hash_content(tool_input),
                output_hash="",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                exit_reason=exit_reason,
                error_detail=error_detail,
            )
            emit_tool_record(record)

    def _process_llm_response(self, response: Any) -> Union[str, Dict[str, Any]]:
        """
        Process the LLM response, handling both text and tool calls.

        Args:
            response: Raw response from LLM

        Returns:
            Processed response (text or structured tool call result)
        """
        # If response is a string, return it directly
        if isinstance(response, str):
            return response

        # If response contains tool calls, execute them
        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_results = []
            for tool_call in response.tool_calls:
                try:
                    result = self._execute_tool(
                        tool_call["name"], tool_call["args"]
                    )
                    tool_results.append(
                        {
                            "tool": tool_call["name"],
                            "result": result,
                            "status": "success",
                        }
                    )
                except Exception as e:
                    tool_results.append(
                        {
                            "tool": tool_call["name"],
                            "error": str(e),
                            "status": "error",
                        }
                    )
            return {
                "tool_calls": tool_results,
                "text": getattr(response, "content", ""),
            }

        # Return content if available
        if hasattr(response, "content"):
            return response.content

        # Fallback to string representation
        return str(response)

    @abstractmethod
    def process(self, state: AgentState) -> AgentState:
        """
        Main processing method for the agent.
        Must be implemented by subclasses.

        Args:
            state: Current agent state

        Returns:
            Updated agent state
        """
        pass

    def run(
        self, 
        state: AgentState, 
        timeout_seconds: int = 300
    ) -> AgentState:
        """
        Run the agent with error handling, state management, and step limiting.

        Args:
            state: Initial agent state
            timeout_seconds: Maximum execution time in seconds (default 300)

        Returns:
            Final agent state
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        from langgraph.graph import END
        
        state.agent_id = str(uuid.uuid4())
        state.timestamp = datetime.utcnow()
        logger.info(f"{self.agent_name} starting processing (ID: {state.agent_id})")

        def _execute_with_step_limit() -> AgentState:
            current_state = state
            
            while True:
                try:
                    current_state = self.process(current_state)
                    current_state.steps_taken += 1
                    
                    is_completed = current_state.output_data.get("status") == "completed"
                    has_error = current_state.error is not None
                    
                    if is_completed or has_error:
                        logger.info(
                            f"{self.agent_name} completed (ID: {current_state.agent_id}, "
                            f"steps: {current_state.steps_taken})"
                        )
                        return current_state
                    
                    if current_state.steps_taken >= current_state.max_steps:
                        current_state.error = "max_steps_exceeded"
                        current_state.output_data["status"] = "failed"
                        current_state.output_data["error"] = "max_steps_exceeded"
                        logger.critical(
                            f"MAX STEPS EXCEEDED: agent={self.agent_name}, "
                            f"tenant_id={current_state.tenant_id}, workflow_id={current_state.workflow_id}, "
                            f"steps_taken={current_state.steps_taken}, max_steps={current_state.max_steps}"
                        )
                        return current_state
                        
                except Exception as e:
                    logger.error(
                        f"{self.agent_name} failed: {str(e)}\n{traceback.format_exc()}"
                    )
                    current_state.error = str(e)
                    current_state.output_data["status"] = "failed"
                    current_state.output_data["error"] = str(e)
                    return current_state

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_execute_with_step_limit)
                try:
                    updated_state = future.result(timeout=timeout_seconds)
                    return updated_state
                except asyncio.TimeoutError:
                    logger.error(
                        f"AGENT TIMEOUT: agent={self.agent_name}, "
                        f"tenant_id={state.tenant_id}, workflow_id={state.workflow_id}, "
                        f"timeout_seconds={timeout_seconds}"
                    )
                    state.error = "timeout_exceeded"
                    state.output_data["status"] = "timed_out"
                    state.output_data["error"] = "timeout_exceeded"
                    
                    from db.database import SessionLocal
                    from db.models import WorkflowRun
                    db = SessionLocal()
                    try:
                        if state.workflow_id:
                            wf_run = db.query(WorkflowRun).filter(
                                WorkflowRun.invocation_id == state.workflow_id
                            ).first()
                            if wf_run:
                                wf_run.status = "timed_out"
                                wf_run.error_message = f"Agent timeout after {timeout_seconds}s"
                                db.commit()
                    except Exception as db_err:
                        logger.error(f"Failed to update WorkflowRun status: {db_err}")
                    finally:
                        db.close()
                    
                    return state
                except Exception as future_exc:
                    raise future_exc
        except Exception as e:
            logger.error(
                f"{self.agent_name} failed: {str(e)}\n{traceback.format_exc()}"
            )
            state.error = str(e)
            state.output_data["status"] = "failed"
            state.output_data["error"] = str(e)
            return state


# Example concrete agent implementation for demonstration
class ExampleAgent(BaseAgent):
    """Example agent showing how to implement a specific agent."""

    def __init__(self, llm: BaseLLM, tools: List[BaseTool]):
        super().__init__(llm, tools, "ExampleAgent")

    def process(self, state: AgentState) -> AgentState:
        """Example processing logic."""
        logger.info(f"ExampleAgent processing input: {state.input_data}")

        # Example: Use LLM to analyze input
        prompt = f"""
        Analyze the following invoice data and extract key information:
        {state.input_data}

        Provide a summary of the amount, date, and vendor.
        """

        try:
            # Invoke LLM with tools (if needed)
            response = self._invoke_llm_with_tools(prompt)
            processed = self._process_llm_response(response)

            state.output_data = {
                "analysis": processed,
                "processed_at": datetime.utcnow().isoformat(),
                "status": "completed"
            }
            return state
        except Exception as e:
            logger.error(f"ExampleAgent processing failed: {str(e)}")
            raise