from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from decimal import Decimal

class ReportBase(BaseModel):
    report_type: str = Field(..., description="Type of report: weekly, monthly, custom")
    title: str = Field(..., min_length=1)
    content: Dict[str, Any] = Field(..., description="Report content in structured format")

class ReportCreate(ReportBase):
    pass

class ReportUpdate(BaseModel):
    report_type: Optional[str] = None
    title: Optional[str] = None
    content: Optional[Dict[str, Any]] = None

class ReportInDBBase(ReportBase):
    id: int
    tenant_id: int
    generated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ReportInDB(ReportInDBBase):
    pass

class Report(ReportInDBBase):
    pass

# Additional schemas for report data
class OverdueSummary(BaseModel):
    total_overdue: Decimal = Field(..., ge=0)
    overdue_count: int = Field(..., ge=0)
    overdue_by_client: List[Dict[str, Any]] = Field(default_factory=list)

class ExpenseSummary(BaseModel):
    total_expenses: Decimal = Field(..., ge=0)
    expense_count: int = Field(..., ge=0)
    expenses_by_category: List[Dict[str, Any]] = Field(default_factory=list)

class InvoiceSummary(BaseModel):
    total_invoiced: Decimal = Field(..., ge=0)
    invoiced_count: int = Field(..., ge=0)
    paid_count: int = Field(..., ge=0)
    pending_count: int = Field(..., ge=0)
    overdue_count: int = Field(..., ge=0)

class FinancialReport(BaseModel):
    period_start: date
    period_end: date
    invoice_summary: InvoiceSummary
    expense_summary: ExpenseSummary
    overdue_summary: OverdueSummary
    generated_at: datetime = Field(default_factory=datetime.utcnow)