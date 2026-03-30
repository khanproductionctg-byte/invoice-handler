from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
from typing import Optional
from datetime import datetime


class CustomerBase(BaseModel):
    email: EmailStr
    phone: Optional[str] = None
    full_name: Optional[str] = None
    company_name: Optional[str] = None
    opt_out_email: bool = False
    opt_out_sms: bool = False
    preferred_language: str = "en"


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    company_name: Optional[str] = None
    opt_out_email: Optional[bool] = None
    opt_out_sms: Optional[bool] = None
    preferred_language: Optional[str] = None


class CustomerInDBBase(CustomerBase):
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Customer(CustomerInDBBase):
    pass
