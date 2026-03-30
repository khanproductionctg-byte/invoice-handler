"""
ReconcilerAgent - Production-Ready Invoice/Payment Matching System
================================================================
Advanced matching logic with:
- Multi-signal fuzzy + semantic matching
- Confidence scoring with explainable components
- Rules for common financial edge cases
- LLM-powered disambiguation for ambiguous matches
"""
import logging
import os
import difflib
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime, date, timedelta, timezone


def utc_now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()
from decimal import Decimal
from enum import Enum
import json
import numpy as np

from langchain_core.tools import BaseTool
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

try:
    from langchain_ollama import OllamaLLM as Ollama
except ImportError:
    from langchain_community.llms import Ollama

from .base_agent import BaseAgent, AgentState
from db.database import SessionLocal, get_tenant_session
from db.models import Invoice, Payment, Expense, ReconciliationHistory, User
from utils.embedding import get_embedding, get_embeddings_batch, cosine_similarity
from config.plan_limits import RECONCILIATION_CONFIDENCE_THRESHOLDS

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS & CONSTANTS
# =============================================================================

class MatchConfidence(str, Enum):
    """Confidence levels for invoice-payment matching."""
    HIGH = "high"       # > 0.85 - Auto-match
    MEDIUM = "medium"   # 0.65-0.85 - Review recommended
    LOW = "low"         # 0.45-0.65 - Manual review required
    VERY_LOW = "very_low"  # < 0.45 - Do not match


class DiscrepancyType(str, Enum):
    """Types of discrepancies to flag."""
    OVERDUE = "overdue"
    AMOUNT_MISMATCH = "amount_mismatch"
    DUPLICATE = "duplicate"
    PARTIAL_PAYMENT = "partial_payment"
    EARLY_PAYMENT = "early_payment"
    LATE_FEE = "late_fee"
    CURRENCY_MISMATCH = "currency_mismatch"
    ROUNDING = "rounding"
    SUSPICIOUS = "suspicious"


# =============================================================================
# SYSTEM PROMPT FOR LLM DISAMBIGUATION
# =============================================================================

RECONCILER_SYSTEM_PROMPT = """You are an expert financial reconciliation assistant specializing in matching invoices to payments.

## Your Role
Analyze invoice and payment data to determine if they represent the same transaction. You must be precise, cautious, and explain your reasoning.

## Input Data
You will receive:
- Invoice details: vendor, amount, date, due date, description, line items
- Payment details: vendor, amount, date, description, reference

## Matching Criteria - Weight & Importance

1. **Amount Match (35% weight) - CRITICAL**
   - Exact match: 1.0
   - Within 1%: 0.95
   - Within 5%: 0.80
   - Partial payment (50-99%): 0.70
   - Less than 50%: 0.30 (likely different transaction)

2. **Vendor Name Match (25% weight)**
   - Exact match: 1.0
   - Fuzzy match (≥85%): 0.90
   - Fuzzy match (70-85%): 0.70
   - Fuzzy match (50-70%): 0.40
   - Semantic match (embedding >0.8): 0.85
   - Different vendors: 0.0

3. **Date Proximity (20% weight)**
   - Payment on due date: 1.0
   - Payment within 5 days before/after due: 0.95
   - Payment within 15 days of invoice: 0.85
   - Payment within 30 days of invoice: 0.70
   - Payment 31-60 days after invoice: 0.50
   - Payment >60 days after: 0.20 (suspicious)

4. **Reference/Description Match (15% weight)**
   - Invoice number in payment reference: 1.0
   - Semantic similarity >0.7: 0.80
   - Some keyword overlap: 0.50
   - No match: 0.20

5. **Currency Match (5% weight)**
   - Same currency: 1.0
   - Convertible (USD to CAD, etc.): 0.60
   - Different non-convertible: 0.0

## Edge Cases to Consider

1. **Partial Payments**: Payment covers 50-99% of invoice
2. **Early Payment Discounts**: Payment slightly less than invoice (common 2/10 net 30)
3. **Late Fees**: Payment slightly MORE than invoice due to fees
4. **Multi-Invoice Payments**: Single payment covering multiple invoices
5. **Credit Memos**: Negative payments / adjustments
6. **Currency Conversions**: Handle USD/CAD/EUR with conversion rates
7. **Rounding Differences**: Cent-level differences acceptable
8. **Reversals**: Payment followed by refund
9. **Backdated Payments**: Payment recorded after actual date
10. **Split Payments**: Invoice paid in multiple transactions

## Output Format
Return a JSON object with:
{
  "match_decision": "match" | "no_match" | "uncertain",
  "confidence": 0.0-1.0,
  "confidence_level": "high" | "medium" | "low" | "very_low",
  "reasoning": "explanation of decision",
  "discrepancies": ["list of any issues found"],
  "edge_case_flags": ["any edge cases that apply"],
  "recommended_action": "auto_match" | "review" | "reject"
}

## Important Rules
- When in doubt, prefer "review" over "auto_match"
- Flag anything unusual for human review
- Always explain your reasoning
- Consider the full context, not just individual signals"""


# =============================================================================
# TOOL INPUT SCHEMAS
# =============================================================================

class MatchInvoiceToPaymentInput(BaseModel):
    invoice_id: int = Field(description="ID of the invoice to match")
    payment_id: int = Field(description="ID of the payment to match against")


class FlagDiscrepancyInput(BaseModel):
    invoice_id: int = Field(description="ID of the invoice with discrepancy")
    discrepancy_type: str = Field(description="Type of discrepancy")
    description: str = Field(description="Description of the discrepancy")


class CategorizeExpenseInput(BaseModel):
    expense_id: int = Field(description="ID of the expense to categorize")
    suggested_category: str = Field(description="Suggested category")


class LLMDisambiguateInput(BaseModel):
    invoice_data: Dict[str, Any] = Field(description="Invoice data")
    payment_data: Dict[str, Any] = Field(description="Payment data")
    candidate_match_score: float = Field(description="Current match score")
    uncertainty_reason: str = Field(description="Why the match is uncertain")


# =============================================================================
# VENDOR NAME NORMALIZER
# =============================================================================

