import os
import logging
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import bcrypt
import redis

logger = logging.getLogger("auth_service.security")

# Global variables to store our RSA private key and public key in PEM format
private_key = None
public_key_pem = ""

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against hashed password."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password: str) -> str:
    """Hash password using bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def load_or_generate_keys():
    """
    Load private key from disk or generate a new RSA 2048-bit key pair.
    Stores the public key in Redis under 'auth:public_key'.
    """
    global private_key, public_key_pem
    
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    
    # Target directory for storing key files
    keys_dir = "/app/auth_service/keys"
    os.makedirs(keys_dir, exist_ok=True)
    private_key_path = os.path.join(keys_dir, "private_key.pem")

    if os.path.exists(private_key_path):
        logger.info(f"Loading private key from {private_key_path}...")
        with open(private_key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
    else:
        logger.info("Generating new RSA key pair for RS256...")
        # Generate new RSA key
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )
        # Save private key to disk
        with open(private_key_path, "wb") as f:
            f.write(pem)
        logger.info(f"Private key saved to {private_key_path}")

    # Serialize public key to PEM format
    public_key = private_key.public_key()
    public_key_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()

    # Store public key in Redis
    try:
        r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        r.set("auth:public_key", public_key_pem)
        logger.info("RS256 Public Key successfully stored in Redis.")
    except Exception as e:
        logger.error(f"Failed to publish public key to Redis: {e}")

    return private_key, public_key_pem

def get_private_key():
    """Retrieve the global private key instance."""
    global private_key
    if not private_key:
        load_or_generate_keys()
    return private_key
