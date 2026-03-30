"""
Template rendering utilities for email and SMS reminders.
"""
import logging
from typing import Dict, Any
from jinja2 import Environment, FileSystemLoader, select_autoescape
import os
from datetime import date, datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

# Set up Jinja2 environment
template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
env = Environment(
    loader=FileSystemLoader(template_dir),
    autoescape=select_autoescape(['html', 'xml'])
)


def render_reminder_template(
    invoice: Any, 
    reminder_type: str, 
    template_type: str = "email"
) -> str:
    """
    Render a reminder template for an invoice.

    Args:
        invoice: Invoice object or dictionary
        reminder_type: Type of reminder (gentle, firm, legal)
        template_type: Type of template (email, sms)

    Returns:
        Rendered template string
    """
    try:
        # Determine template file
        template_name = f"{reminder_type}_{template_type}.j2"
        
        # Try to load the template
        try:
            template = env.get_template(template_name)
        except Exception:
            # Fall back to default template
            template_name = f"default_{template_type}.j2"
            template = env.get_template(template_name)
        
        # Prepare template data
        template_data = {
            "invoice": invoice,
            "reminder_type": reminder_type,
            "today": date.today(),
            "days_overdue": (date.today() - invoice.due_date).days if hasattr(invoice, 'due_date') and invoice.due_date else 0,
            "amount_due": float(invoice.amount_due) if hasattr(invoice, 'amount_due') else 0,
            "invoice_number": getattr(invoice, 'invoice_number', 'N/A'),
            "vendor_name": getattr(invoice, 'vendor_name', 'N/A'),
            "due_date": getattr(invoice, 'due_date', None),
        }
        
        # Render template
        rendered = template.render(**template_data)
        logger.debug(f"Rendered {template_name} for invoice {getattr(invoice, 'invoice_number', 'unknown')}")
        
        return rendered
        
    except Exception as e:
        logger.error(f"Failed to render template: {str(e)}")
        # Fallback to simple text template
        return f"""
        Reminder: Invoice {getattr(invoice, 'invoice_number', 'N/A')} from {getattr(invoice, 'vendor_name', 'N/A')}
        Amount due: ${getattr(invoice, 'amount_due', 0):.2f}
        Due date: {getattr(invoice, 'due_date', 'N/A')}
        This is a {reminder_type} reminder regarding your payment.
        """


def render_report_template(report_data: Dict[str, Any], template_type: str = "email") -> str:
    """
    Render a report template.

    Args:
        report_data: Report data dictionary
        template_type: Type of template (email, sms)

    Returns:
        Rendered template string
    """
    try:
        template_name = f"report_{template_type}.j2"
        
        try:
            template = env.get_template(template_name)
        except Exception:
            # Fall back to default
            template_name = f"default_{template_type}.j2"
            template = env.get_template(template_name)
        
        template_data = {
            "report": report_data,
            "generated_at": datetime.utcnow(),
        }
        
        return template.render(**template_data)
        
    except Exception as e:
        logger.error(f"Failed to render report template: {str(e)}")
        # Simple fallback
        return f"Financial Report Generated at {datetime.utcnow()}\n\n{str(report_data)}"