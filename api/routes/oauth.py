"""
OAuth connection handlers for external services.
Google (Gmail + Drive), QuickBooks, Xero, Plaid
"""
import os
import base64
import secrets
from fastapi import APIRouter, Depends, HTTPException, Query, Request

OAUTH_STATE_SECRET = os.getenv("OAUTH_STATE_SECRET")
if not OAUTH_STATE_SECRET:
    raise RuntimeError(
        "OAUTH_STATE_SECRET environment variable is REQUIRED. "
        "Generate with: python -c \"from itsdangerous import URLSafeTimedSerializer; import secrets; print(secrets.token_hex(32))\""
    )
from itsdangerous import URLSafeTimedSerializer
oauth_state_serializer = URLSafeTimedSerializer(OAUTH_STATE_SECRET)


def _create_oauth_state(tenant_id: int) -> str:
    """Create a signed, time-limited OAuth state parameter."""
    return oauth_state_serializer.dumps({"tenant_id": tenant_id})


def _validate_oauth_state(state: str) -> tuple[bool, int | None]:
    """Validate and extract tenant_id from OAuth state parameter.
    
    Returns (is_valid, tenant_id).
    State expires after 10 minutes (600 seconds).
    """
    try:
        data = oauth_state_serializer.loads(state, max_age=600)
        tenant_id = data.get("tenant_id")
        if tenant_id is None:
            return False, None
        return True, int(tenant_id)
    except Exception:
        return False, None
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from db.database import get_db
from db import models
from middleware import get_current_tenant, require_feature
from config.plan_limits import can_use_feature

# Rate limiting
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    limiter = Limiter(key_func=get_remote_address)
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    limiter = None
    RATE_LIMITING_AVAILABLE = False

router = APIRouter(prefix="/oauth", tags=["oauth"])

# Environment variables
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "https://yourapp.com/oauth/google/callback")

QUICKBOOKS_CLIENT_ID = os.getenv("QUICKBOOKS_CLIENT_ID", "")
QUICKBOOKS_CLIENT_SECRET = os.getenv("QUICKBOOKS_CLIENT_SECRET", "")
QUICKBOOKS_REDIRECT_URI = os.getenv("QUICKBOOKS_REDIRECT_URI", "https://yourapp.com/oauth/quickbooks/callback")

XERO_CLIENT_ID = os.getenv("XERO_CLIENT_ID", "")
XERO_CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET", "")
XERO_REDIRECT_URI = os.getenv("XERO_REDIRECT_URI", "https://yourapp.com/oauth/xero/callback")

PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.getenv("PLAID_SECRET", "")
PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")


# ============================================================================
# GOOGLE (Gmail + Drive)
# ============================================================================

@router.get("/google/auth")
@limiter.limit("10/minute") if RATE_LIMITING_AVAILABLE else lambda request: None
async def google_auth(
    request: Request,
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Get Google OAuth URL."""
    state = _create_oauth_state(tenant.id)
    
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={GOOGLE_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=email%20profile%20https://www.googleapis.com/auth/gmail.readonly%20https://www.googleapis.com/auth/drive.readonly&"
        f"state={state}&"
        "access_type=offline&"
        "prompt=consent"
    )
    
    return {"auth_url": auth_url, "state": state}


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db)
):
    """Handle Google OAuth callback."""
    import httpx
    
    valid, tenant_id = _validate_oauth_state(state)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter. Possible CSRF attack.")
    
    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_REDIRECT_URI
            }
        )
        
        if token_response.status_code != 200:
            raise HTTPException(400, "Failed to exchange code for tokens")
        
        tokens = token_response.json()
        
        # Get user info
        user_response = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        user_info = user_response.json()
    
    # Save connected account
    existing = db.query(models.ConnectedAccount).filter(
        models.ConnectedAccount.tenant_id == tenant_id,
        models.ConnectedAccount.provider == "google"
    ).first()
    
    if existing:
        existing.access_token = tokens.get("access_token")
        existing.refresh_token = tokens.get("refresh_token", existing.refresh_token)
        existing.expires_at = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
        existing.is_active = True
    else:
        account = models.ConnectedAccount(
            tenant_id=tenant_id,
            provider="google",
            provider_account_id=user_info["id"],
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            expires_at=datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
        )
        db.add(account)
    
    db.commit()
    
    return {"status": "connected", "redirect_url": "/settings/connections?connected=google"}


# ============================================================================
# QUICKBOOKS
# ============================================================================

@router.get("/quickbooks/auth")
@limiter.limit("10/minute") if RATE_LIMITING_AVAILABLE else lambda request: None
async def quickbooks_auth(
    request: Request,
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Get QuickBooks OAuth URL."""
    state = _create_oauth_state(tenant.id)
    
    auth_url = (
        "https://appcenter.intuit.com/connect/oauth2?"
        f"client_id={QUICKBOOKS_CLIENT_ID}&"
        f"redirect_uri={QUICKBOOKS_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=com.intuit.quickbooks.accounting&"
        f"state={state}"
    )
    
    return {"auth_url": auth_url}


@router.get("/quickbooks/callback")
async def quickbooks_callback(
    code: str = Query(...),
    realmId: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db)
):
    """Handle QuickBooks OAuth callback."""
    import httpx
    
    valid, tenant_id = _validate_oauth_state(state)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter. Possible CSRF attack.")
    
    async with httpx.AsyncClient() as client:
        credentials = base64.b64encode(
            f"{QUICKBOOKS_CLIENT_ID}:{QUICKBOOKS_CLIENT_SECRET}".encode()
        ).decode()
        
        token_response = await client.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": QUICKBOOKS_REDIRECT_URI
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}"
            }
        )
        
        if token_response.status_code != 200:
            raise HTTPException(400, "Failed to get tokens")
        
        tokens = token_response.json()
    
    # Save
    existing = db.query(models.ConnectedAccount).filter(
        models.ConnectedAccount.tenant_id == tenant_id,
        models.ConnectedAccount.provider == "quickbooks"
    ).first()
    
    if existing:
        existing.access_token = tokens.get("access_token")
        existing.refresh_token = tokens.get("refresh_token", existing.refresh_token)
        existing.provider_account_id = realmId
    else:
        account = models.ConnectedAccount(
            tenant_id=tenant_id,
            provider="quickbooks",
            provider_account_id=realmId,
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token")
        )
        db.add(account)
    
    db.commit()
    
    return {"status": "connected", "redirect_url": "/settings/connections?connected=quickbooks"}


