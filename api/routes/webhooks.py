"""
Webhook handlers for real-time external updates.
Supports: Clerk, Lemon Squeezy, Plaid, QuickBooks, Xero webhooks.
"""
import logging
import hmac
import hashlib
import json
import os
from typing import Dict, Any, Callable, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Invoice, Payment, Expense, User, Tenant
from schemas.webhook import validate_webhook_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Webhook secrets configuration
WEBHOOK_SECRETS = {
    "clerk": os.getenv("CLERK_WEBHOOK_SECRET"),
    "lemonsqueezy": os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET"),
    "plaid": os.getenv("PLAID_WEBHOOK_SECRET"),
    "quickbooks": os.getenv("QUICKBOOKS_WEBHOOK_SECRET"),
    "stripe": os.getenv("STRIPE_WEBHOOK_SECRET"),
    "xero": os.getenv("XERO_WEBHOOK_SECRET"),
}


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str
) -> bool:
    """Verify webhook signature using HMAC-SHA256."""
    if not signature or not secret:
        return False
    
    expected_sig = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_sig)


def get_webhook_secret(source: str) -> Optional[str]:
    """Get webhook secret for a source."""
    secret_map = {
        "clerk": os.getenv("CLERK_WEBHOOK_SECRET"),
        "lemonsqueezy": os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET"),
        "plaid": os.getenv("PLAID_WEBHOOK_SECRET"),
        "quickbooks": os.getenv("QUICKBOOKS_WEBHOOK_SECRET"),
        "stripe": os.getenv("STRIPE_WEBHOOK_SECRET"),
        "xero": os.getenv("XERO_WEBHOOK_SECRET"),
    }
    return secret_map.get(source)


# =============================================================================
# CLERK WEBHOOKS
# =============================================================================

