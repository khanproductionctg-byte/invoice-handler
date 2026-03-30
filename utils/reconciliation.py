"""
Reconciliation utilities for matching invoices with payments.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from db.database import SessionLocal
from db.models import Invoice, Payment, ReconciliationHistory
from utils.currency_converter import convert_amount

logger = logging.getLogger(__name__)


def reconcile_invoices(tenant_id: int, user_id: int) -> str:
    """
    Reconcile invoices with payments using matching logic.
    
    Args:
        tenant_id: The tenant ID for data isolation
        user_id: The user ID for context
    
    Returns:
        JSON string with reconciliation results
    """
    db = SessionLocal()
    results = {
        "total_invoices": 0,
        "matched": 0,
        "partially_matched": 0,
        "unmatched": 0,
        "matches": []
    }
    
    try:
        # Get all pending/overdue invoices for this tenant
        invoices = db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(['pending', 'sent', 'overdue'])
        ).all()
        
        results["total_invoices"] = len(invoices)
        
        for invoice in invoices:
            # Look for matching payments
            match_result = _find_payment_match(db, tenant_id, invoice)
            
            if match_result["matched"]:
                if match_result["match_type"] == "full":
                    results["matched"] += 1
                else:
                    results["partially_matched"] += 1
                
                # Update invoice status
                invoice.status = "paid" if match_result["match_type"] == "full" else "partially_paid"
                invoice.amount_paid = match_result["paid_amount"]
                db.commit()
                
                # Record reconciliation history
                _record_reconciliation(
                    db, tenant_id, invoice.id, 
                    match_result.get("payment_id"),
                    match_result["match_type"],
                    match_result.get("confidence", 1.0)
                )
                
                results["matches"].append({
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "match_type": match_result["match_type"],
                    "confidence": match_result.get("confidence", 1.0),
                    "payment_id": match_result.get("payment_id")
                })
            else:
                results["unmatched"] += 1
                results["matches"].append({
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "match_type": "none",
                    "reason": match_result.get("reason", "No matching payment found")
                })
        
        logger.info(f"Reconciliation completed for tenant {tenant_id}: {results['matched']} matched, {results['unmatched']} unmatched")
        return json.dumps(results, default=str)
        
    except Exception as e:
        logger.error(f"Reconciliation failed for tenant {tenant_id}: {str(e)}")
        return json.dumps({"error": str(e)}, default=str)
    finally:
        db.close()


def _find_payment_match(db, tenant_id: int, invoice: Invoice) -> Dict[str, Any]:
    """Find a payment that matches the given invoice."""
    
    # Try exact match by invoice number
    payments = db.query(Payment).filter(
        Payment.tenant_id == tenant_id,
        Payment.invoice_id == None  # Not already assigned
    ).all()
    
    for payment in payments:
        confidence = _calculate_match_confidence(invoice, payment)
        
        if confidence >= 0.9:
            # Exact match
            payment.invoice_id = invoice.id
            db.commit()
            
            return {
                "matched": True,
                "match_type": "full",
                "payment_id": payment.id,
                "paid_amount": float(payment.amount),
                "confidence": confidence
            }
        elif confidence >= 0.5:
            # Partial match - needs review
            return {
                "matched": True,
                "match_type": "partial",
                "payment_id": payment.id,
                "paid_amount": float(payment.amount),
                "confidence": confidence
            }
    
    return {"matched": False, "reason": "No matching payment found"}


def _calculate_match_confidence(invoice: Invoice, payment: Payment) -> float:
    """Calculate confidence score for invoice-payment match."""
    score = 0.0
    
    # Convert payment to invoice currency if needed
    invoice_currency = getattr(invoice, 'currency', None) or 'USD'
    payment_currency = getattr(payment, 'currency', None) or 'USD'
    
    if invoice_currency != payment_currency:
        converted_amount = convert_amount(
            payment.amount,
            payment_currency,
            invoice_currency,
            payment.payment_date
        )
        if converted_amount is None:
            return 0.0  # Can't match different currencies without conversion
    else:
        converted_amount = payment.amount
    
    # Amount match (up to 40 points)
    amount_diff = abs(float(invoice.amount_due) - float(converted_amount))
    if amount_diff == 0:
        score += 0.4
    elif amount_diff / float(invoice.amount_due) < 0.01:  # Within 1%
        score += 0.3
    elif amount_diff / float(invoice.amount_due) < 0.05:  # Within 5%
        score += 0.2
    elif amount_diff / float(invoice.amount_due) < 0.1:  # Within 10%
        score += 0.1
    
    # Date proximity (up to 30 points)
    days_diff = abs((invoice.due_date - payment.payment_date).days) if invoice.due_date and payment.payment_date else 999
    if days_diff == 0:
        score += 0.3
    elif days_diff <= 3:
        score += 0.2
    elif days_diff <= 7:
        score += 0.1
    
    # Vendor name similarity (up to 30 points)
    if invoice.vendor_name and payment.vendor_name:
        if invoice.vendor_name.lower() == payment.vendor_name.lower():
            score += 0.3
        elif invoice.vendor_name.lower() in payment.vendor_name.lower() or payment.vendor_name.lower() in invoice.vendor_name.lower():
            score += 0.15
    
    return min(score, 1.0)


def _record_reconciliation(
    db, 
    tenant_id: int, 
    invoice_id: Optional[int],
    payment_id: Optional[int],
    outcome: str,
    confidence: float
):
    """Record reconciliation history for audit trail."""
    try:
        history = ReconciliationHistory(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            payment_id=payment_id,
            outcome=1 if outcome in ["full", "partial"] else 0,
            idempotency_key=f"{tenant_id}:{invoice_id}:{payment_id}:{datetime.utcnow().date().isoformat()}"
        )
        db.add(history)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to record reconciliation history: {e}")
        db.rollback()
