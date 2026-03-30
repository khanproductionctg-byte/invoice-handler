"""
Token encryption utilities for secure OAuth token storage.
Requires TOKEN_ENCRYPTION_KEY environment variable - NO FALLBACK.
"""
import os
import json
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class TokenEncryptionError(Exception):
    """Raised when token encryption/decryption fails."""
    pass


class TokenEncryptor:
    """
    Fernet-based token encryption.
    Requires TOKEN_ENCRYPTION_KEY to be set - no fallback allowed.
    """
    
    def __init__(self):
        encryption_key = os.getenv("TOKEN_ENCRYPTION_KEY")
        
        if not encryption_key:
            raise TokenEncryptionError(
                "TOKEN_ENCRYPTION_KEY environment variable is REQUIRED. "
                "Set it to a valid Fernet key (32 bytes, base64-encoded). "
                "Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        
        try:
            from cryptography.fernet import Fernet
            self.fernet = Fernet(encryption_key.encode())
        except Exception as e:
            raise TokenEncryptionError(
                f"Invalid TOKEN_ENCRYPTION_KEY: {str(e)}. "
                "Key must be a valid Fernet key (32 bytes, base64-encoded)."
            )
    
    def encrypt(self, data: Dict[str, Any]) -> str:
        """
        Encrypt a dictionary of token data.
        
        Args:
            data: Dictionary containing token information (access_token, refresh_token, etc.)
            
        Returns:
            Encrypted string suitable for database storage
        """
        try:
            json_data = json.dumps(data)
            encrypted = self.fernet.encrypt(json_data.encode())
            return encrypted.decode()
        except Exception as e:
            logger.error(f"Failed to encrypt token data: {str(e)}")
            raise TokenEncryptionError(f"Encryption failed: {str(e)}")
    
    def decrypt(self, encrypted_data: str) -> Optional[Dict[str, Any]]:
        """
        Decrypt token data.
        
        Args:
            encrypted_data: Encrypted string from database
            
        Returns:
            Dictionary with token information, or None if decryption fails
        """
        if not encrypted_data:
            return None
            
        try:
            decrypted = self.fernet.decrypt(encrypted_data.encode())
            return json.loads(decrypted.decode())
        except Exception as e:
            logger.error(f"Failed to decrypt token data: {str(e)}")
            # Return None instead of raising - might be old plaintext data
            return None


# Global instance - created on first use
_token_encryptor: Optional[TokenEncryptor] = None


def get_token_encryptor() -> TokenEncryptor:
    """
    Get or create the global token encryptor instance.
    
    Returns:
        TokenEncryptor instance
        
    Raises:
        TokenEncryptionError: If TOKEN_ENCRYPTION_KEY is not set
    """
    global _token_encryptor
    if _token_encryptor is None:
        _token_encryptor = TokenEncryptor()
    return _token_encryptor


def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key.
    
    Returns:
        Base64-encoded Fernet key
    """
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


def validate_encryption_key(key: str) -> bool:
    """
    Validate that a string is a valid Fernet key.
    
    Args:
        key: String to validate
        
    Returns:
        True if valid Fernet key, False otherwise
    """
    try:
        from cryptography.fernet import Fernet
        Fernet(key.encode())
        return True
    except Exception:
        return False