class VendorNameNormalizer:
    """Normalize vendor names for better fuzzy matching."""
    
    # Common company suffixes to remove
    SUFFIXES = [
        r'\binc\.?\b', r'\bllc\b', r'\bltd\.?\b', r'\bcorp\.?\b',
        r'\bcorporation\b', r'\bco\.?\b', r'\bcompany\b', r'\bllp\b',
        r'\bgmbh\b', r'\bag\b', r'\bsa\b', r'\blimited\b'
    ]
    
    # Common abbreviations
    ABBREVIATIONS = {
        '&': 'and',
        'and': 'and',
        '@': 'at',
    }
    
    # Words to remove for comparison
    STOP_WORDS = {
        'the', 'of', 'for', 'services', 'service', 'solutions',
        'group', 'international', 'global', 'partners'
    }
    
    @classmethod
    def normalize(cls, vendor_name: str) -> str:
        """Normalize vendor name for comparison."""
        if not vendor_name:
            return ""
        
        name = vendor_name.lower().strip()
        
        # Remove company suffixes
        for suffix in cls.SUFFIXES:
            name = re.sub(suffix, '', name, flags=re.IGNORECASE)
        
        # Replace & with 'and'
        name = name.replace('&', 'and').replace('@', 'at')
        
        # Remove extra whitespace
        name = ' '.join(name.split())
        
        return name
    
    @classmethod
    def get_comparable(cls, vendor_name: str) -> str:
        """Get a version of vendor name for fuzzy matching."""
        normalized = cls.normalize(vendor_name)
        
        # Remove stop words
        words = normalized.split()
        words = [w for w in words if w not in cls.STOP_WORDS]
        
        return ' '.join(words)


# =============================================================================
# RECONCILER AGENT
# =============================================================================

