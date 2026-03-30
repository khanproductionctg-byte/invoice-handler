"""
MFA (Multi-Factor Authentication) utilities.

This module provides MFA functionality using Clerk as the identity provider.
Clerk handles MFA enrollment and verification - we just need to verify the token.

Setup Instructions:
==================

1. Enable MFA in Clerk Dashboard:
   - Go to https://dashboard.clerk.com
   - Navigate to your application -> Settings -> Security -> Multi-factor
   - Enable "One-time code" (Authenticator app) or "SMS" or both
   - Configure which roles/users are required to use MFA

2. Set environment variable in production:
   ENFORCE_MFA=true

3. The system will now require MFA for all authenticated requests.
   Token verification will check for "mfa_verified": true in the JWT.

Token Claims:
=============
When MFA is verified, Clerk includes in the JWT:
- mfa_verified: true (MFA was completed)
- mfa_pending: false

When MFA is pending (first factor only):
- mfa_verified: false
- mfa_pending: true (first factor passed, waiting for second)
"""
import os
import logging

logger = logging.getLogger(__name__)

# MFA enforcement setting
ENFORCE_MFA = os.getenv("ENFORCE_MFA", "false").lower() == "true"

if ENFORCE_MFA:
    logger.warning(
        "MFA ENFORCEMENT IS ENABLED. "
        "All requests will require multi-factor authentication. "
        "Ensure Clerk MFA is configured in the Clerk Dashboard."
    )


def is_mfa_required() -> bool:
    """Check if MFA is required for this environment."""
    return ENFORCE_MFA


def check_mfa_status(claims: dict) -> dict:
    """
    Check MFA status from JWT claims.
    
    Args:
        claims: Decoded JWT payload from Clerk
        
    Returns:
        Dict with mfa_verified, mfa_pending status
    """
    return {
        "mfa_verified": claims.get("mfa_verified", False),
        "mfa_pending": claims.get("mfa_pending", False),
    }


def is_mfa_verified(claims: dict) -> bool:
    """
    Check if MFA was verified in this session.
    
    Args:
        claims: Decoded JWT payload from Clerk
        
    Returns:
        True if MFA was verified, False otherwise
    """
    return claims.get("mfa_verified", False) is True


def get_mfa_enforcement_message() -> str:
    """Get message to display to users when MFA is required."""
    return (
        "Multi-factor authentication is required for this application. "
        "Please enable MFA in your account settings to continue. "
        "Contact your administrator if you need assistance."
    )
