import os
from cryptography.fernet import Fernet

def get_fernet() -> Fernet:
    # Use key from environment, or generate a stable fallback for development
    key = os.getenv("SOCIAL_ENCRYPTION_KEY")
    if not key:
        # Default key for development (32 url-safe base64-encoded bytes)
        key = "h8n2l01N0P6841m82M183M183M183M183M183M183Mw="
    return Fernet(key.encode())

def encrypt_token(token: str) -> str:
    """Encrypt a token string."""
    f = get_fernet()
    return f.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a token string."""
    f = get_fernet()
    return f.decrypt(encrypted_token.encode()).decode()
