"""
ChaserAgent - Production-Ready Payment Reminder System
====================================================
Advanced reminder generation with:
- Natural, professional, personalized messages
- Sophisticated escalation logic (timing + tone)
- LLM-powered generation with comprehensive prompt
- Multi-channel delivery (email + SMS)
- Smart frequency management
"""
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional
from datetime import datetime, date, timedelta, timezone


def utc_now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)
from enum import Enum
import json

from langchain_core.tools import BaseTool
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field
from langchain_community.llms import Ollama

from .base_agent import BaseAgent, AgentState
from db.database import SessionLocal, get_tenant_session
from db.models import Invoice, Customer
from utils.email_sender import send_email
from utils.sms_sender import send_sms

logger = logging.getLogger(__name__)


# =============================================================================
# LLM PROMPT TEMPLATE FOR REMINDER GENERATION
# =============================================================================

REMINDER_GENERATION_PROMPT = """You are an expert accounts receivable specialist at a modern SaaS company. Your job is to craft personalized, effective payment reminder messages that get results while maintaining strong customer relationships.

## CONTEXT
You are writing to {customer_name} at {company_name} regarding an overdue invoice. This is reminder #{reminder_count} for this invoice, and it has been {days_overdue} days since the due date.

## TONE GUIDELINES
Your tone should be: {tone_description}

Remember: You're Collections Professional, not a robot. Write like a smart, empathetic human who wants to help customers succeed while ensuring the business gets paid.

## CUSTOMER RELATIONSHIP
- Previous payment history: {payment_history}
- Number of previous invoices: {total_invoices}
- Current reminder level: {reminder_type} ({reminder_description})

## INVOICE DETAILS
- Invoice Number: {invoice_number}
- Original Due Date: {due_date_formatted}
- Amount Due: {amount_formatted}
- Amount Already Paid: {paid_formatted}
- Outstanding Balance: {outstanding_formatted}

## WHAT MAKES THIS REMINDER UNIQUE
{personalization_context}

## STRUCTURAL REQUIREMENTS

For EMAIL (primary channel):
1. Subject Line: Specific, not generic. Examples:
   - "Quick note about Invoice {invoice_number} - {company_name}"
   - "Following up on your payment for Invoice {invoice_number}"
   - "Action needed: Invoice {invoice_number} past due"

2. Opening: Start with a positive or acknowledge the relationship. NOT "This is a reminder that..."

3. Body: 
   - State the facts clearly (invoice #, amount, what happened)
   - Show you understand (acknowledge if there might be a reason)
   - Make it easy to act (include clear next steps)
   - No blame or shame language

4. Closing: Clear but gentle call to action. Leave the door open for dialogue.

5. Signature: Professional but warm. "{sender_name}"

For SMS (secondary channel - use only if needed):
- Max 155 characters
- Include invoice # and amount
- Include a link or clear instruction
- Example: "Hi {customer_first_name}, just a quick note that Invoice {invoice_number} for {amount_short} is past due. Let's get this resolved - reply or pay here: [LINK]"

## FORBIDDEN
- Never use ALL CAPS (even for emphasis)
- Never use words like "default," "delinquent," "failure," "neglect"
- Never threaten legal action explicitly (leave that to the final notice)
- Never assume bad faith - give customers the benefit of the doubt
- Never be robotic or templatey - every message should feel considered

## OUTPUT FORMAT
Return a JSON object with exactly these fields:
{{
  "email_subject": "your crafted subject line",
  "email_body": "your crafted email body (plain text, 2-4 paragraphs)",
  "sms_body": "your crafted SMS (max 155 chars)",
  "tone_notes": "brief notes on why you chose this approach",
  "personalization_wins": "what made this message personalized"
}}

Generate your response now:"""


# =============================================================================
# ESCALATION CONFIGURATION
# =============================================================================

class ReminderType(str, Enum):
    """Reminder escalation types."""
    FIRST = "first"           # Day 1-3: Friendly nudge
    SECOND = "second"         # Day 4-7: More direct
    URGENT = "urgent"        # Day 8-14: Firm but fair
    FINAL = "final"          # Day 15-30: Last chance
    LEGAL = "legal"          # Day 30+: Pre-collection