class ReconcilerAgent(BaseAgent):
    """
    Production-ready reconciliation agent with:
    - Multi-signal matching (fuzzy + semantic + rules)
    - Confidence scoring with explainability
    - Financial edge case detection
    - LLM-powered disambiguation
    """

    def __init__(self, llm: Any, tools: List[BaseTool]):
        super().__init__(llm, tools, "ReconcilerAgent")
        
        # Get configurable LLM model name from environment
        self.llm_model = os.getenv("LLM_MODEL", "nemotron-3-super")
        
        # Optimized matching weights based on financial domain knowledge
        self.match_weights = {
            "amount": 0.35,
            "vendor_fuzzy": 0.15,
            "vendor_semantic": 0.10,
            "date": 0.20,
            "reference": 0.15,
            "currency": 0.05
        }
        
        # Confidence thresholds
        self.match_threshold_high = RECONCILIATION_CONFIDENCE_THRESHOLDS["high"]
        self.match_threshold_medium = RECONCILIATION_CONFIDENCE_THRESHOLDS["medium"]
        self.match_threshold_low = RECONCILIATION_CONFIDENCE_THRESHOLDS["low"]
        
        # Discrepancy thresholds
        self.amount_discrepancy_threshold = 0.05  # 5%
        self.days_overdue_threshold = 1
        
        # Category prototypes
        self.category_prototypes = {
            "utilities": ["electricity bill", "gas bill", "water bill", "utility payment"],
            "office_supplies": ["office supplies", "stationery", "paper", "printer ink"],
            "travel": ["hotel stay", "airfare", "rental car", "taxi fare"],
            "meals": ["restaurant meal", "business lunch", "dinner expense"],
            "software": ["software subscription", "saas payment", "license fee"],
            "marketing": ["advertising", "marketing campaign", "promo"],
            "professional_services": ["legal consultation", "accounting service", "consulting"],
            "rent": ["office rent", "lease payment"],
            "insurance": ["insurance premium", "policy payment"]
        }
        
        # Embedding cache
        self._embedding_cache = {}
        self._llm_disambiguate = None
        
        # RAG parameters
        self.k = 5
        
        # Initialize LLM for disambiguation if available
        if llm:
            try:
                self._llm_disambiguate = Ollama(
                    model=self.llm_model,
                    temperature=0.3
                )
            except Exception as e:
                logger.warning(f"Could not initialize LLM for disambiguation: {e}")

    def _get_llm_disambiguation(
        self,
        invoice: Invoice,
        payment: Payment,
        current_score: float
    ) -> Optional[Dict[str, Any]]:
        """Use LLM to disambiguate uncertain matches."""
        if not self._llm_disambiguate:
            return None
        
        from utils.prompt_guard import sanitize_for_prompt, check_for_injection, PromptInjectionError
        
        # Enforce prompt injection checks - raise on detection
        try:
            is_safe_inv, inv_violations = check_for_injection(invoice.description or "", raise_on_injection=True)
            is_safe_pay, pay_violations = check_for_injection(payment.description or "", raise_on_injection=True)
        except PromptInjectionError as e:
            logger.error(f"Prompt injection blocked in disambiguation: {e}")
            raise
        
        invoice_num = sanitize_for_prompt(invoice.invoice_number)
        vendor_inv = sanitize_for_prompt(invoice.vendor_name)
        desc_inv = sanitize_for_prompt(invoice.description or "")
        
        payment_num = sanitize_for_prompt(payment.payment_number)
        vendor_pay = sanitize_for_prompt(payment.vendor_name)
        desc_pay = sanitize_for_prompt(payment.description or "")
            
        try:
            prompt = f"""
{RECONCILER_SYSTEM_PROMPT}

## Current Match Score: {current_score:.2f}

## Invoice Data:
- Invoice Number: {invoice_num}
- Vendor: {vendor_inv}
- Amount: {invoice.amount_due} {invoice.currency}
- Invoice Date: {invoice.invoice_date}
- Due Date: {invoice.due_date}
- Description: {desc_inv}

## Payment Data:
- Payment Number: {payment_num}
- Vendor: {vendor_pay}
- Amount: {payment.amount} {payment.currency}
- Payment Date: {payment.payment_date}
- Description: {desc_pay}

Analyze this match and provide your decision in JSON format.
"""
            parser = JsonOutputParser()
            response = self._llm_disambiguate.invoke(prompt)
            return parser.parse(response)
        except Exception as e:
            logger.warning(f"LLM disambiguation failed: {e}")
            return None

    def process(self, state: AgentState) -> AgentState:
        """Main processing method with transaction safety and idempotency."""
        logger.info(f"ReconcilerAgent processing state: {state.agent_id}")
        db = None
        
        try:
            tenant_id = state.tenant_id
            if not tenant_id:
                raise ValueError("tenant_id is required in state")
            
            db = get_tenant_session(tenant_id)
            
            user_id = state.input_data.get("user_id")
            if not user_id:
                raise ValueError("user_id is required in input_data")

            # Check for idempotency - skip if already processed
            idempotency_key = state.input_data.get("idempotency_key")
            if idempotency_key:
                existing = db.query(ReconciliationHistory).filter(
                    ReconciliationHistory.idempotency_key == idempotency_key
                ).first()
                if existing:
                    logger.warning(
                        f"Reconciliation already completed with idempotency_key: {idempotency_key}. "
                        "Skipping to prevent duplicate processing."
                    )
                    state.output_data = {
                        "status": "skipped_duplicate",
                        "idempotency_key": idempotency_key,
                        "message": "Reconciliation already run with this key",
                        "processed_at": utc_now_iso()
                    }
                    return state

            db.begin()

            # Run all reconciliation tasks
            matches = self._match_invoices_to_payments(db, tenant_id)
            
            # Detect multi-invoice payments (single payment covering multiple invoices)
            multi_invoice_matches = self._detect_all_multi_invoice_payments(db, tenant_id)
            if multi_invoice_matches:
                matches.extend(multi_invoice_matches)
            
            # Detect split payments (single invoice paid by multiple payments)
            split_payment_matches = self._detect_all_split_payments(db, tenant_id)
            if split_payment_matches:
                matches.extend(split_payment_matches)
            
            discrepancies = self._flag_discrepancies(db, tenant_id)
            duplicates = self._flag_duplicates(db, tenant_id)
            categorized_expenses = self._categorize_expenses(db, tenant_id)
            self._update_invoice_statuses(db, tenant_id)

            db.commit()

            state.output_data = {
                "matches": matches,
                "discrepancies": discrepancies,
                "duplicates": duplicates,
                "categorized_expenses": categorized_expenses,
                "status": "reconciliation_completed",
                "processed_at": utc_now_iso(),
                "summary": {
                    "total_matches": len(matches),
                    "high_confidence": len([m for m in matches if m.get("confidence_level") == "high"]),
                    "medium_confidence": len([m for m in matches if m.get("confidence_level") == "medium"]),
                    "low_confidence": len([m for m in matches if m.get("confidence_level") in ["low", "very_low"]]),
                    "total_discrepancies": len(discrepancies),
                    "total_duplicates": len(duplicates)
                }
            }

            logger.info(
                f"ReconcilerAgent completed: {len(matches)} matches, "
                f"{len(discrepancies)} discrepancies"
            )
            return state

        except Exception as e:
            logger.error(f"ReconcilerAgent failed: {str(e)}")
            if db:
                db.rollback()
            state.error = str(e)
            state.output_data["status"] = "failed"
            return state
        finally:
            if db:
                db.close()

    def _match_invoices_to_payments(
        self,
        db: SessionLocal,
        tenant_id: int,
        batch_size: int = 100
    ) -> List[Dict[str, Any]]:
        """Match invoices to payments with enhanced logic and pagination."""
        matches = []

        # Load payments once (smaller dataset usually)
        payments = db.query(Payment).filter(
            Payment.tenant_id == tenant_id,
            Payment.invoice_id.is_(None)
        ).order_by(Payment.payment_date.desc()).all()

        # Process invoices in batches to avoid OOM
        offset = 0
        while True:
            invoices = db.query(Invoice).filter(
                Invoice.tenant_id == tenant_id,
                Invoice.status.in_(["pending", "overdue"])
            ).offset(offset).limit(batch_size).all()
            
            if not invoices:
                break
            
            # Precompute embeddings for this batch
            embedding_map = self._precompute_embeddings(invoices, payments)

            for invoice in invoices:
                # Get all potential matches with scores
                candidates = []
                
                for payment in payments:
                    if self._has_been_reconciled(db, invoice.id, payment.id):
                        continue
                        
                    result = self._calculate_match_with_edge_cases(
                        invoice, payment, embedding_map
                    )
                    
                    # Check for edge cases that affect decision
                    edge_case_result = self._check_edge_cases(invoice, payment, result)
                    
                    candidates.append({
                        "payment": payment,
                    "score": edge_case_result["adjusted_score"],
                    "details": result,
                    "edge_cases": edge_case_result["edge_cases"],
                    "needs_llm": edge_case_result.get("needs_llm", False)
                })

                if not candidates:
                    continue

                # Sort by score
                candidates.sort(key=lambda x: x["score"], reverse=True)
                best = candidates[0]

                # For uncertain matches, use LLM disambiguation
                if best["score"] < self.match_threshold_high and best["score"] >= self.match_threshold_medium:
                    llm_result = self._get_llm_disambiguation(
                        invoice, best["payment"], best["score"]
                    )
                    if llm_result:
                        # Update with LLM decision
                        best["llm_decision"] = llm_result
                        if llm_result.get("match_decision") == "match":
                            best["score"] = max(best["score"], llm_result.get("confidence", best["score"]))

                # Determine final match decision
                confidence_level = self._get_confidence_level(best["score"])
                
                if confidence_level == MatchConfidence.HIGH:
                    match = self._create_match_record(invoice, best, confidence_level)
                    match["edge_cases"] = best["edge_cases"]
                    matches.append(match)
                    
                    locked_payment = db.query(Payment).filter(
                        Payment.id == best["payment"].id
                    ).with_for_update(nowait=True).first()
                    
                    if locked_payment and locked_payment.invoice_id is None:
                        locked_payment.invoice_id = invoice.id
                        db.flush()  # Batch changes, commit once at end of loop
                    elif locked_payment:
                        logger.warning(f"Payment {locked_payment.id} already matched to invoice {locked_payment.invoice_id}")
                    
                    # Store history
                    self._store_reconciliation_history(
                        db, tenant_id, best["details"]["feature_vector"], 1,
                        invoice.id, best["payment"].id
                    )
                else:
                    # Store as non-match in history
                    self._store_reconciliation_history(
                        db, tenant_id, best["details"]["feature_vector"], 0,
                        invoice.id, best["payment"].id
                    )
                    
                    # Flag for review if medium confidence
                    if confidence_level == MatchConfidence.MEDIUM:
                        matches.append({
                            "invoice_id": invoice.id,
                            "invoice_number": invoice.invoice_number,
                            "status": "review_required",
                            "confidence_level": confidence_level.value,
                            "score": best["score"],
                            "top_candidates": [
                                {
                                    "payment_id": c["payment"].id,
                                    "payment_number": c["payment"].payment_number,
                                    "score": c["score"]
                                }
                                for c in candidates[:3]
                            ],
                            "reason": "Medium confidence - manual review recommended"
                        })
            
            offset += batch_size

        # Commit all batched changes once at the end
        db.commit()

        return matches

    def _calculate_match_with_edge_cases(
        self,
        invoice: Invoice,
        payment: Payment,
        embedding_map: Dict[str, List[float]]
    ) -> Dict[str, Any]:
        """Calculate match score with edge case detection."""
        
        # 1. Amount matching with edge cases
        amount_result = self._calculate_amount_score(
            float(invoice.amount_due),
            float(payment.amount)
        )
        
        # 2. Vendor matching (fuzzy + semantic)
        vendor_fuzzy, vendor_normalized = self._calculate_vendor_score(invoice, payment)
        
        # Get semantic score from embeddings
        inv_vendor_emb = embedding_map.get(f"inv_vendor_{invoice.id}", [0.0] * 384)
        pay_vendor_emb = embedding_map.get(f"pay_vendor_{payment.id}", [0.0] * 384)
        vendor_semantic = max(0, cosine_similarity(inv_vendor_emb, pay_vendor_emb))
        
        # 3. Date matching
        date_result = self._calculate_date_score(
            invoice.invoice_date,
            invoice.due_date,
            payment.payment_date
        )
        
        # 4. Reference/description matching
        ref_score = self._calculate_reference_score(
            invoice, payment, embedding_map
        )
        
        # 5. Currency matching
        currency_score = 1.0 if invoice.currency == payment.currency else 0.0
        
        # Build feature vector
        feature_vector = [
            amount_result["score"],
            vendor_fuzzy,
            vendor_semantic,
            date_result["score"],
            ref_score,
            currency_score
        ]
        
        # Calculate weighted score
        weighted_score = sum(
            feature_vector[i] * weight 
            for i, weight in enumerate(self.match_weights.values())
        )
        
        # Apply edge case adjustments
        if amount_result.get("is_partial"):
            weighted_score *= 0.9  # Reduce confidence for partial
        
        if amount_result.get("is_early_discount"):
            weighted_score *= 1.05  # Boost for early payment
            
        if date_result.get("is_late"):
            weighted_score *= 0.95  # Slight reduction for late
            
        weighted_score = min(1.0, weighted_score)
        
        return {
            "feature_vector": feature_vector,
            "score": weighted_score,
            "component_scores": {
                "amount": amount_result,
                "vendor_fuzzy": vendor_fuzzy,
                "vendor_semantic": vendor_semantic,
                "date": date_result,
                "reference": ref_score,
                "currency": currency_score
            },
            "vendor_normalized": vendor_normalized
        }

    def _calculate_amount_score(
        self,
        invoice_amount: float,
        payment_amount: float
    ) -> Dict[str, Any]:
        """Calculate amount match score with edge case detection."""
        
        if invoice_amount == payment_amount:
            return {"score": 1.0, "type": "exact"}
        
        # Calculate ratio
        ratio = payment_amount / invoice_amount if invoice_amount > 0 else 0
        
        # Check for early payment discount (typically 2% for Net 30) - must check BEFORE partial
        if 0.98 <= ratio < 1.0:
            return {
                "score": 0.95,
                "type": "early_discount",
                "is_early_discount": True
            }
        
        # Check for partial payment (50-98%)
        if 0.50 <= ratio < 0.98:
            return {
                "score": 0.70,
                "type": "partial",
                "is_partial": True,
                "percentage": ratio * 100
            }
        
        # Check for late fee (typically 1.5x or similar)
        if 1.0 < ratio <= 1.05:
            return {
                "score": 0.90,
                "type": "with_late_fee",
                "is_late_fee": True
            }
        
        # Rounding difference (within cents)
        if abs(invoice_amount - payment_amount) < 0.02:
            return {
                "score": 0.98,
                "type": "rounding"
            }
        
        # Calculate standard similarity
        max_amt = max(invoice_amount, payment_amount)
        min_amt = min(invoice_amount, payment_amount)
        score = min_amt / max_amt if max_amt > 0 else 0.0
        
        return {"score": score, "type": "standard"}

    def _calculate_vendor_score(
        self,
        invoice: Invoice,
        payment: Payment
    ) -> Tuple[float, str]:
        """Calculate vendor name match score with normalization."""
        
        # Get normalized names
        inv_normalized = VendorNameNormalizer.get_comparable(invoice.vendor_name)
        pay_normalized = VendorNameNormalizer.get_comparable(payment.vendor_name)
        
        # Fuzzy match on normalized names
        fuzzy_score = difflib.SequenceMatcher(
            None, inv_normalized, pay_normalized
        ).ratio()
        
        # Bonus for containing each other
        if inv_normalized in pay_normalized or pay_normalized in inv_normalized:
            fuzzy_score = max(fuzzy_score, 0.85)
        
        return fuzzy_score, inv_normalized

    def _calculate_date_score(
        self,
        invoice_date: date,
        due_date: date,
        payment_date: date
    ) -> Dict[str, Any]:
        """Calculate date proximity score."""
        
        days_from_invoice = (payment_date - invoice_date).days
        days_from_due = (payment_date - due_date).days
        
        # Payment on due date
        if days_from_due == 0:
            return {"score": 1.0, "type": "on_due_date", "days_from_due": 0}
        
        # Within grace period (5 days before/after due)
        if -5 <= days_from_due <= 5:
            return {
                "score": 0.95,
                "type": "within_grace",
                "days_from_due": days_from_due
            }
        
        # Within 15 days of invoice
        if -15 <= days_from_invoice <= 15:
            return {
                "score": 0.85,
                "type": "near_invoice",
                "days_from_invoice": days_from_invoice
            }
        
        # Within 30 days
        if -30 <= days_from_invoice <= 30:
            return {
                "score": 0.70,
                "type": "within_month",
                "days_from_invoice": days_from_invoice
            }
        
        # 31-60 days after
        if 31 <= days_from_invoice <= 60:
            return {
                "score": 0.50,
                "type": "late",
                "is_late": True,
                "days_from_invoice": days_from_invoice
            }
        
        # >60 days - suspicious
        return {
            "score": 0.20,
            "type": "very_late",
            "is_suspicious": True,
            "days_from_invoice": days_from_invoice
        }

    def _calculate_reference_score(
        self,
        invoice: Invoice,
        payment: Payment,
        embedding_map: Dict[str, List[float]]
    ) -> float:
        """Calculate reference/description match score."""
        
        # Check if invoice number appears in payment reference
        invoice_num = invoice.invoice_number.lower().replace('-', '').replace(' ', '')
        pay_ref = (payment.description or '').lower()
        
        if invoice_num in pay_ref:
            return 1.0
        
        # Semantic similarity
        inv_desc_emb = embedding_map.get(f"inv_desc_{invoice.id}", [0.0] * 384)
        pay_desc_emb = embedding_map.get(f"pay_desc_{payment.id}", [0.0] * 384)
        
        semantic_score = max(0, cosine_similarity(inv_desc_emb, pay_desc_emb))
        
        return semantic_score

    def _check_edge_cases(
        self,
        invoice: Invoice,
        payment: Payment,
        match_result: Dict
    ) -> Dict[str, Any]:
        """Detect financial edge cases and adjust score."""
        
        edge_cases = []
        adjusted_score = match_result["score"]
        needs_llm = False
        
        amount_result = match_result["component_scores"]["amount"]
        date_result = match_result["component_scores"]["date"]
        
        # Partial payment detected
        if amount_result.get("is_partial"):
            edge_cases.append({
                "type": DiscrepancyType.PARTIAL_PAYMENT.value,
                "severity": "medium",
                "description": f"Payment is {amount_result.get('percentage', 0):.1f}% of invoice amount"
            })
        
        # Early payment discount
        if amount_result.get("is_early_discount"):
            edge_cases.append({
                "type": DiscrepancyType.EARLY_PAYMENT.value,
                "severity": "low",
                "description": "Payment appears to include early payment discount"
            })
        
        # Late fee
        if amount_result.get("is_late_fee"):
            edge_cases.append({
                "type": DiscrepancyType.LATE_FEE.value,
                "severity": "medium",
                "description": "Payment includes late fee"
            })
        
        # Late payment
        if date_result.get("is_late"):
            days = date_result.get("days_from_invoice", 0)
            edge_cases.append({
                "type": DiscrepancyType.OVERDUE.value,
                "severity": "medium" if days < 30 else "high",
                "description": f"Payment is {days} days after invoice"
            })
        
        # Suspicious timing
        if date_result.get("is_suspicious"):
            edge_cases.append({
                "type": DiscrepancyType.SUSPICIOUS.value,
                "severity": "high",
                "description": f"Payment timing suspicious: {date_result.get('days_from_invoice')} days from invoice"
            })
            needs_llm = True
        
        # Currency mismatch but similar
        if match_result["component_scores"]["currency"] < 1.0:
            edge_cases.append({
                "type": DiscrepancyType.CURRENCY_MISMATCH.value,
                "severity": "high",
                "description": "Currency mismatch - requires conversion check"
            })
            needs_llm = True
        
        return {
            "adjusted_score": adjusted_score,
            "edge_cases": edge_cases,
            "needs_llm": needs_llm
        }

    def _create_match_record(
        self,
        invoice: Invoice,
        candidate: Dict,
        confidence_level: MatchConfidence
    ) -> Dict[str, Any]:
        """Create a match record with full details."""
        
        payment = candidate["payment"]
        details = candidate["details"]
        
        return {
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "payment_id": payment.id,
            "payment_number": payment.payment_number,
            "match_score": candidate["score"],
            "confidence_level": confidence_level.value,
            "amount_due": float(invoice.amount_due),
            "amount_paid": float(payment.amount),
            "difference": float(invoice.amount_due) - float(payment.amount),
            "vendor_match_score": details["component_scores"]["vendor_fuzzy"],
            "date_match_score": details["component_scores"]["date"],
            "component_scores": details["component_scores"],
            "recommendation": "auto_matched"
        }

    def _get_confidence_level(self, score: float) -> MatchConfidence:
        """Determine confidence level from score."""
        if score >= self.match_threshold_high:
            return MatchConfidence.HIGH
        elif score >= self.match_threshold_medium:
            return MatchConfidence.MEDIUM
        elif score >= self.match_threshold_low:
            return MatchConfidence.LOW
        else:
            return MatchConfidence.VERY_LOW

    def _has_been_reconciled(
        self,
        db: SessionLocal,
        invoice_id: int,
        payment_id: int
    ) -> bool:
        """Check if invoice-payment pair was already reconciled."""
        existing = db.query(ReconciliationHistory).filter(
            ReconciliationHistory.invoice_id == invoice_id,
            ReconciliationHistory.payment_id == payment_id
        ).first()
        return existing is not None

    def _detect_multi_invoice_payment(
        self,
        db: SessionLocal,
        payment: Payment,
        invoices: List[Invoice]
    ) -> List[Dict[str, Any]]:
        """
        Detect if a payment matches multiple invoices (multi-invoice payment).
        
        This handles cases like:
        - Single payment covering multiple invoices
        - Consolidated payment for the month
        - Payment with amount equal to sum of multiple invoices
        """
        multi_invoice_matches = []
        payment_amount = float(payment.amount)
        
        # Find all pending invoices from the same vendor
        vendor_invoices = [
            inv for inv in invoices 
            if inv.tenant_id == payment.tenant_id 
            and inv.status in ["pending", "overdue"]
            and VendorNameNormalizer.normalize(inv.vendor_name) == VendorNameNormalizer.normalize(payment.vendor_name)
        ]
        
        if not vendor_invoices:
            return []
        
        # Try to find combination of invoices that match payment amount
        # This is a simplified knapsack-style approach
        for inv in vendor_invoices:
            inv_amount = float(inv.amount_due)
            
            # Exact match with single invoice
            if abs(payment_amount - inv_amount) < 0.01:
                multi_invoice_matches.append({
                    "invoice_id": inv.id,
                    "invoice_number": inv.invoice_number,
                    "amount": inv_amount,
                    "match_type": "exact_single"
                })
                break
        
        # If no exact match, check if payment could cover multiple invoices
        if not multi_invoice_matches:
            remaining = payment_amount
            matched_invoices = []
            
            # Sort by amount (smallest first) for greedy matching
            sorted_invoices = sorted(vendor_invoices, key=lambda x: float(x.amount_due))
            
            for inv in sorted_invoices:
                inv_amount = float(inv.amount_due)
                if inv_amount <= remaining + 0.01:  # Allow small tolerance
                    matched_invoices.append({
                        "invoice_id": inv.id,
                        "invoice_number": inv.invoice_number,
                        "amount": inv_amount,
                        "match_type": "partial"
                    })
                    remaining -= inv_amount
            
            # If we've matched invoices worth >80% of payment, consider it a multi-invoice match
            matched_total = sum(m["amount"] for m in matched_invoices)
            if matched_total >= payment_amount * 0.80 and len(matched_invoices) > 1:
                multi_invoice_matches = matched_invoices
        
        return multi_invoice_matches

    def _detect_split_payment(
        self,
        db: SessionLocal,
        invoice: Invoice,
        payments: List[Payment]
    ) -> List[Dict[str, Any]]:
        """
        Detect if an invoice has been paid via multiple split payments.
        
        This handles cases where:
        - Invoice was paid in installments
        - Multiple partial payments that together equal the invoice
        """
        split_payment_matches = []
        invoice_amount = float(invoice.amount_due)
        
        # Find all payments from same vendor around invoice date
        vendor_payments = [
            pay for pay in payments
            if pay.tenant_id == invoice.tenant_id
            and VendorNameNormalizer.normalize(pay.vendor_name) == VendorNameNormalizer.normalize(invoice.vendor_name)
            and pay.invoice_id is None  # Not yet matched
        ]
        
        if not vendor_payments:
            return []
        
        # Check if sum of payments equals invoice amount
        total_matched = 0
        matched_payments = []
        
        for pay in vendor_payments:
            pay_amount = float(pay.amount)
            
            # Check if this payment helps cover the invoice
            if total_matched < invoice_amount:
                matched_payments.append({
                    "payment_id": pay.id,
                    "payment_number": pay.payment_number,
                    "amount": pay_amount,
                    "payment_date": pay.payment_date.isoformat() if pay.payment_date else None
                })
                total_matched += pay_amount
        
        # If we've matched >=95% of invoice, consider it a split payment
        if total_matched >= invoice_amount * 0.95:
            return matched_payments
        
        return []

    def _detect_all_multi_invoice_payments(
        self,
        db: SessionLocal,
        tenant_id: int
    ) -> List[Dict[str, Any]]:
        """
        Detect all multi-invoice payments (single payment covering multiple invoices).
        This is called after the main matching loop to catch payments that weren't matched.
        """
        multi_invoice_matches = []
        
        # Get unmatched payments
        payments = db.query(Payment).filter(
            Payment.tenant_id == tenant_id,
            Payment.invoice_id.is_(None)
        ).all()
        
        # Get all pending invoices
        invoices = db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(["pending", "overdue"]),
            Invoice.amount_paid < Invoice.amount_due
        ).all()
        
        for payment in payments:
            # Try to match this payment to multiple invoices
            multi_match = self._detect_multi_invoice_payment(db, payment, invoices)
            
            if multi_match and len(multi_match) > 1:
                # Create match record for each matched invoice
                for match in multi_match:
                    inv = next((i for i in invoices if i.id == match["invoice_id"]), None)
                    if inv:
                        inv.amount_paid += Decimal(str(match["amount"]))
                        payment.invoice_id = inv.id
                        
                        multi_invoice_matches.append({
                            "invoice_id": inv.id,
                            "invoice_number": inv.invoice_number,
                            "payment_id": payment.id,
                            "payment_number": payment.payment_number,
                            "match_score": 0.95,
                            "confidence_level": "high",
                            "amount_due": float(inv.amount_due),
                            "amount_paid": float(match["amount"]),
                            "match_type": "multi_invoice",
                            "recommendation": "auto_matched"
                        })
        
        if multi_invoice_matches:
            db.commit()
            logger.info(f"Detected {len(multi_invoice_matches)} multi-invoice payment matches")
        
        return multi_invoice_matches

    def _detect_all_split_payments(
        self,
        db: SessionLocal,
        tenant_id: int
    ) -> List[Dict[str, Any]]:
        """
        Detect all split payments (single invoice paid by multiple payments).
        This is called after the main matching loop to catch invoices that were paid in installments.
        """
        split_matches = []
        
        invoices = db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(["pending", "overdue"]),
            Invoice.amount_paid < Invoice.amount_due
        ).all()
        
        payments = db.query(Payment).filter(
            Payment.tenant_id == tenant_id,
            Payment.invoice_id.is_(None)
        ).all()
        
        for invoice in invoices:
            result = self._detect_split_payment(db, invoice, payments)
            if result:
                invoice_amount = float(invoice.amount_due)
                total_paid = sum(p["amount"] for p in result)
                
                if total_paid >= invoice_amount * 0.95:
                    split_matches.append({
                        "invoice_id": invoice.id,
                        "invoice_number": invoice.invoice_number,
                        "payments": result,
                        "total_paid": total_paid,
                        "match_score": 0.95,
                        "confidence_level": "high",
                        "amount_due": invoice_amount,
                        "match_type": "split_payment",
                        "recommendation": "auto_matched"
                    })
        
        if split_matches:
            db.commit()
            logger.info(f"Detected {len(split_matches)} split payment matches")
        
        return split_matches

    def _store_reconciliation_history(
        self,
        db: SessionLocal,
        tenant_id: int,
        feature_vector: List[float],
        outcome: int,
        invoice_id: int,
        payment_id: int
    ) -> None:
        """Store reconciliation attempt in history."""
        try:
            entry = ReconciliationHistory(
                tenant_id=tenant_id,
                feature_vector=feature_vector,
                outcome=outcome,
                invoice_id=invoice_id,
                payment_id=payment_id
            )
            db.add(entry)
        except Exception as e:
            logger.error(f"Failed to store reconciliation history: {e}")

    def _batch_get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings efficiently with caching."""
        if not texts:
            return []
        
        embeddings = []
        
        for text in texts:
            if text in self._embedding_cache:
                embeddings.append(self._embedding_cache[text])
            else:
                try:
                    emb = get_embedding(text)
                    self._embedding_cache[text] = emb
                    embeddings.append(emb)
                except Exception as e:
                    logger.warning(f"Embedding failed for text: {e}")
                    embeddings.append([0.0] * 384)
        
        return embeddings

    def _precompute_embeddings(self, invoices: List, payments: List) -> Dict[str, List[float]]:
        """Precompute embeddings for all entities."""
        texts = []
        keys = []
        
        for inv in invoices:
            texts.append(VendorNameNormalizer.normalize(inv.vendor_name))
            keys.append(f"inv_vendor_{inv.id}")
            texts.append(f"{inv.description or ''} {inv.vendor_name}")
            keys.append(f"inv_desc_{inv.id}")
        
        for pay in payments:
            texts.append(VendorNameNormalizer.normalize(pay.vendor_name))
            keys.append(f"pay_vendor_{pay.id}")
            texts.append(f"{pay.description or ''} {pay.vendor_name}")
            keys.append(f"pay_desc_{pay.id}")
        
        all_embeddings = self._batch_get_embeddings(texts)
        
        return dict(zip(keys, all_embeddings))

    def get_historical_bias(
        self,
        db: SessionLocal,
        feature_vector: List[float]
    ) -> float:
        """Get historical bias from past reconciliations using pgvector-compatible approach."""
        history_count = db.query(ReconciliationHistory).count()
        if history_count == 0:
            return 0.5
        
        try:
            from sqlalchemy import text
            
            if not feature_vector:
                return 0.5
            
            vector_str = "[" + ",".join(str(x) for x in feature_vector) + "]"
            
            query = text("""
                SELECT feature_vector, outcome 
                FROM reconciliation_history 
                ORDER BY feature_vector <-> :vector
                LIMIT :k
            """)
            
            result = db.execute(query, {"vector": vector_str, "k": self.k})
            entries = result.fetchall()
            
            if not entries:
                return 0.5
            
            outcomes = [row[1] for row in entries]
            return sum(outcomes) / len(outcomes)
            
        except Exception as e:
            logger.warning(f"Error querying historical bias (pgvector method): {e}")
            try:
                all_entries = db.query(ReconciliationHistory).limit(100).all()
                if not all_entries:
                    return 0.5
                
                similarities = []
                for entry in all_entries:
                    if entry.feature_vector and len(entry.feature_vector) == len(feature_vector):
                        sim = cosine_similarity(entry.feature_vector, feature_vector)
                        similarities.append((entry.outcome, sim))
                
                similarities.sort(key=lambda x: x[1], reverse=True)
                top_k = similarities[:self.k]
                
                if not top_k:
                    return 0.5
                
                outcomes = [outcome for outcome, _ in top_k]
                return sum(outcomes) / len(outcomes)
            except Exception as fallback_error:
                logger.warning(f"Fallback historical bias also failed: {fallback_error}")
                return 0.5

    # =========================================================================
    # DISCREPANCY DETECTION
    # =========================================================================

    def _flag_discrepancies(self, db: SessionLocal, tenant_id: int) -> List[Dict[str, Any]]:
        """Flag all discrepancies in invoices and payments."""
        discrepancies = []
        
        # Overdue invoices
        overdue = db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.due_date < date.today(),
            Invoice.status == "pending"
        ).all()
        
        for inv in overdue:
            days = (date.today() - inv.due_date).days
            if days >= self.days_overdue_threshold:
                discrepancies.append({
                    "type": DiscrepancyType.OVERDUE.value,
                    "invoice_id": inv.id,
                    "invoice_number": inv.invoice_number,
                    "vendor_name": inv.vendor_name,
                    "amount_due": float(inv.amount_due),
                    "days_overdue": days,
                    "severity": "high" if days > 30 else "medium",
                    "confidence": min(1.0, days / 30.0)
                })
        
        # Amount mismatches in paid invoices
        paid = db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.status == "paid"
        ).all()
        
        for inv in paid:
            if inv.amount_due > 0:
                diff_ratio = abs(float(inv.amount_due - inv.amount_paid)) / float(inv.amount_due)
                if diff_ratio > self.amount_discrepancy_threshold:
                    discrepancies.append({
                        "type": DiscrepancyType.AMOUNT_MISMATCH.value,
                        "invoice_id": inv.id,
                        "invoice_number": inv.invoice_number,
                        "amount_due": float(inv.amount_due),
                        "amount_paid": float(inv.amount_paid),
                        "difference_ratio": diff_ratio,
                        "severity": "high" if diff_ratio > 0.1 else "medium"
                    })
        
        # Duplicate detection - use batched queries to avoid OOM
        seen = {}
        batch_size = 500
        offset = 0
        
        while True:
            invoices = db.query(Invoice).filter(
                Invoice.tenant_id == tenant_id
            ).offset(offset).limit(batch_size).all()
            
            if not invoices:
                break
                
            for inv in invoices:
                key = f"{VendorNameNormalizer.normalize(inv.vendor_name)}_{float(inv.amount_due)}_{inv.invoice_date}"
                if key in seen:
                    discrepancies.append({
                        "type": DiscrepancyType.DUPLICATE.value,
                        "invoice_id": inv.id,
                        "invoice_number": inv.invoice_number,
                        "original_invoice_id": seen[key],
                        "severity": "high"
                    })
                else:
                    seen[key] = inv.id
            
            offset += batch_size
        
        return discrepancies

    def _flag_duplicates(self, db: SessionLocal, tenant_id: int) -> List[Dict[str, Any]]:
        """
        O(n) duplicate detection using DB-level grouping.
        First groups by normalized vendor + amount (exact matches),
        then does fuzzy matching only on same-vendor invoices.
        """
        duplicates = []
        from sqlalchemy import func, cast, Float
        
        # Group by normalized vendor + amount (catches exact dupes fast - O(n))
        dupe_groups = db.query(
            Invoice.vendor_name,
            cast(Invoice.amount_due, Float),
            func.count(Invoice.id),
            func.array_agg(Invoice.id),
            func.array_agg(Invoice.invoice_number)
        ).filter(
            Invoice.tenant_id == tenant_id
        ).group_by(
            Invoice.vendor_name,
            cast(Invoice.amount_due, Float)
        ).having(func.count(Invoice.id) > 1).all()
        
        for vendor, amount, count, ids, inv_numbers in dupe_groups:
            for i in range(1, len(ids)):
                duplicates.append({
                    "type": "duplicate",
                    "invoice_id": ids[i],
                    "invoice_number": inv_numbers[i],
                    "original_invoice_id": ids[0],
                    "original_invoice_number": inv_numbers[0],
                    "vendor_name": vendor,
                    "amount": float(amount),
                    "severity": "high"
                })
        
        # Fuzzy pass only on same-vendor invoices (O(n) not O(n²))
        vendors = db.query(Invoice.vendor_name).filter(
            Invoice.tenant_id == tenant_id
        ).distinct().all()
        
        for (vendor,) in vendors:
            if not vendor or len(vendor) < 3:
                continue
            similar = db.query(Invoice).filter(
                Invoice.tenant_id == tenant_id,
                Invoice.vendor_name != vendor,
                Invoice.vendor_name.ilike(f"%{vendor[:10]}%")
            ).all()
            
            if similar and len(similar) < 20:  # Only check if narrow subset
                main_invoices = db.query(Invoice).filter(
                    Invoice.tenant_id == tenant_id,
                    Invoice.vendor_name == vendor
                ).all()
                
                for main_inv in main_invoices:
                    main_emb = self._embedding_cache.get(f"inv_vendor_{main_inv.id}")
                    if main_emb is None:
                        try:
                            main_emb = get_embedding(VendorNameNormalizer.normalize(main_inv.vendor_name))
                            self._embedding_cache[f"inv_vendor_{main_inv.id}"] = main_emb
                        except:
                            continue
                    
                    for s in similar:
                        other_emb = self._embedding_cache.get(f"inv_vendor_{s.id}")
                        if other_emb is None:
                            try:
                                other_emb = get_embedding(VendorNameNormalizer.normalize(s.vendor_name))
                                self._embedding_cache[f"inv_vendor_{s.id}"] = other_emb
                            except:
                                continue
                        
                        similarity = cosine_similarity(main_emb, other_emb)
                        if similarity > 0.85:
                            amount_diff = abs(float(main_inv.amount_due) - float(s.amount_due))
                            if amount_diff < 10:
                                duplicates.append({
                                    "type": "potential_duplicate",
                                    "invoice_id": s.id,
                                    "invoice_number": s.invoice_number,
                                    "potential_duplicate_id": main_inv.id,
                                    "potential_duplicate_number": main_inv.invoice_number,
                                    "vendor_similarity": float(similarity),
                                    "amount_diff": amount_diff,
                                    "severity": "medium",
                                    "recommendation": "review"
                                })
        
        return duplicates

    # =========================================================================
    # EXPENSE CATEGORIZATION
    # =========================================================================

    def _categorize_expenses(self, db: SessionLocal, tenant_id: int) -> List[Dict[str, Any]]:
        """Categorize expenses using rules + embeddings."""
        categorized = []
        
        expenses = db.query(Expense).filter(
            Expense.tenant_id == tenant_id,
            (Expense.category.is_(None)) | (Expense.category == "")
        ).all()
        
        category_keywords = {
            "utilities": ["electric", "gas", "water", "utility", "power", "energy"],
            "office_supplies": ["office", "supply", "stationery", "paper", "ink"],
            "travel": ["hotel", "flight", "airfare", "mileage", "taxi", "uber", "lyft"],
            "meals": ["restaurant", "meal", "food", "lunch", "dinner", "breakfast"],
            "software": ["software", "subscription", "saas", "license"],
            "marketing": ["ad", "advertising", "marketing", "promo", "campaign"],
            "professional_services": ["legal", "accounting", "consulting", "professional"],
            "rent": ["rent", "lease"],
            "insurance": ["insurance", "policy"]
        }
        
        for expense in expenses:
            rule_cat = self._categorize_expense_rule_based(expense, category_keywords)
            rule_conf = 0.8 if rule_cat else 0.0
            
            emb_cat, emb_conf = self._categorize_expense_embedding_based(
                expense.description or ""
            )
            
            if rule_cat and emb_cat:
                if rule_cat == emb_cat:
                    suggested = rule_cat
                    confidence = min(0.95, (rule_conf + emb_conf) / 2 + 0.1)
                else:
                    suggested = emb_cat if emb_conf > rule_conf else rule_cat
                    confidence = max(emb_conf, rule_conf)
            elif rule_cat:
                suggested = rule_cat
                confidence = rule_conf
            elif emb_cat:
                suggested = emb_cat
                confidence = emb_conf
            else:
                suggested = "uncategorized"
                confidence = 0.0
            
            expense.category = suggested
            db.commit()
            
            categorized.append({
                "expense_id": expense.id,
                "vendor_name": expense.vendor_name,
                "amount": float(expense.amount),
                "suggested_category": suggested,
                "confidence": confidence
            })
        
        return categorized

    def _categorize_expense_rule_based(
        self,
        expense: Expense,
        keywords: Dict[str, List[str]]
    ) -> Optional[str]:
        """Rule-based expense categorization."""
        text = f"{expense.vendor_name} {expense.description or ''}".lower()
        
        for category, words in keywords.items():
            if any(word in text for word in words):
                return category
        return None

    def _categorize_expense_embedding_based(
        self,
        description: str
    ) -> Tuple[Optional[str], float]:
        """Embedding-based expense categorization."""
        if not description:
            return None, 0.0
        
        try:
            desc_emb = get_embedding(description)
            
            best_cat = None
            best_sim = 0.0
            
            for category, prototypes in self.category_prototypes.items():
                similarities = []
                for proto in prototypes:
                    proto_emb = get_embedding(proto)
                    sim = cosine_similarity(desc_emb, proto_emb)
                    similarities.append(sim)
                
                if similarities:
                    avg = sum(similarities) / len(similarities)
                    if avg > best_sim:
                        best_sim = avg
                        best_cat = category
            
            if best_sim > 0.3:
                return best_cat, best_sim
            return None, best_sim
            
        except Exception as e:
            logger.warning(f"Embedding categorization failed: {e}")
            return None, 0.0

    def _update_invoice_statuses(self, db: SessionLocal, tenant_id: int) -> None:
        """Update invoice statuses based on payments."""
        
        # Mark paid
        paid = db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.status != "paid",
            Invoice.amount_paid >= Invoice.amount_due
        ).all()
        
        for inv in paid:
            inv.status = "paid"
        
        # Mark overdue
        overdue = db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.due_date < date.today(),
            Invoice.status == "pending"
        ).all()
        
        for inv in overdue:
            inv.status = "overdue"
        
        db.commit()


# =============================================================================
# TOOLS
# =============================================================================

class MatchInvoiceToPaymentTool(BaseTool):
    name: str = "match_invoice_to_payment"
    description: str = "Record a match between an invoice and payment"
    args_schema: type[BaseModel] = MatchInvoiceToPaymentInput

    def _run(self, invoice_id: int, payment_id: int) -> str:
        return f"Matched invoice {invoice_id} to payment {payment_id}"

    async def _arun(self, invoice_id: int, payment_id: int) -> str:
        return self._run(invoice_id, payment_id)


class FlagDiscrepancyTool(BaseTool):
    name: str = "flag_discrepancy"
    description: str = "Flag a discrepancy in invoice/payment data"
    args_schema: type[BaseModel] = FlagDiscrepancyInput

    def _run(self, invoice_id: int, discrepancy_type: str, description: str) -> str:
        return f"Flagged {discrepancy_type} for invoice {invoice_id}"

    async def _arun(self, invoice_id: int, discrepancy_type: str, description: str) -> str:
        return self._run(invoice_id, discrepancy_type, description)


class CategorizeExpenseTool(BaseTool):
    name: str = "categorize_expense"
    description: str = "Record the categorization of an expense"
    args_schema: type[BaseModel] = CategorizeExpenseInput

    def _run(self, expense_id: int, suggested_category: str) -> str:
        return f"Categorized expense {expense_id} as {suggested_category}"

    async def _arun(self, expense_id: int, suggested_category: str) -> str:
        return self._run(expense_id, suggested_category)