# ============================================================================
# XERO
# ============================================================================

@router.get("/xero/auth")
@limiter.limit("10/minute") if RATE_LIMITING_AVAILABLE else lambda request: None
async def xero_auth(
    request: Request,
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Get Xero OAuth URL."""
    state = _create_oauth_state(tenant.id)
    
    auth_url = (
        "https://login.xero.com/identity/connect/authorize?"
        f"client_id={XERO_CLIENT_ID}&"
        f"redirect_uri={XERO_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=openid%20profile%20email%20accounting.transactions%20accounting.contacts&"
        f"state={state}"
    )
    
    return {"auth_url": auth_url}


@router.get("/xero/callback")
async def xero_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db)
):
    """Handle Xero OAuth callback."""
    import httpx
    
    valid, tenant_id = _validate_oauth_state(state)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter. Possible CSRF attack.")
    
    async with httpx.AsyncClient() as client:
        credentials = base64.b64encode(
            f"{XERO_CLIENT_ID}:{XERO_CLIENT_SECRET}".encode()
        ).decode()
        
        token_response = await client.post(
            "https://identity.xero.com/connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": XERO_REDIRECT_URI
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}"
            }
        )
        
        if token_response.status_code != 200:
            raise HTTPException(400, "Failed to get tokens")
        
        tokens = token_response.json()
    
    # Save
    existing = db.query(models.ConnectedAccount).filter(
        models.ConnectedAccount.tenant_id == tenant_id,
        models.ConnectedAccount.provider == "xero"
    ).first()
    
    if existing:
        existing.access_token = tokens.get("access_token")
        existing.refresh_token = tokens.get("refresh_token", existing.refresh_token)
    else:
        account = models.ConnectedAccount(
            tenant_id=tenant_id,
            provider="xero",
            provider_account_id="xero",
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token")
        )
        db.add(account)
    
    db.commit()
    
    return {"status": "connected", "redirect_url": "/settings/connections?connected=xero"}


# ============================================================================
# PLAID
# ============================================================================

@router.post("/plaid/link-token")
async def create_plaid_link_token(
    tenant: models.Tenant = Depends(get_current_tenant)
):
    """Create Plaid Link token for frontend."""
    if not can_use_feature(tenant.plan, "plaid"):
        raise HTTPException(403, "Plaid requires Pro plan")
    
    from plaid import PlaidApi, ApiClient
    from plaid.configuration import Configuration
    
    configuration = Configuration(
        host=f"https://{PLAID_ENV}.plaid.com",
        api_key={
            "clientId": PLAID_CLIENT_ID,
            "secret": PLAID_SECRET
        }
    )
    
    client = PlaidApi(ApiClient(configuration))
    
    response = client.link_token_create({
        "user": {"client_user_id": str(tenant.id)},
        "client_name": "Invoice Handler",
        "products": ["transactions"],
        "country_codes": ["US", "CA", "GB"],
        "language": "en"
    })
    
    return {"link_token": response["link_token"]}


@router.post("/plaid/exchange")
async def exchange_plaid_token(
    public_token: str,
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Exchange Plaid public token for access token."""
    if not can_use_feature(tenant.plan, "plaid"):
        raise HTTPException(403, "Plaid requires Pro plan")
    
    from plaid import PlaidApi
    from plaid.configuration import Configuration
    
    configuration = Configuration(
        host=f"https://{PLAID_ENV}.plaid.com",
        api_key={
            "clientId": PLAID_CLIENT_ID,
            "secret": PLAID_SECRET
        }
    )
    
    client = PlaidApi(ApiClient(configuration))
    
    response = client.item_public_token_exchange({
        "public_token": public_token
    })
    
    # Save
    account = models.ConnectedAccount(
        tenant_id=tenant.id,
        provider="plaid",
        provider_account_id=response["item_id"],
        access_token=response["access_token"]
    )
    db.add(account)
    db.commit()
    
    return {"status": "connected"}


# ============================================================================
# OAUTH PROVIDERS STATUS
# ============================================================================

@router.get("/providers")
async def get_oauth_providers(
    tenant: models.Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Get status of all OAuth providers."""
    connections = db.query(models.ConnectedAccount).filter(
        models.ConnectedAccount.tenant_id == tenant.id,
        models.ConnectedAccount.is_active == True
    ).all()
    
    connected_providers = {c.provider for c in connections}
    
    providers = [
        {"id": "google", "name": "Google", "connected": "google" in connected_providers},
        {"id": "quickbooks", "name": "QuickBooks", "connected": "quickbooks" in connected_providers},
        {"id": "xero", "name": "Xero", "connected": "xero" in connected_providers},
        {"id": "plaid", "name": "Plaid", "connected": "plaid" in connected_providers, "requires_pro": True},
    ]
    
    return providers