# Detailed escalation configuration
ESCALATION_CONFIG = {
    ReminderType.FIRST: {
        "days_overdue_min": 1,
        "days_overdue_max": 3,
        "tone_description": "friendly, warm, like a helpful colleague reminding you of something you might have missed. Use 'I' and 'we' more than 'you must'.",
        "reminder_description": "A friendly first nudge - assume good faith, keep it light",
        "email_style": "warm_professional",
        "sms_appropriate": False,
        "example_subject": "Quick note about Invoice {inv}",
        "relationship_focus": "maintain",
        "urgency_level": 1,
    },
    ReminderType.SECOND: {
        "days_overdue_min": 4,
        "days_overdue_max": 7,
        "tone_description": "concerned but not accusatory. Acknowledge that things can get busy, but make clear this needs attention.",
        "reminder_description": "Follow-up - more direct but still understanding",
        "email_style": "concerned_professional",
        "sms_appropriate": True,
        "example_subject": "Following up on Invoice {inv} - {company}",
        "relationship_focus": "nurture",
        "urgency_level": 2,
    },
    ReminderType.URGENT: {
        "days_overdue_min": 8,
        "days_overdue_max": 14,
        "tone_description": "professional and firm. Clear about consequences but still leaving room for dialogue. This is the 'we need to solve this' conversation.",
        "reminder_description": "Serious but not burning bridges - we need to fix this",
        "email_style": "firm_professional",
        "sms_appropriate": True,
        "example_subject": "Action needed: Invoice {inv} ({company})",
        "relationship_focus": "recover",
        "urgency_level": 3,
    },
    ReminderType.FINAL: {
        "days_overdue_min": 15,
        "days_overdue_max": 29,
        "tone_description": "very clear and direct. Last friendly reminder before next steps. Professional but no-nonsense.",
        "reminder_description": "Final notice - clear about timeline and consequences",
        "email_style": "final_notice",
        "sms_appropriate": True,
        "example_subject": "FINAL NOTICE: Invoice {inv} - immediate action required",
        "relationship_focus": "urgent_recovery",
        "urgency_level": 4,
    },
    ReminderType.LEGAL: {
        "days_overdue_min": 30,
        "days_overdue_max": 999,
        "tone_description": "formal and procedural. This moves to collections posture. Clear, documented, no ambiguity.",
        "reminder_description": "Pre-collection/collections - formal process initiated",
        "email_style": "formal_notice",
        "sms_appropriate": False,
        "example_subject": "URGENT: Account status - Invoice {inv}",
        "relationship_focus": "recover_or_escalate",
        "urgency_level": 5,
    },
}


# Minimum days between reminders of each type
FREQUENCY_CONFIG = {
    ReminderType.FIRST: 2,
    ReminderType.SECOND: 3,
    ReminderType.URGENT: 4,
    ReminderType.FINAL: 5,
    ReminderType.LEGAL: 7,
}


# =============================================================================
# PERSONALIZATION CONTEXT BUILDERS
# =============================================================================

def build_payment_history_context(invoice_count: int, paid_early: int, paid_on_time: int, late_count: int) -> str:
    """Build context string about customer's payment history."""
    if invoice_count == 0:
        return "First-time customer - no payment history available"
    
    if late_count == 0:
        if paid_early > paid_on_time:
            return f"Excellent history - typically pays early ({paid_early} early of {invoice_count} invoices)"
        elif paid_on_time > 0:
            return f"Good history - typically pays on time ({paid_on_time} on-time of {invoice_count} invoices)"
        return "Good payment history"
    
    if late_count <= 2:
        return f"Generally good with occasional delays ({late_count} late of {invoice_count} invoices)"
    
    return f"Multiple late payments ({late_count} late of {invoice_count} invoices) - handle with care"


