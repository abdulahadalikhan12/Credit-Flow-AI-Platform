import os
import uuid
import logging
import datetime
from typing import Optional, Dict, Any, List
import jwt
import httpx
import redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.models import User, Credential, RefreshToken, PasswordResetToken
from core.security import verify_password, get_password_hash, get_private_key
from shared.messaging import RabbitMQClient

logger = logging.getLogger("auth_service.auth_manager")

class AuthManager:
    def __init__(self):
        self.redis_host = os.getenv("REDIS_HOST", "redis")
        self.redis_port = int(os.getenv("REDIS_PORT", "6379"))
        self.algorithm = os.getenv("JWT_ALGORITHM", "RS256")
        self.secret_key = os.getenv("JWT_SECRET_KEY", "local_development_jwt_secret_key_change_in_production")
        self.rabbitmq = RabbitMQClient()

    async def get_redis_client(self):
        return redis.Redis(host=self.redis_host, port=self.redis_port, decode_responses=True)

    async def fetch_user_accounts(self, user_id: uuid.UUID) -> List[Dict[str, Any]]:
        """
        Query User/Tenant Service to fetch accounts this user belongs to.
        """
        user_service_url = os.getenv("USER_SERVICE_URL", "http://user_service:8002")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{user_service_url}/api/v1/accounts/internal/users/{user_id}/accounts", timeout=5.0)
                if response.status_code == 200:
                    return response.json()
                logger.warning(f"User service returned code {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Error fetching user accounts from User Service: {e}")
        return []

    async def generate_tokens(self, db: AsyncSession, user: User, account_id: Optional[str] = None) -> Dict[str, str]:
        """
        Generate access token (RS256) and refresh token. Save jti state in PostgreSQL and Redis.
        """
        # Resolve account_id and role
        accounts = await self.fetch_user_accounts(user.id)
        role = "member"
        active_account_id = None
        
        if accounts:
            # If account_id is specified and user belongs to it, use it; otherwise use the first one
            matched = next((a for a in accounts if str(a["account_id"]) == account_id), None)
            if matched:
                active_account_id = str(matched["account_id"])
                role = matched["role"]
            else:
                active_account_id = str(accounts[0]["account_id"])
                role = accounts[0]["role"]
        else:
            # Fallback for signups before the event-driven consumer completes account creation
            active_account_id = str(user.id) # fallback matching individual user_id
            role = "owner"

        if user.email.lower() == "superadmin@creditflow.ai":
            role = "superadmin"

        jti = str(uuid.uuid4())
        access_token_expires = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
        refresh_token_expires = datetime.datetime.utcnow() + datetime.timedelta(days=7)

        # Build access token
        access_payload = {
            "user_id": str(user.id),
            "account_id": active_account_id,
            "role": role,
            "jti": jti,
            "exp": access_token_expires
        }

        if self.algorithm == "RS256":
            private_key = get_private_key()
            access_token = jwt.encode(access_payload, private_key, algorithm="RS256")
        else:
            access_token = jwt.encode(access_payload, self.secret_key, algorithm="HS256")

        # Generate refresh token
        refresh_token = str(uuid.uuid4())

        # Save to DB
        db_refresh = RefreshToken(
            user_id=user.id,
            jti=jti,
            expires_at=refresh_token_expires
        )
        db.add(db_refresh)
        await db.commit()

        # Save active JTI in Redis with TTL
        try:
            r = await self.get_redis_client()
            redis_key = f"auth:jti:{jti}"
            # TTL in seconds
            ttl = int((access_token_expires - datetime.datetime.utcnow()).total_seconds())
            if ttl > 0:
                r.set(redis_key, str(user.id), ex=ttl)
        except Exception as e:
            logger.error(f"Failed to cache JTI in Redis: {e}")

        return {
            "access_token": access_token,
            "refresh_token": f"{refresh_token}:{jti}", # Embed jti in the token for more direct lookup
            "token_type": "bearer"
        }

    def generate_email_verification_token(self, user_id: uuid.UUID) -> str:
        """Generate a cryptographically signed 24h verification token."""
        payload = {
            "sub": str(user_id),
            "type": "email_verification",
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }
        return jwt.encode(payload, self.secret_key, algorithm="HS256")

    async def register_user(self, db: AsyncSession, email: str, password: str) -> User:
        """Create a new user and emit user.registered event."""
        # Check if already registered
        q = select(User).where(User.email == email)
        res = await db.execute(q)
        if res.fetchone():
            raise ValueError("Email already registered")

        user = User(email=email, is_verified=False)
        db.add(user)
        await db.flush() # populate user.id

        credential = Credential(user_id=user.id, password_hash=get_password_hash(password))
        db.add(credential)
        await db.commit()

        # Send event to RabbitMQ
        verification_token = self.generate_email_verification_token(user.id)
        try:
            await self.rabbitmq.publish(
                exchange_name="auth_events",
                routing_key="user.registered",
                body={
                    "user_id": str(user.id),
                    "email": email,
                    "verification_token": verification_token
                }
            )
        except Exception as e:
            logger.error(f"Failed to publish user.registered event: {e}")

        return user

    async def authenticate_user(self, db: AsyncSession, email: str, password: str) -> User:
        """Authenticate password against stored hash."""
        q = select(User).where(User.email == email)
        res = await db.execute(q)
        user = res.scalar_one_or_none()
        if not user:
            raise ValueError("Invalid email or password")

        cred_q = select(Credential).where(Credential.user_id == user.id)
        cred_res = await db.execute(cred_q)
        credential = cred_res.scalar_one_or_none()

        if not credential or not verify_password(password, credential.password_hash):
            raise ValueError("Invalid email or password")

        if not user.is_verified:
            raise ValueError("Email not verified. Please verify your email first.")

        # Emit user.logged_in
        try:
            await self.rabbitmq.publish(
                exchange_name="auth_events",
                routing_key="user.logged_in",
                body={"user_id": str(user.id), "email": email}
            )
        except Exception as e:
            logger.error(f"Failed to publish user.logged_in event: {e}")

        return user

    async def revoke_session(self, db: AsyncSession, jti: str) -> bool:
        """Revoke active JWT by JTI in both Database and Redis."""
        # Revoke in Database
        q = select(RefreshToken).where(RefreshToken.jti == jti)
        res = await db.execute(q)
        token = res.scalar_one_or_none()
        if token:
            token.is_revoked = True
            await db.commit()

        # Revoke in Redis
        try:
            r = await self.get_redis_client()
            r.delete(f"auth:jti:{jti}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete JTI from Redis: {e}")
        return False
