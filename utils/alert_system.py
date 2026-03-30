"""
Alert system utilities for checking alert conditions and sending alerts.
"""
import logging
from typing import Dict, List, Any, Optional
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session
from db.models import Invoice, Expense
from utils.email_sender import send_email
from utils.sms_sender import send_sms
import os
import json
import requests

logger = logging.getLogger(__name__)


def _send_pagerduty_alert(alert: Dict[str, Any]) -> bool:
    """Send alert to PagerDuty."""
    pd_key = os.getenv("PAGERDUTY_API_KEY")
    pd_service = os.getenv("PAGERDUTY_SERVICE_ID")
    
    if not pd_key or not pd_service:
        logger.debug("PagerDuty not configured")
        return False
    
    severity_map = {"high": "critical", "medium": "warning", "low": "info"}
    
    try:
        response = requests.post(
            "https://events.pagerduty.com/v2/enqueue",
            headers={"Content-Type": "application/json"},
            json={
                "routing_key": pd_service,
                "event_action": "trigger",
                "payload": {
                    "summary": alert["title"],
                    "severity": severity_map.get(alert.get("severity", "medium"), "warning"),
                    "source": "invoice-handler",
                    "custom_details": alert.get("data", {})
                },
                "dedup_key": f"invoice-handler-{alert['type']}-{datetime.utcnow().date()}"
            },
            timeout=10
        )
        return response.status_code in (200, 202, 202)
    except Exception as e:
        logger.error(f"Failed to send PagerDuty alert: {e}")
        return False


def _send_slack_alert(alert: Dict[str, Any]) -> bool:
    """Send alert to Slack."""
    slack_webhook = os.getenv("SLACK_WEBHOOK_URL")
    
    if not slack_webhook:
        logger.debug("Slack not configured")
        return False
    
    color_map = {"high": "#ff0000", "medium": "#ffa500", "low": "#00ff00"}
    
    try:
        payload = {
            "attachments": [{
                "color": color_map.get(alert.get("severity", "medium"), "#ffa500"),
                "title": alert["title"],
                "text": alert["message"],
                "fields": [
                    {"title": "Type", "value": alert["type"], "short": True},
                    {"title": "Severity", "value": alert.get("severity", "medium"), "short": True}
                ],
                "footer": "Invoice Handler",
                "ts": int(datetime.utcnow().timestamp())
            }]
        }
        response = requests.post(slack_webhook, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


def _send_opsgenie_alert(alert: Dict[str, Any]) -> bool:
    """Send alert to OpsGenie."""
    opsgenie_key = os.getenv("OPSGENIE_API_KEY")
    opsgenie_team = os.getenv("OPSGENIE_TEAM_NAME")
    
    if not opsgenie_key:
        logger.debug("OpsGenie not configured")
        return False
    
    priority_map = {"high": "P1", "medium": "P2", "low": "P3"}
    
    try:
        payload = {
            "message": alert["title"],
            "description": alert["message"],
            "priority": priority_map.get(alert.get("severity", "medium"), "P2"),
            "tags": [alert["type"], "invoice-handler"],
            "details": alert.get("data", {})
        }
        if opsgenie_team:
            payload["teams"] = [{"name": opsgenie_team}]
        
        response = requests.post(
            "https://api.opsgenie.com/v2/alerts",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"GenieKey {opsgenie_key}"
            },
            json=payload,
            timeout=10
        )
        return response.status_code in (200, 201, 202)
    except Exception as e:
        logger.error(f"Failed to send OpsGenie alert: {e}")
        return False


def check_alert_conditions(db: Session, tenant_id: int) -> List[Dict[str, Any]]:
    """
    Check for alert conditions such as overdue amounts, unusual expenses, etc.

    Args:
        db: Database session
        tenant_id: ID of the tenant

    Returns:
        List of alert dictionaries
    """
    alerts = []
    
    # Check for high overdue amount
    overdue_alert = _check_high_overdue(db, tenant_id)
    if overdue_alert:
        alerts.append(overdue_alert)
    
    # Check for unusual expense spikes
    expense_alert = _check_unusual_expenses(db, tenant_id)
    if expense_alert:
        alerts.append(expense_alert)
    
    # Check for duplicate invoices (already flagged by reconciler, but we can alert here too)
    duplicate_alert = _check_duplicate_invoices(db, tenant_id)
    if duplicate_alert:
        alerts.append(duplicate_alert)
    
    return alerts


