"""
Pydantic schemas for webhook payload validation.
Ensures all incoming webhook data is validated before processing.
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime


# =============================================================================
# CLERK WEBHOOKS
# =============================================================================

class ClerkEmailAddress(BaseModel):
    email_address: str
    id: Optional[str] = None


class ClerkName(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class ClerkUserData(BaseModel):
    id: str
    email_addresses: List[ClerkEmailAddress] = Field(default_factory=list)
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class ClerkWebhookPayload(BaseModel):
    type: str
    data: ClerkUserData


# =============================================================================
# LEMON SQUEEZY WEBHOOKS
# =============================================================================

class LemonSqueezyAttributes(BaseModel):
    status: Optional[str] = None
    variant_id: Optional[str] = None
    renews_at: Optional[str] = None
    subscription_id: Optional[str] = None


class LemonSqueezyMeta(BaseModel):
    event_name: str
    custom_data: Dict[str, Any] = Field(default_factory=dict)


class LemonSqueezyData(BaseModel):
    id: str
    attributes: LemonSqueezyAttributes = Field(default_factory=LemonSqueezyAttributes)


class LemonSqueezyWebhookPayload(BaseModel):
    meta: LemonSqueezyMeta
    data: LemonSqueezyData


# =============================================================================
# STRIPE WEBHOOKS
# =============================================================================

class StripePaymentIntent(BaseModel):
    id: str
    amount: int
    currency: str
    status: str
    customer_email: Optional[str] = None


class StripeInvoice(BaseModel):
    id: str
    customer_email: Optional[str] = None
    amount_paid: int
    status: str


class StripeWebhookPayload(BaseModel):
    type: str
    data: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# PLAID WEBHOOKS
# =============================================================================

class PlaidWebhookPayload(BaseModel):
    webhook_type: str = Field(validation_alias="webhook_type")
    webhook_code: str = Field(validation_alias="webhook_code")
    item_id: str
    error: Optional[Dict[str, Any]] = None

    @field_validator('webhook_type', 'webhook_code', mode='before')
    @classmethod
    def snake_to_camel(cls, v):
        return v


# =============================================================================
# QUICKBOOKS WEBHOOKS
# =============================================================================

class QuickBooksNotification(BaseModel):
    entityType: str
    operation: str
    entityId: str


class QuickBooksWebhookPayload(BaseModel):
    notifications: List[QuickBooksNotification] = Field(default_factory=list)


# =============================================================================
# XERO WEBHOOKS
# =============================================================================

class XeroEvent(BaseModel):
    eventType: str
    resourceId: str


class XeroWebhookPayload(BaseModel):
    events: List[XeroEvent] = Field(default_factory=list)
    tenant_id: Optional[str] = None


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_webhook_payload(webhook_type: str, payload: Dict[str, Any]) -> BaseModel:
    """
    Validate webhook payload based on type.
    
    Args:
        webhook_type: Type of webhook (clerk, lemonsqueezy, stripe, plaid, quickbooks, xero)
        payload: Raw payload dictionary
        
    Returns:
        Validated Pydantic model
        
    Raises:
        ValidationError: If payload is invalid
    """
    validators = {
        "clerk": ClerkWebhookPayload,
        "lemonsqueezy": LemonSqueezyWebhookPayload,
        "stripe": StripeWebhookPayload,
        "plaid": PlaidWebhookPayload,
        "quickbooks": QuickBooksWebhookPayload,
        "xero": XeroWebhookPayload,
    }
    
    validator_class = validators.get(webhook_type)
    if not validator_class:
        raise ValueError(f"Unknown webhook type: {webhook_type}")
    
    return validator_class(**payload)
