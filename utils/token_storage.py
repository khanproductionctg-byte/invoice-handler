"""
Secure token storage utilities using Fernet encryption.
Provides encryption/decryption for OAuth tokens stored on disk.
"""
import os
import json
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# cryptography is required - no plaintext fallback
try:
    from cryptography.fernet import Fernet
    FERNET_AVAILABLE = True
except ImportError:
    FERNET_AVAILABLE = False
    raise RuntimeError(
        "cryptography library is REQUIRED. "
        "Install with: pip install cryptography. "
        "Plaintext token storage is not permitted."
    )


class SecureTokenStorage:
    """Secure token storage with encryption support."""
    
    def __init__(self, encryption_key: Optional[str] = None):
        if not FERNET_AVAILABLE:
            raise RuntimeError(
                "cryptography library is REQUIRED. "
                "Install with: pip install cryptography. "
                "Plaintext token storage is not permitted."
            )
        if encryption_key:
            self.fernet = Fernet(encryption_key.encode())
        else:
            env_key = os.getenv("TOKEN_ENCRYPTION_KEY")
            if env_key:
                self.fernet = Fernet(env_key.encode())
            else:
                raise RuntimeError(
                    "No encryption key provided and TOKEN_ENCRYPTION_KEY not set. "
                    "A Fernet encryption key is REQUIRED. "
                    "Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
                )
    
    def _generate_key(self) -> str:
        """Generate a new encryption key."""
        return Fernet.generate_key().decode()
    
    def save_token(self, token_data: Dict[str, Any], filepath: str) -> bool:
        """
        Save token data to file with encryption.
        
        Args:
            token_data: Dictionary containing token information
            filepath: Path to save the token
            
        Returns:
            True if successful, False otherwise
        """
        try:
            json_data = json.dumps(token_data)
            encrypted = self.fernet.encrypt(json_data.encode())
            with open(filepath, 'wb') as f:
                f.write(encrypted)
            os.chmod(filepath, 0o600)
            logger.info(f"Token saved securely to {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save token: {str(e)}")
            return False
    
    def load_token(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        Load and decrypt token data from file.
        
        Args:
            filepath: Path to the token file
            
        Returns:
            Dictionary containing token information, or None if failed
        """
        try:
            if not os.path.exists(filepath):
                return None
            
            with open(filepath, 'rb') as f:
                data = f.read()
            decrypted = self.fernet.decrypt(data)
            return json.loads(decrypted.decode())
                
        except Exception as e:
            logger.error(f"Failed to load token: {str(e)}")
            return None
    
    def delete_token(self, filepath: str) -> bool:
        """Delete a token file."""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Token deleted: {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete token: {str(e)}")
            return False


# Global instance for convenience
_token_storage: Optional[SecureTokenStorage] = None


def get_token_storage() -> SecureTokenStorage:
    """Get or create the global token storage instance."""
    global _token_storage
    if _token_storage is None:
        _token_storage = SecureTokenStorage()
    return _token_storage
