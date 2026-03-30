#!/usr/bin/env python3
"""Generate secure secrets for production deployment."""
import secrets
import os
from cryptography.fernet import Fernet


def generate_secrets():
    secret_key = secrets.token_hex(32)
    jwt_secret = secrets.token_hex(32)
    fernet_key = Fernet.generate_key().decode()
    
    output = f"""# Generated secrets - {os.popen('date').read().strip()}
# Copy these to .env or .env.production and NEVER commit the actual values

SECRET_KEY={secret_key}
JWT_SECRET_KEY={jwt_secret}
TOKEN_ENCRYPTION_KEY={fernet_key}
"""
    
    with open('.env.generated', 'w') as f:
        f.write(output)
    
    print("Generated .env.generated with secure values.")
    print()
    print("CHECKLIST:")
    print("-" * 40)
    print("1. Copy .env.generated to .env.production")
    print("2. Update TOKEN_ENCRYPTION_KEY in your secrets manager")
    print("3. Add .env.generated to .gitignore (keep it for reference)")
    print("4. Never commit actual secret values to version control")
    print("5. Run: python -m api.main (validation will happen at startup)")
    print()
    print("Generated values (for reference):")
    print(f"  SECRET_KEY={secret_key[:16]}...{secret_key[-8:]}")
    print(f"  JWT_SECRET_KEY={jwt_secret[:16]}...{jwt_secret[-8:]}")
    print(f"  TOKEN_ENCRYPTION_KEY={fernet_key[:16]}...")


if __name__ == "__main__":
    generate_secrets()