@router.post("/clerk")
async def clerk_webhook(request: Request):
    """
    Handle Clerk webhooks for user management.
    
    Supported events:
    - user.created
    - user.updated
    - user.deleted
    - session.created
    - session.ended
    """
    payload = await request.body()
    
    # Verify signature
    signature = request.headers.get("Clerk-Signature") or request.headers.get("x-clerk-signature")
    secret = get_webhook_secret("clerk")
    
    if not secret:
        import logging
        logging.getLogger(__name__).error("CLERK_WEBHOOK_SECRET is not configured. Rejecting all Clerk webhooks.")
        raise HTTPException(
            status_code=500,
            detail="Webhook secret not configured. Webhooks are disabled for security."
        )
    
    if not signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    
    expected_sig = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(signature, expected_sig):
        import logging
        logging.getLogger(__name__).warning(f"Clerk webhook signature mismatch from {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    event = json.loads(payload)
    
    # Validate payload
    try:
        validated = validate_webhook_payload("clerk", event)
    except Exception as e:
        logger.warning(f"Clerk webhook validation failed: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    
    event_type = validated.type
    data = validated.data.model_dump()
    
    db = next(get_db())
    
    try:
        if event_type == "user.created":
            await _handle_clerk_user_created(db, data)
        elif event_type == "user.updated":
            await _handle_clerk_user_updated(db, data)
        elif event_type == "user.deleted":
            await _handle_clerk_user_deleted(db, data)
        else:
            logger.info(f"Unhandled Clerk event: {event_type}")
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Clerk webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


async def _handle_clerk_user_created(db: Session, data: Dict):
    """Handle new user created in Clerk."""
    clerk_id = data.get("id")
    email = data.get("email_addresses", [{}])[0].get("email_address", "")
    first_name = data.get("first_name", "")
    last_name = data.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip() or None
    
    # Check if user exists
    user = db.query(User).filter(User.clerk_id == clerk_id).first()
    
    if not user:
        # Check by email
        user = db.query(User).filter(User.email == email).first()
        
        if user:
            # Link Clerk ID
            user.clerk_id = clerk_id
        else:
            # Create new user
            user = User(
                email=email,
                full_name=full_name,
                clerk_id=clerk_id,
                is_active=True
            )
            db.add(user)
        
        db.commit()
        logger.info(f"Clerk user created: {clerk_id} - {email}")
    
    # Create default tenant for new user
    from utils.clerk_auth import _create_default_tenant
    _create_default_tenant(db, user, email)


async def _handle_clerk_user_updated(db: Session, data: Dict):
    """Handle user updated in Clerk."""
    clerk_id = data.get("id")
    email = data.get("email_addresses", [{}])[0].get("email_address", "")
    first_name = data.get("first_name", "")
    last_name = data.get("last_name", "")
    
    user = db.query(User).filter(User.clerk_id == clerk_id).first()
    
    if user:
        user.email = email
        user.full_name = f"{first_name} {last_name}".strip()
        db.commit()
        logger.info(f"Clerk user updated: {clerk_id}")


async def _handle_clerk_user_deleted(db: Session, data: Dict):
    """Handle user deleted in Clerk."""
    clerk_id = data.get("id")
    
    user = db.query(User).filter(User.clerk_id == clerk_id).first()
    
    if user:
        user.is_active = False
        db.commit()
        logger.info(f"Clerk user deactivated: {clerk_id}")


# =============================================================================
# LEMON SQUEEZY WEBHOOKS
# =============================================================================

@router.post("/lemonsqueezy")
async def lemonsqueezy_webhook(
    request: Request,
    lemonsqueezy_signature: Optional[str] = Header(None, alias="x-signature")
):
    """
    Handle Lemon Squeezy webhooks for subscription management.
    
    Supported events:
    - subscription_created
    - subscription_updated
    - subscription_cancelled
    - subscription_expired
    - subscription_payment_succeeded
    - subscription_payment_failed
    """
    payload = await request.body()
    
    # Verify signature - Lemon Squeezy requires secret to be configured
    secret = get_webhook_secret("lemonsqueezy")
    if not secret:
        logger.error("LEMONSQUEEZY_WEBHOOK_SECRET not configured. Rejecting webhook.")
        raise HTTPException(
            status_code=500,
            detail="Webhook secret not configured"
        )
    
    if not lemonsqueezy_signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    
    expected_sig = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(lemonsqueezy_signature, expected_sig):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    event = json.loads(payload)
    
    # Validate payload
    try:
        validated = validate_webhook_payload("lemonsqueezy", event)
    except Exception as e:
        logger.warning(f"Lemon Squeezy webhook validation failed: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    
    event_type = validated.meta.event_name
    custom_data = validated.meta.custom_data
    tenant_id = custom_data.get("tenant_id")
    
    if not tenant_id:
        logger.warning("Lemon Squeezy webhook missing tenant_id")
        return {"status": "ignored"}
    
    db = next(get_db())
    
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        
        if not tenant:
            logger.error(f"Tenant not found: {tenant_id}")
            return {"status": "error", "reason": "Tenant not found"}
        
        # Handle event
        if event_type == "subscription_created":
            await _handle_ls_subscription_created(db, tenant, event)
        elif event_type == "subscription_updated":
            await _handle_ls_subscription_updated(db, tenant, event)
        elif event_type == "subscription_cancelled":
            await _handle_ls_subscription_cancelled(db, tenant, event)
        elif event_type == "subscription_expired":
            await _handle_ls_subscription_expired(db, tenant, event)
        elif event_type == "subscription_payment_succeeded":
            await _handle_ls_payment_succeeded(db, tenant, event)
        elif event_type == "subscription_payment_failed":
            await _handle_ls_payment_failed(db, tenant, event)
        else:
            logger.info(f"Unhandled Lemon Squeezy event: {event_type}")
        
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Lemon Squeezy webhook error: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


async def _handle_ls_subscription_created(db: Session, tenant: Tenant, event: Dict):
    """Handle subscription created."""
    attrs = event.get("data", {}).get("attributes", {})
    
    tenant.lemon_subscription_id = str(event["data"]["id"])
    tenant.subscription_status = attrs.get("status", "active")
    
    # Determine plan from variant_id
    variant_id = str(attrs.get("variant_id", ""))
    tenant.plan = _get_plan_from_variant(variant_id)
    
    renews_at = attrs.get("renews_at")
    if renews_at:
        tenant.subscription_renews_at = datetime.fromisoformat(renews_at.replace("Z", "+00:00"))
    
    logger.info(f"Lemon Squeezy subscription created: {tenant.id} - {tenant.plan}")


async def _handle_ls_subscription_updated(db: Session, tenant: Tenant, event: Dict):
    """Handle subscription updated."""
    attrs = event.get("data", {}).get("attributes", {})
    
    tenant.subscription_status = attrs.get("status", tenant.subscription_status)
    
    # Check if plan changed
    variant_id = str(attrs.get("variant_id", ""))
    new_plan = _get_plan_from_variant(variant_id)
    
    if new_plan != tenant.plan:
        tenant.plan = new_plan
        logger.info(f"Tenant {tenant.id} plan changed to {new_plan}")
    
    renews_at = attrs.get("renews_at")
    if renews_at:
        tenant.subscription_renews_at = datetime.fromisoformat(renews_at.replace("Z", "+00:00"))


async def _handle_ls_subscription_cancelled(db: Session, tenant: Tenant, event: Dict):
    """Handle subscription cancelled."""
    tenant.subscription_status = "canceled"
    tenant.plan = "free"
    logger.info(f"Tenant {tenant.id} subscription cancelled, downgraded to free")


async def _handle_ls_subscription_expired(db: Session, tenant: Tenant, event: Dict):
    """Handle subscription expired."""
    tenant.subscription_status = "expired"
    tenant.plan = "free"
    tenant.lemon_subscription_id = None
    logger.info(f"Tenant {tenant.id} subscription expired, downgraded to free")


async def _handle_ls_payment_succeeded(db: Session, tenant: Tenant, event: Dict):
    """Handle successful payment."""
    tenant.subscription_status = "active"
    attrs = event.get("data", {}).get("attributes", {})
    renews_at = attrs.get("renews_at")
    if renews_at:
        tenant.subscription_renews_at = datetime.fromisoformat(renews_at.replace("Z", "+00:00"))
    logger.info(f"Payment succeeded for tenant {tenant.id}")


async def _handle_ls_payment_failed(db: Session, tenant: Tenant, event: Dict):
    """Handle failed payment."""
    tenant.subscription_status = "past_due"
    logger.warning(f"Payment failed for tenant {tenant.id}")


def _get_plan_from_variant(variant_id: str) -> str:
    """Map Lemon Squeezy variant ID to plan name."""
    from config.plan_limits import get_plan_from_variant
    return get_plan_from_variant(variant_id)


# =============================================================================
# STRIPE WEBHOOKS
# =============================================================================

@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None)
):
    """
    Handle Stripe webhooks for payment events.
    
    Supported events:
    - payment_intent.succeeded
    - payment_intent.payment_failed
    - invoice.paid
    - invoice.payment_failed
    """
    payload = await request.body()
    
    secret = get_webhook_secret("stripe")
    if not secret:
        logger.error("STRIPE_WEBHOOK_SECRET not configured. Rejecting webhook.")
        raise HTTPException(
            status_code=500,
            detail="Webhook secret not configured"
        )
    
    if not stripe_signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    
    if not verify_webhook_signature(payload, stripe_signature, secret):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    event = json.loads(payload)
    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})
    
    db = next(get_db())
    
    try:
        if event_type == "payment_intent.succeeded":
            await _handle_stripe_payment_succeeded(db, data)
        elif event_type == "payment_intent.payment_failed":
            await _handle_stripe_payment_failed(db, data)
        elif event_type == "invoice.paid":
            await _handle_stripe_invoice_paid(db, data)
        elif event_type == "invoice.payment_failed":
            await _handle_stripe_invoice_failed(db, data)
        else:
            logger.info(f"Unhandled Stripe event: {event_type}")
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Stripe webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


