from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional
from datetime import date, datetime
from decimal import Decimal

class ExpenseBase(BaseModel):
    vendor_name: str = Field(..., min_length=1)
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    expense_date: date
    category: Optional[str] = None
    description: Optional[str] = None
    receipt_url: Optional[str] = None
    source: str = Field(..., min_length=1)  # gmail, drive, quickbooks, xero, plaid
    source_id: Optional[str] = None

    @field_validator('currency')
    @classmethod
    def currency_must_be_three_chars(cls, v):
        if len(v) != 3 or not v.isalpha():
            raise ValueError('Currency must be a 3-letter code (e.g., USD)')
        return v.upper()

class ExpenseCreate(ExpenseBase):
    pass

class ExpenseUpdate(BaseModel):
    vendor_name: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    expense_date: Optional[date] = None
    category: Optional[str] = None
    description: Optional[str] = None
    receipt_url: Optional[str] = None
    source: Optional[str] = None
    source_id: Optional[str] = None

class ExpenseInDBBase(ExpenseBase):
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ExpenseInDB(ExpenseInDBBase):
    pass

class Expense(ExpenseInDBBase):
    pass