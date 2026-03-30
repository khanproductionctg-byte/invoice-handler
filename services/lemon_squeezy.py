"""
Lemon Squeezy payment service for subscriptions.
Replaces Stripe with Lemon Squeezy - better for SaaS with lower fees.
"""
import os
import hmac
import hashlib
import httpx
from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime

from db import models
from config.plan_limits import get_plan_from_variant, get_lemon_variant_id

# Lemon Squeezy configuration
LEMONSQUEEZY_API_URL = "https://api.lemonsqueezy.com/v1"
LEMONSQUEEZY_API_KEY = os.getenv("LEMONSQUEEZY_API_KEY", "")
LEMONSQUEEZY_STORE_ID = os.getenv("LEMONSQUEEZY_STORE_ID", "")
LEMONSQUEEZY_WEBHOOK_SECRET = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "")


class LemonSqueezyService:
    def __init__(self):
        self.api_url = LEMONSQUEEZY_API_URL
        self.api_key = LEMONSQUEEZY_API_KEY
        self.store_id = LEMONSQUEEZY_STORE_ID
        self.webhook_secret = LEMONSQUEEZY_WEBHOOK_SECRET
    
    def _headers(self) -> dict:
        """Get headers for Lemon Squeezy API."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }
    
    async def _make_request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make API request to Lemon Squeezy."""
        async with httpx.AsyncClient() as client:
            url = f"{self.api_url}{endpoint}"
            
            if method == "GET":
                response = await client.get(url, headers=self._headers())
            elif method == "POST":
                response = await client.post(url, json=data, headers=self._headers())
            elif method == "PATCH":
                response = await client.patch(url, json=data, headers=self._headers())
            elif method == "DELETE":
                response = await client.delete(url, headers=self._headers())
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            if response.status_code >= 400:
                raise Exception(f"Lemon Squeezy API error: {response.status_code} - {response.text}")
            
            return response.json()
    
    async def create_checkout(
        self,
        variant_id: str,
        user_email: str,
        user_name: str,
        tenant_id: int,
        success_url: str,
        cancel_url: str
    ) -> str:
        """
        Create a Lemon Squeezy checkout URL.
        """
        checkout_data = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": {
                        "email": user_email,
                        "name": user_name,
                        "custom": {
                            "tenant_id": str(tenant_id)
                        }
                    },
                    "urls": {
                        "success": success_url,
                        "cancel": cancel_url
                    }
                },
                "relationships": {
                    "store": {
                        "data": {
                            "type": "stores",
                            "id": self.store_id
                        }
                    },
                    "variant": {
                        "data": {
                            "type": "variants",
                            "id": variant_id
                        }
                    }
                }
            }
        }
        
        result = await self._make_request("POST", "/checkouts", checkout_data)
        
        # Return the checkout URL
        return result["data"]["attributes"]["url"]
    
    async def get_subscription(self, subscription_id: str) -> dict:
        """
        Get subscription details from Lemon Squeezy.
        """
        result = await self._make_request("GET", f"/subscriptions/{subscription_id}")
        return result["data"]
    
    async def cancel_subscription(self, subscription_id: str) -> dict:
        """
        Cancel a subscription.
        """
        result = await self._make_request(
            "PATCH",
            f"/subscriptions/{subscription_id}",
            {"data": {"attributes": {"cancelled": True}}}
        )
        return result["data"]
    
    async def create_customer(self, email: str, name: str, tenant_id: int) -> str:
        """
        Create a customer in Lemon Squeezy.
        """
        customer_data = {
            "data": {
                "type": "customers",
                "attributes": {
                    "email": email,
                    "name": name,
                    "meta": {
                        "tenant_id": str(tenant_id)
                    }
                },
                "relationships": {
                    "store": {
                        "data": {
                            "type": "stores",
                            "id": self.store_id
                        }
                    }
                }
            }
        }
        
        result = await self._make_request("POST", "/customers", customer_data)
        return result["data"]["id"]
    
    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """
        Verify webhook signature from Lemon Squeezy.
        """
        if not self.webhook_secret:
            return False  # Reject if no secret configured (must be set in production)
        
        expected_signature = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)
    
    def handle_webhook(self, payload: bytes, signature: str, db: Session) -> dict:
        """
        Handle webhook events from Lemon Squeezy.
        """
        if not self.verify_webhook(payload, signature):
            raise ValueError("Invalid webhook signature")
        
        import json
        event_data = json.loads(payload)
        
        event_type = event_data.get("meta", {}).get("event_name")
        custom_data = event_data.get("meta", {}).get("custom_data", {})
        tenant_id = custom_data.get("tenant_id")
        
        if not tenant_id:
            return {"status": "ignored", "reason": "No tenant_id in custom data"}
        
        tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
        
        if not tenant:
            return {"status": "error", "reason": "Tenant not found"}
        
        if event_type == "subscription_created":
            return self._handle_subscription_created(event_data, tenant, db)
        elif event_type == "subscription_updated":
            return self._handle_subscription_updated(event_data, tenant, db)
        elif event_type == "subscription_cancelled":
            return self._handle_subscription_cancelled(event_data, tenant, db)
        elif event_type == "subscription_expired":
            return self._handle_subscription_expired(event_data, tenant, db)
        elif event_type == "subscription_payment_succeeded":
            return self._handle_payment_succeeded(event_data, tenant, db)
        elif event_type == "subscription_payment_failed":
            return self._handle_payment_failed(event_data, tenant, db)
        
        return {"status": "processed", "event": event_type}
    
    def _handle_subscription_created(self, event_data: dict, tenant: models.Tenant, db: Session) -> dict:
        """Handle subscription created event."""
        attributes = event_data.get("data", {}).get("attributes", {})
        
        tenant.lemon_subscription_id = str(event_data["data"]["id"])
        tenant.subscription_status = attributes.get("status", "active")
        
        # Get variant ID to determine plan
        variant_id = str(attributes.get("variant_id", ""))
        plan = get_plan_from_variant(variant_id)
        tenant.plan = plan
        
        # Set renewal date
        renews_at = attributes.get("renews_at")
        if renews_at:
            tenant.subscription_renews_at = datetime.fromisoformat(renews_at.replace("Z", "+00:00"))
        
        db.commit()
        
        return {"status": "processed", "action": "subscription_created", "plan": plan}
    
    def _handle_subscription_updated(self, event_data: dict, tenant: models.Tenant, db: Session) -> dict:
        """Handle subscription updated event."""
        attributes = event_data.get("data", {}).get("attributes", {})
        
        tenant.subscription_status = attributes.get("status", tenant.subscription_status)
        
        # Check if plan changed
        variant_id = str(attributes.get("variant_id", ""))
        new_plan = get_plan_from_variant(variant_id)
        
        if new_plan != tenant.plan:
            tenant.plan = new_plan
        
        # Update renewal date
        renews_at = attributes.get("renews_at")
        if renews_at:
            tenant.subscription_renews_at = datetime.fromisoformat(renews_at.replace("Z", "+00:00"))
        
        db.commit()
        
        return {"status": "processed", "action": "subscription_updated", "plan": new_plan}
    
    def _handle_subscription_cancelled(self, event_data: dict, tenant: models.Tenant, db: Session) -> dict:
        """Handle subscription cancelled event."""
        tenant.subscription_status = "canceled"
        tenant.plan = "free"  # Downgrade to free
        
        db.commit()
        
        return {"status": "processed", "action": "subscription_cancelled"}
    
    def _handle_subscription_expired(self, event_data: dict, tenant: models.Tenant, db: Session) -> dict:
        """Handle subscription expired event."""
        tenant.subscription_status = "expired"
        tenant.plan = "free"
        tenant.lemon_subscription_id = None
        
        db.commit()
        
        return {"status": "processed", "action": "subscription_expired"}
    
    def _handle_payment_succeeded(self, event_data: dict, tenant: models.Tenant, db: Session) -> dict:
        """Handle successful payment event."""
        tenant.subscription_status = "active"
        
        # Extend renewal date
        attributes = event_data.get("data", {}).get("attributes", {})
        renews_at = attributes.get("renews_at")
        if renews_at:
            tenant.subscription_renews_at = datetime.fromisoformat(renews_at.replace("Z", "+00:00"))
        
        db.commit()
        
        return {"status": "processed", "action": "payment_succeeded"}
    
    def _handle_payment_failed(self, event_data: dict, tenant: models.Tenant, db: Session) -> dict:
        """Handle failed payment event."""
        tenant.subscription_status = "past_due"
        
        db.commit()
        
        return {"status": "processed", "action": "payment_failed"}
    
    async def create_customer_portal_url(self, tenant: models.Tenant, return_url: str) -> str:
        """
        Create a customer portal URL for managing subscription.
        Note: Lemon Squeezy doesn't have a native portal like Stripe,
        so we return a link to the billing settings page.
        """
        # In production, you might want to generate a custom billing page
        # or use Lemon Squeezy's customer URL
        if tenant.lemon_customer_id:
            # Lemon Squeezy doesn't have a public customer portal URL
            # Return your app's billing page
            pass
        
        return return_url
    
    def get_subscription_info(self, tenant: models.Tenant) -> dict:
        """Get current subscription information."""
        return {
            "plan": tenant.plan,
            "status": tenant.subscription_status,
            "is_active": tenant.subscription_status == "active",
            "renews_at": tenant.subscription_renews_at.isoformat() if tenant.subscription_renews_at else None,
        }


# Create singleton instance
lemon_squeezy_service = LemonSqueezyService()
