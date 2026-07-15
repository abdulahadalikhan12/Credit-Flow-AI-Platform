import os
import logging
import jwt
from typing import Dict, Any, Optional
import redis

logger = logging.getLogger("shared.security")

class JWTVerifier:
    def __init__(self):
        self.redis_host = os.getenv("REDIS_HOST", "redis")
        self.redis_port = int(os.getenv("REDIS_PORT", "6379"))
        self.public_key: Optional[str] = None
        self.secret_key = os.getenv("JWT_SECRET_KEY", "local_development_jwt_secret_key_change_in_production")
        self.algorithm = os.getenv("JWT_ALGORITHM", "RS256")

    def _fetch_public_key_from_redis(self) -> Optional[str]:
        """
        Fetch RS256 public key dynamically from Redis, populated by the Auth service.
        """
        try:
            r = redis.Redis(host=self.redis_host, port=self.redis_port, decode_responses=True)
            return r.get("auth:public_key")
        except Exception as e:
            logger.warning(f"Failed to fetch public key from Redis: {e}")
            return None

    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Decode and verify JWT token. Supports RS256 (fetched via Redis) and HS256 fallback.
        """
        # Try RS256 if configured
        if self.algorithm == "RS256":
            if not self.public_key:
                self.public_key = self._fetch_public_key_from_redis()
            
            if self.public_key:
                try:
                    return jwt.decode(token, self.public_key, algorithms=["RS256"])
                except jwt.PyJWTError as e:
                    logger.error(f"RS256 JWT validation failed: {e}")
                    raise e
            else:
                logger.warning("RS256 requested but public key not found in Redis. Falling back to HS256.")

        # Fallback / HS256
        try:
            return jwt.decode(token, self.secret_key, algorithms=["HS256"])
        except jwt.PyJWTError as e:
            logger.error(f"HS256 JWT validation failed: {e}")
            raise e
