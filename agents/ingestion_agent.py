"""
IngestionAgent for fetching data from various sources.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from decimal import Decimal

from langchain_core.tools import BaseTool
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from .base_agent import BaseAgent, AgentState
from db.database import SessionLocal, get_tenant_session
from db.models import Payment, Invoice, Expense
from utils.ingestion import (
    fetch_gmail_invoices,
    fetch_drive_pdfs,
    fetch_quickbooks_invoices,
    fetch_xero_invoices,
    fetch_plaid_transactions_and_statements
)

logger = logging.getLogger(__name__)


class IngestionAgent(BaseAgent):
    """
    Agent responsible for:
    - Fetching invoices/expenses from Gmail, Google Drive, QuickBooks, Xero, Plaid
    - Storing them in the database (via the state or by direct database operations)
    """

    def __init__(self, tools: List[BaseTool]):
        """
        Initialize the IngestionAgent.

        Args:
            tools: List of ingestion tools available to this agent
        """
        super().__init__(llm=None, tools=tools, agent_name="IngestionAgent")

    def _check_invoice_exists(self, db, source: str, source_id: str, tenant_id: int) -> Optional[Invoice]:
        """Check if an invoice already exists to ensure idempotency."""
        return db.query(Invoice).filter(
            Invoice.source == source,
            Invoice.source_id == source_id,
            Invoice.tenant_id == tenant_id
        ).first()

    def _check_expense_exists(self, db, source: str, source_id: str, tenant_id: int) -> Optional[Expense]:
        """Check if an expense already exists to ensure idempotency."""
        return db.query(Expense).filter(
            Expense.source == source,
            Expense.source_id == source_id,
            Expense.tenant_id == tenant_id
        ).first()

    def _save_invoice_idempotent(self, db, invoice_data: Dict[str, Any], tenant_id: int) -> Optional[Invoice]:
        """
        Save invoice with idempotency check.
        Returns existing invoice if found, creates new one otherwise.
        """
        source = invoice_data.get("source")
        source_id = invoice_data.get("source_id")
        
        if not source or not source_id:
            logger.warning(f"Cannot check idempotency - missing source or source_id")
            return None
        
        existing = self._check_invoice_exists(db, source, source_id, tenant_id)
        if existing:
            logger.info(f"Skipping duplicate invoice: {source}:{source_id}")
            return existing
        
        invoice = Invoice(
            invoice_number=invoice_data.get("invoice_number", f"{source}_{source_id}"),
            vendor_name=invoice_data.get("vendor_name", "Unknown"),
            amount_due=Decimal(str(invoice_data.get("amount_due", 0))),
            amount_paid=Decimal(str(invoice_data.get("amount_paid", 0))),
            currency=invoice_data.get("currency", "USD"),
            invoice_date=invoice_data.get("invoice_date") or datetime.now().date(),
            due_date=invoice_data.get("due_date") or datetime.now().date(),
            status=invoice_data.get("status", "pending"),
            description=invoice_data.get("description"),
            line_items=json.dumps(invoice_data.get("line_items", [])) if invoice_data.get("line_items") else None,
            source=source,
            source_id=source_id,
            tenant_id=tenant_id
        )
        db.add(invoice)
        return invoice

    def process(self, state: AgentState) -> AgentState:
        """
        Process ingestion for a user.

        Args:
            state: Current agent state containing user_id and tenant_id

        Returns:
            Updated agent state with ingestion results
        """
        logger.info(f"IngestionAgent processing state: {state.agent_id}")
        db = None

        try:
            tenant_id = state.tenant_id
            if not tenant_id:
                raise ValueError("tenant_id is required in state")
            
            user_id = state.input_data.get("user_id")
            if not user_id:
                raise ValueError("user_id is required in input_data")

            db = get_tenant_session(tenant_id)
            ingestion_results = {}
            stats = {"created": 0, "skipped": 0, "errors": 0}

            tools_to_run = [
                ("gmail", fetch_gmail_invoices),
                ("drive", fetch_drive_pdfs),
                ("quickbooks", fetch_quickbooks_invoices),
                ("xero", fetch_xero_invoices),
                ("plaid", fetch_plaid_transactions_and_statements)
            ]

            for source_name, tool in tools_to_run:
                try:
                    logger.info(f"Running {source_name} ingestion for tenant {tenant_id}")
                    result_json = tool.invoke({"tenant_id": tenant_id, "user_id": user_id, "days_back": 30})
                    ingestion_results[source_name] = result_json
                    
                    if source_name != "plaid":
                        invoices = json.loads(result_json) if result_json and not result_json.startswith("Error") else []
                        for inv_data in invoices:
                            try:
                                saved = self._save_invoice_idempotent(db, inv_data, tenant_id)
                                if saved:
                                    stats["created"] += 1
                            except Exception as inv_err:
                                logger.warning(f"Failed to save invoice: {inv_err}")
                                stats["errors"] += 1
                    
                    logger.info(f"Completed {source_name} ingestion for user {user_id}")
                except Exception as e:
                    logger.error(f"Error in {source_name} ingestion for user {user_id}: {str(e)}")
                    ingestion_results[source_name] = f"Error: {str(e)}"
                    stats["errors"] += 1

            db.commit()

            # Convert Plaid transactions to payments with idempotency
            self._convert_plaid_to_payments(ingestion_results, tenant_id)

            state.output_data["ingestion_results"] = ingestion_results
            state.output_data["status"] = "ingestion_completed"
            state.output_data["processed_at"] = datetime.utcnow().isoformat()
            state.output_data["stats"] = stats

            logger.info(f"IngestionAgent completed for user {user_id}: {stats}")
            return state

        except Exception as e:
            logger.error(f"IngestionAgent failed: {str(e)}")
            if db:
                db.rollback()
            state.error = str(e)
            state.output_data["status"] = "failed"
            return state
        finally:
            if db:
                db.close()

    def _convert_plaid_to_payments(self, ingestion_results: Dict[str, Any], tenant_id: int) -> None:
        """Convert Plaid transactions to Payment records in the database with idempotency."""
        db = None
        try:
            plaid_data_str = ingestion_results.get("plaid", "{}")
            if not plaid_data_str or plaid_data_str.startswith("Error"):
                logger.warning("Skipping Plaid conversion due to error or no data")
                return
            
            # Parse the JSON string into a dict and extract transactions
            plaid_data = json.loads(plaid_data_str) if isinstance(plaid_data_str, str) else plaid_data_str
            transactions = plaid_data.get("transactions", []) if plaid_data else []
            
            if not transactions:
                logger.info("No Plaid transactions to convert")
                return
            
            db = get_tenant_session(tenant_id)
            payments_created = 0
            
            for txn in transactions:
                txn_id = txn.get("transaction_id")
                if not txn_id:
                    continue
                
                existing = db.query(Payment).filter(
                    Payment.source == "plaid",
                    Payment.source_id == txn_id,
                    Payment.tenant_id == tenant_id
                ).first()
                
                if existing:
                    logger.debug(f"Skipping duplicate Plaid payment: {txn_id}")
                    continue
                
                amount = abs(txn.get("amount", 0))
                if amount == 0:
                    continue
                
                payment = Payment(
                    payment_number=f"PLAID_{txn_id}",
                    amount=Decimal(str(amount)),
                    currency=txn.get("iso_currency_code", "USD"),
                    payment_date=datetime.strptime(txn["date"], "%Y-%m-%d").date(),
                    vendor_name=txn.get("name", "Unknown"),
                    description=txn.get("category", [{}])[0] if txn.get("category") else None,
                    source="plaid",
                    source_id=txn_id,
                    tenant_id=tenant_id
                )
                db.add(payment)
                payments_created += 1
            
            db.commit()
            
            if payments_created > 0:
                logger.info(f"Created {payments_created} payments from Plaid transactions")
                
        except Exception as e:
            logger.error(f"Failed to convert Plaid transactions to payments: {str(e)}")
            if db:
                db.rollback()
        finally:
            if db:
                db.close()
