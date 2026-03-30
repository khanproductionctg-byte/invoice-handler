"""
Lemon Squeezy billing API routes.
Subscription management, checkout, customer portal
"""
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db.database import get_db
from db import models
from middleware import get_current_tenant
from services.lemon_squeezy import lemon_squeezy_service
from config.plan_limits import get_plan_limits, get_lemon_variant_id

router = APIRouter(prefix="/billing", tags=["billing"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


@router.get("/subscription")
async def get_subscription(
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Get current subscription info."""
    return lemon_squeezy_service.get_subscription_info(tenant)


@router.get("/plans")
async def get_available_plans():
    """Get available subscription plans."""
    plans = []
    for plan_key, plan_data in get_plan_limits("pro").items():
        if plan_key in ["name", "description", "price_monthly", "price_yearly"]:
            continue
    
    # Return structured plan info
    return [
        {
            "id": "free",
            "name": "Free",
            "description": "Perfect for getting started",
            "price_monthly": 0,
            "price_yearly": 0,
            "features": [
                "25 invoices/month",
                "10 emails/month",
                "Gmail integration",
                "Basic reports"
            ]
        },
        {
            "id": "pro",
            "name": "Pro",
            "description": "For growing businesses",
            "price_monthly": 29,
            "price_yearly": 290,
            "features": [
                "500 invoices/month",
                "200 emails/month",
                "50 SMS/month",
                "All integrations",
                "API access",
                "Priority support"
            ]
        },
        {
            "id": "enterprise",
            "name": "Enterprise",
            "description": "For large organizations",
            "price_monthly": 99,
            "price_yearly": 990,
            "features": [
                "Unlimited invoices",
                "Unlimited emails",
                "Unlimited SMS",
                "All integrations",
                "API access",
                "Dedicated support",
                "Custom reporting"
            ]
        }
    ]


@router.post("/upgrade")
async def upgrade_plan(
    plan: str,
    billing_cycle: str = "monthly",
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Create checkout session for plan upgrade."""
    if plan not in ["pro", "enterprise"]:
        raise HTTPException(400, "Invalid plan. Choose 'pro' or 'enterprise'")
    
    if billing_cycle not in ["monthly", "yearly"]:
        raise HTTPException(400, "Invalid billing cycle. Choose 'monthly' or 'yearly'")
    
    # Get variant ID
    variant_id = get_lemon_variant_id(plan, billing_cycle)
    if not variant_id:
        raise HTTPException(400, "Plan not available")
    
    # Get user email
    tenant_user = db.query(models.TenantUser).filter(
        models.TenantUser.tenant_id == tenant.id,
        models.TenantUser.role == "owner"
    ).first()
    
    if not tenant_user:
        raise HTTPException(400, "No owner found for tenant")
    
    user = db.query(models.User).filter(models.User.id == tenant_user.user_id).first()
    user_email = user.email if user else "user@example.com"
    user_name = user.full_name or user_email.split("@")[0]
    
    # Build URLs
    success_url = f"{FRONTEND_URL}/settings/billing?success=true&plan={plan}"
    cancel_url = f"{FRONTEND_URL}/settings/billing?canceled=true"
    
    try:
        checkout_url = await lemon_squeezy_service.create_checkout(
            variant_id=variant_id,
            user_email=user_email,
            user_name=user_name,
            tenant_id=tenant.id,
            success_url=success_url,
            cancel_url=cancel_url
        )
        
        return {"url": checkout_url}
    except Exception as e:
        raise HTTPException(500, f"Failed to create checkout: {str(e)}")


@router.post("/cancel")
async def cancel_subscription(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Cancel current subscription."""
    if not tenant.lemon_subscription_id:
        raise HTTPException(400, "No active subscription")
    
    try:
        await lemon_squeezy_service.cancel_subscription(tenant.lemon_subscription_id)
        
        tenant.subscription_status = "canceled"
        tenant.plan = "free"
        db.commit()
        
        return {"status": "canceled", "message": "Subscription will expire at the end of the billing period"}
    except Exception as e:
        raise HTTPException(500, f"Failed to cancel: {str(e)}")


@router.get("/portal")
async def open_customer_portal(
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Open customer portal for subscription management."""
    return_url = f"{FRONTEND_URL}/settings/billing"
    
    # Since Lemon Squeezy doesn't have a portal, return the billing page URL
    return {"url": return_url}


@router.post("/webhook")
async def lemon_squeezy_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """Handle Lemon Squeezy webhooks."""
    payload = await request.body()
    signature = request.headers.get("x-signature", "")
    
    try:
        return lemon_squeezy_service.handle_webhook(payload, signature, db)
    except ValueError as e:
        raise HTTPException(401, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/invoice/{invoice_id}")
async def get_invoice(
    invoice_id: str,
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Get invoice details from Lemon Squeezy."""
    if not tenant.lemon_subscription_id:
        raise HTTPException(400, "No subscription found")
    
    try:
        # This would call Lemon Squeezy API to get invoice
        # For now, return placeholder
        return {
            "id": invoice_id,
            "status": "paid",
            "amount": 2900,
            "currency": "usd"
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/history")
async def get_billing_history(
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Get billing history."""
    # This would fetch from Lemon Squeezy API
    # For now, return current subscription info
    return {
        "subscription": lemon_squeezy_service.get_subscription_info(tenant),
        "invoices": []
    }