async def _handle_stripe_payment_succeeded(db: Session, data: Dict):
    """Handle successful Stripe payment."""
    amount = data.get("amount", 0) / 100
    stripe_id = data.get("id")
    logger.info(f"Stripe payment succeeded: {stripe_id}, amount: {amount}")


async def _handle_stripe_payment_failed(db: Session, data: Dict):
    """Handle failed Stripe payment."""
    stripe_id = data.get("id")
    logger.warning(f"Stripe payment failed: {stripe_id}")


async def _handle_stripe_invoice_paid(db: Session, data: Dict):
    """Handle paid Stripe invoice."""
    stripe_id = data.get("id")
    amount_paid = data.get("amount_paid", 0) / 100
    logger.info(f"Stripe invoice paid: {stripe_id}, amount: {amount_paid}")


async def _handle_stripe_invoice_failed(db: Session, data: Dict):
    """Handle failed Stripe invoice."""
    stripe_id = data.get("id")
    logger.warning(f"Stripe invoice failed: {stripe_id}")


# =============================================================================
# PLAID WEBHOOKS
# =============================================================================

@router.post("/plaid")
async def plaid_webhook(
    request: Request,
    plaid_signature: Optional[str] = Header(None, alias="x-plaid-signature")
):
    """
    Handle Plaid webhooks for transaction updates.
    """
    payload = await request.body()
    
    secret = get_webhook_secret("plaid")
    if not secret:
        logger.error("PLAID_WEBHOOK_SECRET not configured. Rejecting webhook.")
        raise HTTPException(
            status_code=500,
            detail="Webhook secret not configured"
        )
    
    if not plaid_signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    
    expected_sig = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(plaid_signature, expected_sig):
        logger.warning(f"Plaid webhook signature mismatch from {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    payload_json = json.loads(payload)
    
    webhook_type = payload_json.get("webhook_type")
    webhook_code = payload_json.get("webhook_code")
    item_id = payload_json.get("item_id")
    
    logger.info(f"Plaid webhook: {webhook_type}/{webhook_code} for item {item_id}")
    
    return {"status": "ok"}


# =============================================================================
# QUICKBOOKS WEBHOOKS
# =============================================================================

@router.post("/quickbooks")
async def quickbooks_webhook(
    request: Request,
    quickbooks_signature: Optional[str] = Header(None, alias="x-quickbooks-signature")
):
    """
    Handle QuickBooks webhooks for real-time updates.
    """
    payload = await request.body()
    
    secret = get_webhook_secret("quickbooks")
    if not secret:
        logger.error("QUICKBOOKS_WEBHOOK_SECRET not configured. Rejecting webhook.")
        raise HTTPException(
            status_code=500,
            detail="Webhook secret not configured"
        )
    
    if not quickbooks_signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    
    expected_sig = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(quickbooks_signature, expected_sig):
        logger.warning(f"QuickBooks webhook signature mismatch from {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    payload_json = json.loads(payload)
    
    notifications = payload_json.get("notifications", [])
    
    for notification in notifications:
        entity_type = notification.get("entityType")
        operation = notification.get("operation")
        entity_id = notification.get("entityId")
        
        logger.info(f"QuickBooks {operation} on {entity_type}: {entity_id}")
    
    return {"status": "ok"}


async def _handle_quickbooks_invoice_created(invoice_id: str):
    """Handle new invoice from QuickBooks."""
    logger.info(f"New QuickBooks invoice: {invoice_id}")


async def _handle_quickbooks_payment_created(payment_id: str):
    """Handle new payment from QuickBooks."""
    logger.info(f"New QuickBooks payment: {payment_id}")


# =============================================================================
# XERO WEBHOOKS
# =============================================================================

@router.post("/xero")
async def xero_webhook(
    request: Request,
    xero_tenant_id: Optional[str] = Header(None),
    xero_signature: Optional[str] = Header(None, alias="x-xero-signature")
):
    """
    Handle Xero webhooks for real-time updates.
    """
    payload = await request.body()
    
    secret = get_webhook_secret("xero")
    if not secret:
        logger.error("XERO_WEBHOOK_SECRET not configured. Rejecting webhook.")
        raise HTTPException(
            status_code=500,
            detail="Webhook secret not configured"
        )
    
    if not xero_signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    
    expected_sig = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(xero_signature, expected_sig):
        logger.warning(f"Xero webhook signature mismatch from {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    payload_json = json.loads(payload)
    
    events = payload_json.get("events", [])
    
    for event in events:
        event_type = event.get("eventType")
        resource_id = event.get("resourceId")
        
        logger.info(f"Xero event: {event_type} for {resource_id}")
    
    return {"status": "ok"}


async def _handle_xero_invoice_event(event_type: str, invoice_id: str):
    """Handle Xero invoice events."""
    if "PAID" in event_type:
        logger.info(f"Xero invoice paid: {invoice_id}")
    elif "CREATED" in event_type:
        logger.info(f"Xero invoice created: {invoice_id}")


async def _handle_xero_payment_event(event_type: str, payment_id: str):
    """Handle Xero payment events."""
    logger.info(f"Xero payment event: {event_type}, {payment_id}")


# =============================================================================
# GENERIC WEBHOOK REGISTRATION
# =============================================================================

@router.get("/endpoints")
def list_webhook_endpoints():
    """List all available webhook endpoints."""
    return {
        "endpoints": [
            {"path": "/webhooks/clerk", "description": "Clerk user events"},
            {"path": "/webhooks/lemonsqueezy", "description": "Lemon Squeezy subscription events"},
            {"path": "/webhooks/stripe", "description": "Stripe payment events"},
            {"path": "/webhooks/plaid", "description": "Plaid transaction updates"},
            {"path": "/webhooks/quickbooks", "description": "QuickBooks real-time updates"},
            {"path": "/webhooks/xero", "description": "Xero real-time updates"},
        ]
    }