def build_personalization_context(
    invoice,
    customer: Optional[Customer],
    payment_history: Dict
) -> str:
    """Build context for message personalization."""
    contexts = []
    
    # Amount context
    amount = float(invoice.amount_due or 0)
    if amount > 10000:
        contexts.append("Large invoice - high value, prioritize personal touch")
    elif amount > 1000:
        contexts.append("Mid-range invoice - standard approach")
    else:
        contexts.append("Smaller invoice - efficiency matters too")
    
    # History context
    if payment_history.get("total_invoices", 0) > 10:
        if payment_history.get("late_count", 0) == 0:
            contexts.append("Long-standing customer with perfect payment record")
    
    # Time context
    if invoice.due_date:
        due_month = invoice.due_date.strftime("%B")
        if due_month in ["December", "January"]:
            contexts.append(f"Invoice was due in {due_month} - may have been impacted by holiday timing")
    
    # Customer context
    if customer:
        if customer.full_name:
            contexts.append(f"Customer contact: {customer.full_name}")
    
    return " | ".join(contexts) if contexts else "Standard reminder - no special context"


# =============================================================================
# CHASER AGENT
# =============================================================================

class ChaserAgent(BaseAgent):
    """
    Production-ready ChaserAgent with:
    - Natural, personalized reminder generation via LLM
    - Sophisticated escalation logic
    - Smart frequency management
    - Multi-channel delivery
    """

    def __init__(self, llm: Any, tools: List[BaseTool]):
        super().__init__(llm, tools, "ChaserAgent")
        
        # Get configurable values from environment
        self.llm_model = os.getenv("LLM_MODEL", "nemotron-3-super")
        self.company_name = os.getenv("COMPANY_NAME", "Your Company Name")
        self.sender_name = os.getenv("SENDER_NAME", "Accounts Receivable")
        
        # Initialize LLM with production settings
        try:
            self.reminder_llm = Ollama(
                model=self.llm_model,
                temperature=0.5,  # Balanced creativity
                top_p=0.9
            )
        except Exception as e:
            logger.warning(f"Could not initialize LLM: {e}")
            self.reminder_llm = None

    def process(self, state: AgentState) -> AgentState:
        """Main processing method for sending payment reminders."""
        logger.info(f"ChaserAgent processing state: {state.agent_id}")
        db = None

        try:
            tenant_id = state.tenant_id
            if not tenant_id:
                raise ValueError("tenant_id is required in state")
            
            db = get_tenant_session(tenant_id)

            # Get configurable batch limit from state or use default
            max_reminders_per_run = state.input_data.get("max_reminders_per_run", 10)
            
            overdue_invoices = self._get_overdue_invoices_needing_reminders(db, tenant_id)
            
            # Group by customer to avoid sending multiple reminders to same customer
            customer_invoices = {}
            for inv in overdue_invoices:
                # Look up customer from invoice's customer_id
                customer = db.query(Customer).filter(Customer.id == inv.customer_id).first() if inv.customer_id else None
                customer_email = self._get_customer_email(db, customer, inv)
                if customer_email and customer_email not in customer_invoices:
                    customer_invoices[customer_email] = []
                if customer_email:
                    customer_invoices[customer_email].append(inv)
            
            # Flatten with priority (most overdue first), respecting batch limit
            prioritized = []
            for emails, invs in customer_invoices.items():
                # Sort by days overdue descending
                invs.sort(key=lambda x: (date.today() - x.due_date).days, reverse=True)
                prioritized.extend(invs)
            
            # Apply batch limit
            batched_invoices = prioritized[:max_reminders_per_run]
            
            reminders_sent = []
            errors = []
            skipped = []

            for invoice in batched_invoices:
                try:
                    result = self._process_invoice_reminder(db, invoice)
                    
                    if result["action"] == "sent":
                        reminders_sent.append(result["details"])
                    elif result["action"] == "skipped":
                        skipped.append(result["details"])
                    elif result["action"] == "error":
                        errors.append(result["details"])
                        
                except Exception as e:
                    logger.error(f"Error processing invoice {invoice.id}: {str(e)}")
                    errors.append({
                        "invoice_id": invoice.id,
                        "invoice_number": invoice.invoice_number,
                        "error": str(e)
                    })

            state.output_data = {
                "reminders_sent": reminders_sent,
                "skipped": skipped,
                "errors": errors,
                "status": "chasing_completed",
                "processed_at": utc_now_iso(),
                "summary": {
                    "total_processed": len(overdue_invoices),
                    "sent": len(reminders_sent),
                    "skipped": len(skipped),
                    "errors": len(errors)
                }
            }

            logger.info(
                f"ChaserAgent completed: {len(reminders_sent)} sent, "
                f"{len(skipped)} skipped, {len(errors)} errors"
            )
            return state

        except Exception as e:
            logger.error(f"ChaserAgent failed: {str(e)}")
            if db:
                db.rollback()
            state.error = str(e)
            state.output_data["status"] = "failed"
            return state
        finally:
            if db:
                db.close()

    def _process_invoice_reminder(
        self,
        db,
        invoice: Invoice
    ) -> Dict[str, Any]:
        """Process reminder for a single invoice."""
        
        # Get customer info
        customer = self._get_customer_for_invoice(db, invoice)
        
        # Determine reminder type
        reminder_type = self._determine_reminder_type(invoice)
        if reminder_type is None:
            return {
                "action": "skipped",
                "details": {
                    "invoice_id": invoice.id,
                    "reason": "No reminder type needed or frequency limit"
                }
            }
        
        # Get contact info
        customer_email = self._get_customer_email(db, customer, invoice)
        customer_phone = self._get_customer_phone(db, customer)
        
        # Check opt-outs
        if customer:
            if customer.opt_out_email and customer_email:
                return {"action": "skipped", "details": {"invoice_id": invoice.id, "reason": "Opted out of email"}}
            if customer.opt_out_sms and customer_phone:
                pass  # Still send email if available
        
        if not customer_email and not customer_phone:
            return {
                "action": "error",
                "details": {
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "error": "No contact information"
                }
            }
        
        # Get payment history for personalization
        payment_history = self._get_payment_history(db, invoice.tenant_id, invoice.vendor_name)
        
        # Generate reminder content
        reminder_content = self._generate_reminder_content(
            invoice, customer, reminder_type, payment_history
        )
        
        # Send reminder
        send_result = self._send_reminder(
            invoice, reminder_type, reminder_content,
            customer_email, customer_phone
        )
        
        if send_result["success"]:
            self._update_reminder_tracking(db, invoice, reminder_type)
            return {
                "action": "sent",
                "details": {
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "reminder_type": reminder_type,
                    "sent_at": utc_now_iso(),
                    "contact_method": send_result.get("contact_method", "email"),
                    "subject": reminder_content.get("email_subject", "")
                }
            }
        else:
            return {
                "action": "error",
                "details": {
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "error": send_result.get("error", "Unknown error")
                }
            }

    def _get_customer_for_invoice(self, db, invoice: Invoice) -> Optional[Customer]:
        """Get customer associated with invoice."""
        if invoice.customer_id:
            return db.query(Customer).filter(Customer.id == invoice.customer_id).first()
        
        if invoice.vendor_name:
            return db.query(Customer).filter(
                Customer.company_name.ilike(f"%{invoice.vendor_name}%"),
                Customer.tenant_id == invoice.tenant_id
            ).first()
        return None

    def _get_customer_email(self, db, customer: Optional[Customer], invoice: Optional[Invoice] = None) -> Optional[str]:
        if not customer:
            return invoice.vendor_email if invoice and hasattr(invoice, 'vendor_email') else None
        
        if customer.opt_out_email:
            return None
        return customer.email

    def _get_customer_phone(self, db, customer: Optional[Customer]) -> Optional[str]:
        """Get customer phone with validation."""
        if not customer:
            return None
        if customer.opt_out_sms:
            return None
        
        phone = customer.phone
        if phone and not phone.startswith("+"):
            return None
        return phone

    def _get_payment_history(
        self,
        db,
        tenant_id: int,
        vendor_name: str
    ) -> Dict[str, Any]:
        """Get payment history for personalization."""
        from db.models import Invoice as Inv, Payment
        
        invoices = db.query(Inv).filter(
            Inv.tenant_id == tenant_id,
            Inv.vendor_name.ilike(f"%{vendor_name}%")
        ).all()
        
        payments = db.query(Payment).filter(
            Payment.tenant_id == tenant_id,
            Payment.vendor_name.ilike(f"%{vendor_name}%")
        ).all()
        
        paid_early = sum(1 for inv in invoices if inv.status == "paid" and inv.amount_paid < inv.amount_due)
        paid_on_time = sum(1 for inv in invoices if inv.status == "paid" and inv.amount_paid >= inv.amount_due)
        
        return {
            "total_invoices": len(invoices),
            "total_payments": len(payments),
            "paid_early": paid_early,
            "paid_on_time": paid_on_time,
            "late_count": len(invoices) - paid_early - paid_on_time
        }

    def _get_overdue_invoices_needing_reminders(
        self,
        db,
        tenant_id: int
    ) -> List[Invoice]:
        """Get overdue invoices that need reminders."""
        return db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.due_date < date.today(),
            Invoice.status == "overdue",
            Invoice.amount_paid < Invoice.amount_due
        ).all()

    def _determine_reminder_type(self, invoice: Invoice) -> Optional[ReminderType]:
        """Determine reminder type based on days overdue and history."""
        days_overdue = (date.today() - invoice.due_date).days
        reminder_count = invoice.reminder_count or 0
        
        # Map days overdue to reminder type
        for rem_type, config in ESCALATION_CONFIG.items():
            if config["days_overdue_min"] <= days_overdue <= config["days_overdue_max"]:
                # Check frequency rules
                if reminder_count > 0:
                    last_reminder = invoice.last_reminder_date
                    if last_reminder:
                        days_since_last = (utc_now() - last_reminder).days
                        min_days = FREQUENCY_CONFIG.get(rem_type, 3)
                        if days_since_last < min_days:
                            return None  # Skip - too soon
                
                return rem_type
        
        return None

    def _generate_reminder_content(
        self,
        invoice: Invoice,
        customer: Optional[Customer],
        reminder_type: ReminderType,
        payment_history: Dict
    ) -> Dict[str, Any]:
        """Generate personalized reminder using LLM."""
        
        config = ESCALATION_CONFIG[reminder_type]
        days_overdue = max(1, (date.today() - invoice.due_date).days)
        
        # Prepare template variables
        customer_name = customer.full_name if customer and customer.full_name else invoice.vendor_name
        company_name = customer.company_name if customer and customer.company_name else invoice.vendor_name
        first_name = customer_name.split()[0] if customer_name else "there"
        
        amount_formatted = f"${float(invoice.amount_due):,.2f} {invoice.currency}"
        paid_amount = float(invoice.amount_paid or 0)
        outstanding = float(invoice.amount_due) - paid_amount
        outstanding_formatted = f"${outstanding:,.2f} {invoice.currency}"
        
        payment_history_text = build_payment_history_context(
            payment_history.get("total_invoices", 0),
            payment_history.get("paid_early", 0),
            payment_history.get("paid_on_time", 0),
            payment_history.get("late_count", 0)
        )
        
        personalization_context = build_personalization_context(
            invoice, customer, payment_history
        )
        
        # Try LLM generation first
        if self.reminder_llm:
            try:
                return self._generate_with_llm(
                    customer_name, company_name, first_name,
                    invoice, reminder_type, config,
                    amount_formatted, outstanding_formatted,
                    payment_history_text, personalization_context,
                    days_overdue
                )
            except Exception as e:
                logger.warning(f"LLM generation failed, using fallback: {e}")
        
        # Fallback to template-based generation
        return self._generate_fallback(
            customer_name, company_name, first_name,
            invoice, reminder_type, config,
            amount_formatted, outstanding_formatted,
            days_overdue
        )

    def _generate_with_llm(
        self,
        customer_name: str,
        company_name: str,
        first_name: str,
        invoice: Invoice,
        reminder_type: ReminderType,
        config: Dict,
        amount_formatted: str,
        outstanding_formatted: str,
        payment_history_text: str,
        personalization_context: str,
        days_overdue: int
    ) -> Dict[str, Any]:
        """Generate reminder using LLM."""
        from utils.prompt_guard import sanitize_for_prompt, check_for_injection
        
        is_safe, violations = check_for_injection(personalization_context)
        if not is_safe:
            logger.warning(f"Prompt injection detected in personalization_context: {violations}")
            personalization_context = "[Redacted for security]"
        
        is_safe_hist, hist_violations = check_for_injection(payment_history_text)
        if not is_safe_hist:
            logger.warning(f"Prompt injection detected in payment_history: {hist_violations}")
            payment_history_text = "History unavailable"
        
        customer_name_san = sanitize_for_prompt(customer_name)
        company_name_san = sanitize_for_prompt(company_name)
        personalization_ctx_san = sanitize_for_prompt(personalization_context)
        payment_hist_san = sanitize_for_prompt(payment_history_text)
        
        prompt = REMINDER_GENERATION_PROMPT.format(
            customer_name=customer_name_san,
            company_name=company_name_san,
            reminder_count=(invoice.reminder_count or 0) + 1,
            days_overdue=days_overdue,
            tone_description=config["tone_description"],
            payment_history=payment_hist_san,
            total_invoices="multiple" if payment_history_text != "First-time" else "first",
            reminder_type=reminder_type.value,
            reminder_description=config["reminder_description"],
            invoice_number=invoice.invoice_number,
            due_date_formatted=invoice.due_date.strftime("%B %d, %Y") if invoice.due_date else "N/A",
            amount_formatted=amount_formatted,
            paid_formatted=f"${float(invoice.amount_paid or 0):,.2f}" if invoice.amount_paid else "$0.00",
            outstanding_formatted=outstanding_formatted,
            personalization_context=personalization_ctx_san,
            sender_name=self.sender_name
        )
        
        # Parse JSON response
        from langchain_core.output_parsers import JsonOutputParser
        parser = JsonOutputParser()
        
        chain = self.reminder_llm | parser
        
        try:
            result = chain.invoke(prompt)
            
            # Validate and sanitize
            return {
                "email_subject": result.get("email_subject", f"Invoice {invoice.invoice_number} - Action Needed"),
                "email_body": result.get("email_body", ""),
                "sms_body": result.get("sms_body", ""),
                "tone_notes": result.get("tone_notes", "")
            }
        except Exception as e:
            logger.error(f"LLM JSON parsing failed: {e}")
            raise

    def _generate_fallback(
        self,
        customer_name: str,
        company_name: str,
        first_name: str,
        invoice: Invoice,
        reminder_type: ReminderType,
        config: Dict,
        amount_formatted: str,
        outstanding_formatted: str,
        days_overdue: int
    ) -> Dict[str, Any]:
        """Generate fallback reminder templates."""
        
        templates = {
            ReminderType.FIRST: {
                "subject": f"Quick note about Invoice {invoice.invoice_number}",
                "body": f"""Hi {first_name},

Hope you're doing well! I wanted to shoot you a quick note about Invoice {invoice.invoice_number} for {amount_formatted}.

I know things get busy, so this is just a friendly heads up that it was due on {invoice.due_date.strftime('%B %d')} and is now a few days past due.

No worries - let's get this sorted out. You can pay directly here: [PAYMENT LINK]

Questions? Just reply to this email. I'm happy to help!

Best,
{self.sender_name}"""
            },
            ReminderType.SECOND: {
                "subject": f"Following up on Invoice {invoice.invoice_number} - {company_name}",
                "body": f"""Hi {first_name},

Just following up on Invoice {invoice.invoice_number} for {outstanding_formatted}. This has been outstanding for about {days_overdue} days now.

I totally understand things can slip through the cracks - could this have gotten buried? Let's get it cleared up.

You can pay here: [PAYMENT LINK]

Or if there's anything we can help with on your end, just let me know.

Thanks,
{self.sender_name}"""
            },
            ReminderType.URGENT: {
                "subject": f"Action needed: Invoice {invoice.invoice_number}",
                "body": f"""Hi {first_name},

I wanted to reach out about Invoice {invoice.invoice_number} ({outstanding_formatted}) which is now {days_overdue} days past due.

I'd like to resolve this quickly so we can keep things moving smoothly. Could we get this taken care of this week?

Pay here: [PAYMENT LINK]

If there's an issue or you need to discuss payment terms, please let me know ASAP.

Thanks,
{self.sender_name}"""
            },
            ReminderType.FINAL: {
                "subject": f"FINAL NOTICE: Invoice {invoice.invoice_number} - Action Required",
                "body": f"""Dear {customer_name},

This is a final reminder about Invoice {invoice.invoice_number} for {outstanding_formatted}, now {days_overdue} days overdue.

We need to resolve this to avoid any service interruption or further action. Please process payment by [DATE + 5 DAYS] at the latest.

Pay now: [PAYMENT LINK]

If payment has already been sent, please ignore this notice or reply with confirmation.

Please contact us immediately if you need to discuss.

Regards,
{self.sender_name}"""
            },
            ReminderType.LEGAL: {
                "subject": f"URGENT: Account Status - Invoice {invoice.invoice_number}",
                "body": f"""Dear {customer_name},

Invoice {invoice.invoice_number} for {outstanding_formatted} is now significantly overdue ({days_overdue} days).

Unless payment or a payment arrangement is received within 5 business days, this account will be escalated to collections per our terms of service.

This is your final opportunity to resolve directly. Please contact us immediately.

Regards,
{self.sender_name}"""
            }
        }
        
        template = templates.get(reminder_type, templates[ReminderType.FIRST])
        
        return {
            "email_subject": template["subject"],
            "email_body": template["body"],
            "sms_body": f"Hi {first_name}, Invoice {invoice.invoice_number} for {outstanding_formatted} is {days_overdue} days overdue. Please pay here: [LINK]",
            "tone_notes": "Fallback template - LLM generation unavailable"
        }

    def _send_reminder(
        self,
        invoice: Invoice,
        reminder_type: ReminderType,
        content: Dict,
        customer_email: Optional[str],
        customer_phone: Optional[str]
    ) -> Dict[str, Any]:
        """Send reminder via email and/or SMS with configurable rate limiting."""
        
        results = {"email_sent": False, "sms_sent": False, "errors": []}
        contact_methods = []
        
        rate_limit_delay = float(os.getenv("REMINDER_RATE_LIMIT_SECONDS", "0.5"))
        
        # Send email
        if customer_email and content.get("email_body"):
            try:
                result = send_email(
                    to_email=customer_email,
                    subject=content["email_subject"],
                    body=content["email_body"],
                    is_html=False
                )
                if result.get("success"):
                    results["email_sent"] = True
                    contact_methods.append("email")
                else:
                    results["errors"].append(f"Email: {result.get('error')}")
            except Exception as e:
                results["errors"].append(f"Email exception: {str(e)}")
        
        if rate_limit_delay > 0:
            time.sleep(rate_limit_delay)
        
        # Send SMS for urgent/final or if no email
        config = ESCALATION_CONFIG[reminder_type]
        should_sms = config.get("sms_appropriate", False) and customer_phone
        
        if should_sms and content.get("sms_body"):
            try:
                sms_body = content["sms_body"][:155]  # Ensure length
                result = send_sms(to_number=customer_phone, message=sms_body)
                if result.get("success"):
                    results["sms_sent"] = True
                    contact_methods.append("sms")
                else:
                    results["errors"].append(f"SMS: {result.get('error')}")
            except Exception as e:
                results["errors"].append(f"SMS exception: {str(e)}")
        
        success = results["email_sent"] or results["sms_sent"]
        
        return {
            "success": success,
            "contact_method": "+".join(contact_methods) if contact_methods else "none",
            "error": "; ".join(results["errors"]) if results["errors"] else None
        }

    def _update_reminder_tracking(
        self,
        db,
        invoice: Invoice,
        reminder_type: ReminderType
    ) -> None:
        """Update invoice with reminder tracking."""
        try:
            invoice.reminder_count = (invoice.reminder_count or 0) + 1
            invoice.last_reminder_date = utc_now()
            invoice.last_reminder_type = reminder_type.value
            db.commit()
        except Exception as e:
            logger.error(f"Failed to update reminder tracking: {e}")
            db.rollback()


# =============================================================================
# TOOLS
# =============================================================================

class SendReminderTool(BaseTool):
    name: str = "send_payment_reminder"
    description: str = "Record that a payment reminder was sent"
    
    def _run(
        self,
        invoice_id: int,
        reminder_type: str,
        customer_email: str,
        customer_phone: Optional[str] = None
    ) -> str:
        return f"Reminder logged: invoice={invoice_id}, type={reminder_type}, email={customer_email}"

    async def _arun(self, **kwargs) -> str:
        return self._run(**kwargs)


class UpdateReminderStatusTool(BaseTool):
    name: str = "update_reminder_status"
    description: str = "Update reminder status for an invoice"
    
    def _run(self, invoice_id: int, reminder_sent: bool, reminder_type: str) -> str:
        return f"Status updated: invoice={invoice_id}, sent={reminder_sent}, type={reminder_type}"

    async def _arun(self, **kwargs) -> str:
        return self._run(**kwargs)
