"""
Payment chasing utilities for sending follow-up emails about overdue invoices.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any
from db.database import SessionLocal
from db.models import Invoice, Customer
from utils.email_sender import send_email
from utils.template_renderer import render_template

logger = logging.getLogger(__name__)


def chase_payments(tenant_id: int, user_id: int) -> str:
    """
    Send payment follow-up emails for overdue invoices.
    
    Args:
        tenant_id: The tenant ID for data isolation
        user_id: The user ID for context
    
    Returns:
        JSON string with chasing results
    """
    db = SessionLocal()
    results = {
        "total_overdue": 0,
        "emails_sent": 0,
        "skipped": 0,
        "errors": 0,
        "details": []
    }
    
    try:
        # Get all overdue invoices
        overdue_invoices = db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.status == 'overdue'
        ).all()
        
        results["total_overdue"] = len(overdue_invoices)
        
        for invoice in overdue_invoices:
            # Get customer info
            customer = None
            if invoice.customer_id:
                customer = db.query(Customer).filter(
                    Customer.id == invoice.customer_id
                ).first()
            
            if not customer or not customer.email:
                results["skipped"] += 1
                results["details"].append({
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "status": "skipped",
                    "reason": "No customer email found"
                })
                continue
            
            # Check if we should send (respect follow-up limits)
            if _should_send_followup(db, tenant_id, invoice):
                success = _send_payment_followup(
                    db, tenant_id, user_id, 
                    invoice, customer
                )
                
                if success:
                    results["emails_sent"] += 1
                    results["details"].append({
                        "invoice_id": invoice.id,
                        "invoice_number": invoice.invoice_number,
                        "customer_email": customer.email,
                        "status": "sent"
                    })
                    
                    # Record follow-up sent
                    _record_followup_sent(db, tenant_id, invoice.id)
                else:
                    results["errors"] += 1
                    results["details"].append({
                        "invoice_id": invoice.id,
                        "invoice_number": invoice.invoice_number,
                        "status": "error",
                        "reason": "Failed to send email"
                    })
            else:
                results["skipped"] += 1
                results["details"].append({
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "status": "skipped",
                    "reason": "Follow-up limit reached or sent too recently"
                })
        
        logger.info(f"Payment chasing completed for tenant {tenant_id}: {results['emails_sent']} emails sent")
        return json.dumps(results, default=str)
        
    except Exception as e:
        logger.error(f"Payment chasing failed for tenant {tenant_id}: {str(e)}")
        return json.dumps({"error": str(e)}, default=str)
    finally:
        db.close()


def _should_send_followup(db, tenant_id: int, invoice: Invoice) -> bool:
    """Check if we should send a follow-up email for this invoice."""
    from db.models import PaymentFollowup
    
    # Get the latest follow-up for this invoice
    latest_followup = db.query(PaymentFollowup).filter(
        PaymentFollowup.tenant_id == tenant_id,
        PaymentFollowup.invoice_id == invoice.id
    ).order_by(PaymentFollowup.sent_at.desc()).first()
    
    if not latest_followup:
        return True
    
    # Check if enough days have passed since last follow-up
    days_since_followup = (datetime.utcnow() - latest_followup.sent_at).days
    
    # Get tenant settings (default to 7 days between follow-ups)
    followup_interval_days = 7
    
    return days_since_followup >= followup_interval_days


def _send_payment_followup(
    db, 
    tenant_id: int, 
    user_id: int,
    invoice: Invoice, 
    customer: Customer
) -> bool:
    """Send a payment follow-up email for an overdue invoice."""
    try:
        # Calculate days overdue
        days_overdue = (datetime.utcnow().date() - invoice.due_date).days if invoice.due_date else 0
        
        # Prepare email data
        email_data = {
            "customer_name": customer.full_name or customer.email,
            "customer_email": customer.email,
            "invoice_number": invoice.invoice_number,
            "amount_due": float(invoice.amount_due),
            "amount_paid": float(invoice.amount_paid),
            "currency": invoice.currency,
            "due_date": invoice.due_date.strftime("%B %d, %Y") if invoice.due_date else "N/A",
            "days_overdue": days_overdue,
            "vendor_name": invoice.vendor_name,
            "invoice_description": invoice.description or ""
        }
        
        # Determine email template based on severity
        if days_overdue > 60:
            template_name = "payment_reminder_urgent"
            subject = f"URGENT: Invoice {invoice.invoice_number} is {days_overdue} days overdue"
        elif days_overdue > 30:
            template_name = "payment_reminder_final"
            subject = f"Final Notice: Invoice {invoice.invoice_number} is {days_overdue} days overdue"
        else:
            template_name = "payment_reminder_first"
            subject = f"Payment Reminder: Invoice {invoice.invoice_number} due {days_overdue} days ago"
        
        # Render email content
        try:
            html_content = render_template(f"{template_name}.html", email_data)
            text_content = render_template(f"{template_name}.txt", email_data)
        except Exception:
            # Fallback to simple email if template rendering fails
            html_content = None
            text_content = (
                f"Dear {email_data['customer_name']},\n\n"
                f"This is a reminder that invoice {email_data['invoice_number']} "
                f"for {email_data['currency']} {email_data['amount_due']:.2f} "
                f"was due on {email_data['due_date']} and is now {days_overdue} days overdue.\n\n"
                f"Please arrange payment at your earliest convenience.\n\n"
                f"Thank you."
            )
        
        # Send email
        send_email(
            to_email=customer.email,
            subject=subject,
            text_body=text_content,
            html_body=html_content
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to send payment follow-up for invoice {invoice.id}: {str(e)}")
        return False


def _record_followup_sent(db, tenant_id: int, invoice_id: int):
    """Record that a follow-up was sent."""
    from db.models import PaymentFollowup
    
    try:
        followup = PaymentFollowup(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            followup_type="email",
            sent_at=datetime.utcnow()
        )
        db.add(followup)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to record follow-up: {e}")
        db.rollback()
