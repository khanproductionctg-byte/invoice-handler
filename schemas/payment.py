from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import date
from decimal import Decimal
from pydantic import ConfigDict

class PaymentBase(BaseModel):
    payment_number: str = Field(..., min_length=1)
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    payment_date: date
    vendor_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    invoice_id: Optional[int] = None  # Reference to invoice if applicable
    source: str = Field(..., min_length=1)  # plaid, manual, etc.
    source_id: Optional[str] = None

    @field_validator('currency')
    @classmethod
    def currency_must_be_three_chars(cls, v):
        if len(v) != 3 or not v.isalpha():
            raise ValueError('Currency must be a 3-letter code (e.g., USD)')
        return v.upper()

class PaymentCreate(PaymentBase):
    pass

class PaymentUpdate(BaseModel):
    payment_number: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    payment_date: Optional[date] = None
    vendor_name: Optional[str] = None
    description: Optional[str] = None
    invoice_id: Optional[int] = None
    source: Optional[str] = None
    source_id: Optional[str] = None

class PaymentInDBBase(PaymentBase):
    id: int
    tenant_id: int
    created_at: date
    updated_at: date

    model_config = ConfigDict(from_attributes=True)

class PaymentInDB(PaymentInDBBase):
    pass

class Payment(PaymentInDBBase):
    pass