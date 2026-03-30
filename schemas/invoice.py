from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List
from datetime import date, datetime
from decimal import Decimal
from pydantic import ConfigDict
import re

class InvoiceBase(BaseModel):
    invoice_number: str = Field(..., min_length=1)
    vendor_name: str = Field(..., min_length=1)
    vendor_id: Optional[str] = None
    amount_due: Decimal = Field(..., gt=0)
    amount_paid: Decimal = Field(default=0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    invoice_date: date
    due_date: date
    status: Optional[str] = Field(default="pending")
    description: Optional[str] = None
    line_items: Optional[List[dict]] = None  # Will store as JSON
    source: str = Field(..., min_length=1)  # gmail, drive, quickbooks, xero, plaid
    source_id: Optional[str] = None

    @field_validator('currency')
    @classmethod
    def currency_must_be_three_chars(cls, v):
        if len(v) != 3 or not v.isalpha():
            raise ValueError('Currency must be a 3-letter code (e.g., USD)')
        return v.upper()

    @field_validator('due_date')
    @classmethod
    def due_date_must_be_after_invoice_date(cls, v, info):
        if 'invoice_date' in info.data and v < info.data['invoice_date']:
            raise ValueError('Due date must be after invoice date')
        return v


class InvoiceValidation:
    """Validation mixin for invoice data."""
    
    PROMPT_INJECTION_PATTERN = re.compile(
        r'ignore|system:|assistant:|<\|im_start\|>|<\|im_end\|>',
        re.IGNORECASE
    )
    
    @classmethod
    def validate_invoice_amount(cls, amount_due: Decimal) -> Decimal:
        if amount_due <= 0:
            raise ValueError('amount_due must be greater than 0')
        if amount_due > 10_000_000:
            raise ValueError('amount_due cannot exceed 10,000,000')
        return amount_due
    
    @classmethod
    def validate_invoice_date(cls, due_date: date) -> date:
        from datetime import timedelta
        today = date.today()
        one_year_ago = today - timedelta(days=365)
        five_years_future = today + timedelta(days=365 * 5)
        
        if due_date < one_year_ago:
            raise ValueError('due_date cannot be more than 1 year in the past')
        if due_date > five_years_future:
            raise ValueError('due_date cannot be more than 5 years in the future')
        return due_date
    
    @classmethod
    def sanitize_invoice_number(cls, invoice_number: str) -> str:
        if cls.PROMPT_INJECTION_PATTERN.search(invoice_number):
            raise ValueError('invoice_number contains invalid characters')
        return invoice_number.strip()

class InvoiceCreate(InvoiceBase):
    pass

class InvoiceUpdate(BaseModel):
    invoice_number: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_id: Optional[str] = None
    amount_due: Optional[Decimal] = None
    amount_paid: Optional[Decimal] = None
    currency: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    status: Optional[str] = None
    description: Optional[str] = None
    line_items: Optional[List[dict]] = None
    source: Optional[str] = None
    source_id: Optional[str] = None

class InvoiceInDBBase(InvoiceBase):
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class InvoiceInDB(InvoiceInDBBase):
    pass

class Invoice(InvoiceInDBBase):
    pass