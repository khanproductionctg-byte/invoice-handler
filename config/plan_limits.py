"""
Plan limits configuration for SaaS tiers - Lemon Squeezy Edition.
"""
from decimal import Decimal

PLAN_LIMITS = {
    "free": {
        "name": "Free",
        "description": "Perfect for getting started",
        "invoices_per_month": 25,
        "emails_per_month": 10,
        "sms_per_month": 0,
        "api_access": False,
        "users_per_tenant": 1,
        "sources": ["gmail"],
        "report_history": 3,
        "support": "email",
        "price_monthly": 0,
        "price_yearly": 0,
        "lemon_variant_id": None,  # No paid variant for free
    },
    "pro": {
        "name": "Pro",
        "description": "For growing businesses",
        "invoices_per_month": 500,
        "emails_per_month": 200,
        "sms_per_month": 50,
        "api_access": True,
        "users_per_tenant": 5,
        "sources": ["gmail", "drive", "quickbooks", "xero", "plaid"],
        "report_history": 50,
        "support": "priority",
        "price_monthly": 29,
        "price_yearly": 290,
        "lemon_variant_id": "pro_monthly_variant_id",  # Set in environment
    },
    "enterprise": {
        "name": "Enterprise",
        "description": "For large organizations",
        "invoices_per_month": -1,  # Unlimited
        "emails_per_month": -1,
        "sms_per_month": -1,
        "api_access": True,
        "users_per_tenant": -1,
        "sources": ["gmail", "drive", "quickbooks", "xero", "plaid", "custom"],
        "report_history": -1,
        "support": "dedicated",
        "price_monthly": 99,
        "price_yearly": 990,
        "lemon_variant_id": "enterprise_monthly_variant_id",  # Set in environment
    }
}


# Lemon Squeezy specific settings
LEMON_SQUEEZY_VARIANTS = {
    "pro_monthly": "lemondemo_pro_monthly",       # Replace with actual variant ID
    "pro_yearly": "lemondemo_pro_yearly",         # Replace with actual variant ID
    "enterprise_monthly": "lemondemo_enterprise",  # Replace with actual variant ID
    "enterprise_yearly": "lemondemo_enterprise_yearly",  # Replace with actual variant ID
}


def get_plan_limits(plan: str) -> dict:
    """Get limits for a specific plan."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


def get_lemon_variant_id(plan: str, billing_cycle: str = "monthly") -> str:
    """Get Lemon Squeezy variant ID for a plan."""
    key = f"{plan}_{billing_cycle}"
    return LEMON_SQUEEZY_VARIANTS.get(key, "")


def can_use_feature(plan: str, feature: str) -> bool:
    """Check if a plan can use a specific feature."""
    limits = get_plan_limits(plan)
    
    feature_map = {
        "api_access": "api_access",
        "sms": "sms_per_month",
        "reports": "report_history",
        "multiple_sources": "sources",
    }
    
    key = feature_map.get(feature, feature)
    value = limits.get(key, 0)
    
    if isinstance(value, bool):
        return value
    if isinstance(value, list):
        return len(value) > 1
    return value != 0


def check_limit(plan: str, resource: str, current_usage: int) -> tuple[bool, str]:
    """
    Check if current usage is within limits.
    Returns (can_proceed, message)
    """
    limits = get_plan_limits(plan)
    limit = limits.get(resource, 0)
    
    if limit == -1:  # Unlimited
        return True, "OK"
    
    if limit == 0:
        return False, f"{resource} not available on {plan} plan"
    
    if current_usage >= limit:
        return False, f"Monthly limit reached. Upgrade to continue."
    
    remaining = limit - current_usage
    return True, f"{remaining} remaining this month"


def get_plan_from_variant(variant_id: str) -> str:
    """Map Lemon Squeezy variant ID to plan name."""
    for plan, config in PLAN_LIMITS.items():
        if config.get("lemon_variant_id") == variant_id:
            return plan
    
    # Check variants directly
    for key, vid in LEMON_SQUEEZY_VARIANTS.items():
        if vid == variant_id:
            if "enterprise" in key:
                return "enterprise"
            elif "pro" in key:
                return "pro"
    
    return "free"


MAX_RECONCILIATION_ITEMS: int = 1000
MAX_INVOICE_BATCH_SIZE: int = 100
MAX_WORKFLOW_OUTPUT_MB: int = 10

RECONCILIATION_CONFIDENCE_THRESHOLDS = {
    "high": 0.85,
    "medium": 0.65,
    "low": 0.45,
}
HIGH_VALUE_INVOICE_THRESHOLD = Decimal("10000.00")
