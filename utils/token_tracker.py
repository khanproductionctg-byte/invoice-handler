"""
Token usage tracking for LLM calls in agent workflows.
Provides atomic DB updates and budget alerts.
"""
import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

COST_PER_TOKEN: Dict[str, Dict[str, Decimal]] = {
    "gpt-4o": {
        "input": Decimal("0.0025"),
        "output": Decimal("0.0100"),
    },
    "gpt-4o-mini": {
        "input": Decimal("0.00015"),
        "output": Decimal("0.0006"),
    },
    "gpt-4-turbo": {
        "input": Decimal("0.0100"),
        "output": Decimal("0.0300"),
    },
    "gpt-3.5-turbo": {
        "input": Decimal("0.0005"),
        "output": Decimal("0.0015"),
    },
    "claude-3-opus": {
        "input": Decimal("0.0150"),
        "output": Decimal("0.0750"),
    },
    "claude-3-sonnet": {
        "input": Decimal("0.0030"),
        "output": Decimal("0.0150"),
    },
    "claude-3-haiku": {
        "input": Decimal("0.00025"),
        "output": Decimal("0.00125"),
    },
    "default": {
        "input": Decimal("0.0010"),
        "output": Decimal("0.0050"),
    },
}

WORKFLOW_TOKEN_COST: Optional[Any] = None


def _get_workflow_token_cost_counter() -> Optional[Any]:
    """Lazy-load Prometheus counter for workflow token cost."""
    global WORKFLOW_TOKEN_COST
    if WORKFLOW_TOKEN_COST is not None:
        return WORKFLOW_TOKEN_COST
    
    try:
        from prometheus_client import Counter
        WORKFLOW_TOKEN_COST = Counter(
            'workflow_token_cost_usd_total',
            'Total workflow token cost in USD',
            ['tenant_id', 'model']
        )
    except ImportError:
        logger.warning("prometheus_client not installed - token cost metrics disabled")
    
    return WORKFLOW_TOKEN_COST


def _get_model_pricing(model_name: str) -> Dict[str, Decimal]:
    """Get pricing for a specific model."""
    normalized = model_name.lower().strip()
    for key, pricing in COST_PER_TOKEN.items():
        if key in normalized or normalized in key:
            return pricing
    return COST_PER_TOKEN["default"]


def _track_token_usage(
    response: Any,
    state: "agents.base_agent.AgentState",
    model_name: Optional[str] = None,
) -> None:
    """
    Extract token usage from LLM response, calculate cost, and update WorkflowRun atomically.
    
    Args:
        response: The LLM response object (must have usage metadata)
        state: The current agent state containing tenant_id and workflow_id
        model_name: The LLM model name for pricing lookup
    
    Raises:
        ValueError: If workflow_id is missing from state
    """
    if state.workflow_id is None:
        logger.warning("No workflow_id in state, skipping token tracking")
        return
    
    if state.tenant_id is None:
        logger.warning("No tenant_id in state, skipping token tracking")
        return
    
    input_tokens = 0
    output_tokens = 0
    
    if hasattr(response, 'usage') and response.usage is not None:
        usage = response.usage
        if hasattr(usage, 'input_tokens'):
            input_tokens = getattr(usage, 'input_tokens', 0) or 0
        elif hasattr(usage, 'tokens'):
            input_tokens = getattr(usage, 'tokens', {}).get('input', 0) or 0
            output_tokens = getattr(usage, 'tokens', {}).get('output', 0) or 0
        
        if hasattr(usage, 'output_tokens'):
            output_tokens = getattr(usage, 'output_tokens', 0) or 0
        elif hasattr(usage, 'completion_tokens'):
            output_tokens = getattr(usage, 'completion_tokens', 0) or 0
    
    if input_tokens == 0 and output_tokens == 0:
        return
    
    model = model_name or "default"
    pricing = _get_model_pricing(model)
    input_cost = pricing["input"] * Decimal(str(input_tokens)) / Decimal("1000")
    output_cost = pricing["output"] * Decimal(str(output_tokens)) / Decimal("1000")
    total_cost = input_cost + output_cost
    
    _update_workflow_tokens_atomically(
        workflow_id=state.workflow_id,
        tenant_id=state.tenant_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=total_cost,
    )
    
    _check_budget_and_alert(
        workflow_id=state.workflow_id,
        tenant_id=state.tenant_id,
    )


def _update_workflow_tokens_atomically(
    workflow_id: str,
    tenant_id: int,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
) -> None:
    """
    Atomically update WorkflowRun token totals using SQL UPDATE.
    Uses atomic increment to prevent race conditions.
    """
    from db.database import SessionLocal
    from db.models import WorkflowRun
    
    db = SessionLocal()
    try:
        db.execute(
            text("""
                UPDATE workflow_runs 
                SET tokens_input = tokens_input + :input_tokens,
                    tokens_output = tokens_output + :output_tokens,
                    estimated_cost_usd = estimated_cost_usd + :cost_usd
                WHERE invocation_id = :workflow_id
                  AND tenant_id = :tenant_id
            """),
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": float(cost_usd),
                "workflow_id": workflow_id,
                "tenant_id": tenant_id,
            }
        )
        db.commit()
        
        counter = _get_workflow_token_cost_counter()
        if counter:
            counter.labels(tenant_id=str(tenant_id), model="default").inc(float(cost_usd))
        
        logger.debug(
            f"Token usage updated: workflow={workflow_id}, "
            f"input={input_tokens}, output={output_tokens}, cost=${cost_usd}"
        )
    except Exception as e:
        logger.error(f"Failed to update token usage: {e}")
        db.rollback()
    finally:
        db.close()


def _check_budget_and_alert(
    workflow_id: str,
    tenant_id: int,
) -> None:
    """
    Check if workflow has exceeded budget and set error state if so.
    Fires 80% warning alert if threshold reached.
    """
    from db.database import SessionLocal
    from db.models import WorkflowRun
    
    db = SessionLocal()
    try:
        wf_run = db.query(WorkflowRun).filter(
            WorkflowRun.invocation_id == workflow_id,
            WorkflowRun.tenant_id == tenant_id,
        ).first()
        
        if not wf_run or wf_run.budget_limit_usd is None:
            return
        
        current_cost = Decimal(str(wf_run.estimated_cost_usd or 0))
        budget_limit = Decimal(str(wf_run.budget_limit_usd))
        
        if current_cost >= budget_limit:
            wf_run.status = "failed"
            wf_run.error_message = "budget_exceeded"
            db.commit()
            logger.warning(f"Budget exceeded for workflow {workflow_id}")
        
        elif current_cost >= budget_limit * Decimal("0.8"):
            _fire_budget_warning(tenant_id, current_cost, budget_limit)
    
    except Exception as e:
        logger.error(f"Failed to check budget: {e}")
    finally:
        db.close()


def _fire_budget_warning(
    tenant_id: int,
    current_cost: Decimal,
    budget_limit: Decimal,
) -> None:
    """Fire an 80% budget warning alert."""
    try:
        from utils.alert_system import send_alert
        
        send_alert({
            "type": "token_budget_warning",
            "title": f"Token Budget Warning: 80% Threshold Reached",
            "message": f"Workflow has consumed ${current_cost:.4f} of ${budget_limit:.4f} budget (80% threshold)",
            "severity": "medium",
            "data": {
                "tenant_id": tenant_id,
                "current_cost_usd": float(current_cost),
                "budget_limit_usd": float(budget_limit),
                "percent_used": float(current_cost / budget_limit * 100),
            }
        })
    except Exception as e:
        logger.error(f"Failed to send budget warning: {e}")