def check_token_budget_alerts() -> List[Dict[str, Any]]:
    """
    Check all active WorkflowRuns for token budget warnings.
    Queries runs where estimated_cost_usd >= budget_limit_usd * 0.8.
    
    Returns:
        List of alert dictionaries for budget warnings
    """
    from db.database import SessionLocal
    from db.models import WorkflowRun
    from decimal import Decimal
    
    alerts = []
    db = SessionLocal()
    try:
        runs = db.query(WorkflowRun).filter(
            WorkflowRun.budget_limit_usd.isnot(None),
            WorkflowRun.status.in_(["running", "queued", "pending"]),
        ).all()
        
        for wf_run in runs:
            current_cost = Decimal(str(wf_run.estimated_cost_usd or 0))
            budget_limit = Decimal(str(wf_run.budget_limit_usd))
            percent_used = (current_cost / budget_limit * 100) if budget_limit > 0 else 0
            
            if current_cost >= budget_limit:
                alerts.append({
                    "type": "token_budget_exceeded",
                    "title": f"Token Budget Exceeded for Workflow {wf_run.invocation_id}",
                    "message": f"Workflow has exceeded token budget: ${current_cost:.4f} of ${budget_limit:.4f}",
                    "severity": "high",
                    "data": {
                        "workflow_id": wf_run.invocation_id,
                        "tenant_id": wf_run.tenant_id,
                        "current_cost_usd": float(current_cost),
                        "budget_limit_usd": float(budget_limit),
                        "percent_used": float(percent_used),
                        "status": wf_run.status,
                    }
                })
            elif current_cost >= budget_limit * Decimal("0.8"):
                alerts.append({
                    "type": "token_budget_warning",
                    "title": f"Token Budget Warning: {percent_used:.1f}% Used",
                    "message": f"Workflow has used {percent_used:.1f}% of token budget: ${current_cost:.4f} of ${budget_limit:.4f}",
                    "severity": "medium",
                    "data": {
                        "workflow_id": wf_run.invocation_id,
                        "tenant_id": wf_run.tenant_id,
                        "current_cost_usd": float(current_cost),
                        "budget_limit_usd": float(budget_limit),
                        "percent_used": float(percent_used),
                        "status": wf_run.status,
                    }
                })
        
        for alert in alerts:
            send_alert(alert)
            
    except Exception as e:
        logger.error(f"Failed to check token budget alerts: {e}")
    finally:
        db.close()
    
    return alerts


def _check_high_overdue(db: Session, tenant_id: int) -> Optional[Dict[str, Any]]:
    """
    Check if overdue amount exceeds a threshold.

    Returns:
        Alert dictionary or None
    """
    threshold = float(os.getenv("ALERT_THRESHOLD_OVERDUE", 1000))
    
    overdue_invoices = db.query(Invoice).filter(
        Invoice.tenant_id == tenant_id,
        Invoice.due_date < date.today(),
        Invoice.status == "overdue",
        Invoice.amount_paid < Invoice.amount_due
    ).all()
    
    total_overdue = sum(inv.amount_due - inv.amount_paid for inv in overdue_invoices)
    
    if total_overdue > threshold:
        return {
            "type": "high_overdue",
            "title": f"High Overdue Amount: ${total_overdue:.2f}",
            "message": f"Total overdue amount is ${total_overdue:.2f}, which exceeds the threshold of ${threshold:.2f}.",
            "severity": "high",
            "data": {
                "total_overdue": total_overdue,
                "threshold": threshold,
                "overdue_invoice_count": len(overdue_invoices),
                "overdue_invoices": [
                    {
                        "invoice_number": inv.invoice_number,
                        "vendor_name": inv.vendor_name,
                        "amount_overdue": float(inv.amount_due - inv.amount_paid),
                        "days_overdue": (date.today() - inv.due_date).days
                    }
                    for inv in overdue_invoices
                ]
            }
        }
    return None


