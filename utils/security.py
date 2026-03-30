"""
Security utilities for password hashing and general security functions.
"""
import os
import secrets
import string
from typing import Optional
from passlib.context import CryptContext

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt.
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.
    
    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against
        
    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def generate_random_password(length: int = 16) -> str:
    """
    Generate a random secure password.
    
    Args:
        length: Length of password to generate (default: 16)
        
    Returns:
        Random password string
    """
    alphabet = string.ascii_letters + string.digits + string.punctuation
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        # Ensure password meets complexity requirements
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)
                and any(c in string.punctuation for c in password)):
            return password


def generate_api_key(prefix: str = "sk", length: int = 32) -> str:
    """
    Generate a random API key.
    
    Args:
        prefix: Prefix for the key (e.g., "sk_live_", "sk_test_")
        length: Length of random part
        
    Returns:
        API key string
    """
    random_part = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
    return f"{prefix}{random_part}"


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key for storage.
    
    Args:
        api_key: Plain API key
        
    Returns:
        Hashed API key
    """
    return pwd_context.hash(api_key)


def verify_api_key(plain_key: str, hashed_key: str) -> bool:
    """
    Verify an API key against a hash.
    
    Args:
        plain_key: Plain API key
        hashed_key: Hashed API key
        
    Returns:
        True if key matches, False otherwise
    """
    return pwd_context.verify(plain_key, hashed_key)


def generate_token_secret() -> str:
    """
    Generate a secure random secret for JWT tokens.
    
    Returns:
        Random secret string
    """
    return secrets.token_urlsafe(32)


def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """
    Validate password strength.
    
    Args:
        password: Password to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"
    
    return True, None