def _check_unusual_expenses(db: Session, tenant_id: int) -> Optional[Dict[str, Any]]:
    """
    Check for unusual expense spikes compared to historical average.

    Returns:
        Alert dictionary or None
    """
    # Get expenses for the last 30 days
    thirty_days_ago = date.today() - timedelta(days=30)
    recent_expenses = db.query(Expense).filter(
        Expense.tenant_id == tenant_id,
        Expense.expense_date >= thirty_days_ago
    ).all()
    
    if not recent_expenses:
        return None
    
    # Calculate total recent expenses
    total_recent = sum(exp.amount for exp in recent_expenses)
    
    # Get expenses for the previous 30 days for comparison
    sixty_days_ago = date.today() - timedelta(days=60)
    previous_expenses = db.query(Expense).filter(
        Expense.tenant_id == tenant_id,
        Expense.expense_date >= sixty_days_ago,
        Expense.expense_date < thirty_days_ago
    ).all()
    
    total_previous = sum(exp.amount for exp in previous_expenses) if previous_expenses else 0
    
    # If we have previous data, check for spike
    if total_previous > 0:
        # Calculate percentage increase
        if total_previous > 0:
            increase_percent = ((total_recent - total_previous) / total_previous) * 100
        else:
            increase_percent = 0 if total_recent == 0 else float('inf')
        
        # Alert if increase is more than 50%
        if increase_percent > 50:
            return {
                "type": "expense_spike",
                "title": f"Expense Spike Detected: {increase_percent:.1f}% Increase",
                "message": f"Expenses in the last 30 days (${total_recent:.2f}) are {increase_percent:.1f}% higher than the previous 30 days (${total_previous:.2f}).",
                "severity": "medium",
                "data": {
                    "recent_total": total_recent,
                    "previous_total": total_previous,
                    "increase_percent": increase_percent,
                    "recent_expense_count": len(recent_expenses),
                    "previous_expense_count": len(previous_expenses)
                }
            }
    return None


def _check_duplicate_invoices(db: Session, tenant_id: int) -> Optional[Dict[str, Any]]:
    """
    Check for potential duplicate invoices.

    Returns:
        Alert dictionary or None
    """
    # Get all invoices for the tenant
    invoices = db.query(Invoice).filter(Invoice.tenant_id == tenant_id).all()
    
    # Simple duplicate check: same vendor, amount, and date (within 2 days)
    seen = {}
    duplicates = []
    
    for inv in invoices:
        # Create a key that allows for small date differences
        key = (inv.vendor_name, float(inv.amount_due), inv.invoice_date)
        if key in seen:
            duplicates.append((seen[key], inv.id))
        else:
            seen[key] = inv.id
    
    if duplicates:
        duplicate_details = []
        for orig_id, dup_id in duplicates:
            orig_inv = db.query(Invoice).get(orig_id)
            dup_inv = db.query(Invoice).get(dup_id)
            duplicate_details.append({
                "original_invoice": {
                    "id": orig_inv.id,
                    "number": orig_inv.invoice_number,
                    "date": orig_inv.invoice_date.isoformat() if orig_inv.invoice_date else None
                },
                "duplicate_invoice": {
                    "id": dup_inv.id,
                    "number": dup_inv.invoice_number,
                    "date": dup_inv.invoice_date.isoformat() if dup_inv.invoice_date else None
                }
            })
        
        return {
            "type": "duplicate_invoices",
            "title": f"Potential Duplicate Invoices Detected: {len(duplicates)} pairs",
            "message": f"Found {len(duplicates)} potential duplicate invoice pairs.",
            "severity": "medium",
            "data": {
                "duplicate_pairs": duplicate_details
            }
        }
    return None


def send_alert(alert: Dict[str, Any]) -> bool:
    """
    Send an alert via email, SMS, PagerDuty, Slack, and/or OpsGenie.

    Args:
        alert: Alert dictionary from check_alert_conditions

    Returns:
        True if alert was sent successfully, False otherwise
    """
    try:
        alert_email = os.getenv("ALERT_EMAIL")
        alert_phone = os.getenv("ALERT_PHONE")
        
        if not alert_email and not alert_phone and not os.getenv("PAGERDUTY_API_KEY") and not os.getenv("SLACK_WEBHOOK_URL") and not os.getenv("OPSGENIE_API_KEY"):
            logger.warning("No alert destinations configured")
            return False
        
        subject = f"[Invoice Handler Alert] {alert['title']}"
        body = f"""
        Alert Type: {alert['type']}
        Severity: {alert['severity']}
        
        {alert['message']}
        
        Details:
        {json.dumps(alert['data'], indent=2)}
        
        Timestamp: {datetime.utcnow().isoformat()}
        """
        
        success = True
        
        if alert_email:
            email_result = send_email(
                to_email=alert_email,
                subject=subject,
                body=body,
                is_html=False
            )
            if not email_result["success"]:
                logger.error(f"Failed to send alert email: {email_result.get('error')}")
                success = False
        
        if alert_phone and alert['severity'] == 'high':
            sms_message = f"ALERT: {alert['title']} - {alert['message'][:100]}"
            sms_result = send_sms(
                to_number=alert_phone,
                message=sms_message
            )
            if not sms_result["success"]:
                logger.error(f"Failed to send alert SMS: {sms_result.get('error')}")
                success = False
        
        _send_pagerduty_alert(alert)
        _send_slack_alert(alert)
        _send_opsgenie_alert(alert)
        
        return success
        
    except Exception as e:
        logger.error(f"Failed to send alert: {str(e)}")
        return False