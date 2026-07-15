import asyncio
import logging
import os
from datetime import datetime, timedelta
from sqlalchemy.future import select
from core.database import SessionLocal
from models.models import SocialConnection
from services.encryption import decrypt_token, encrypt_token
import httpx

logger = logging.getLogger("social_service.refresher")

async def refresh_linkedin_tokens():
    """
    Scans database for social connections expiring in less than 7 days,
    and refreshes them via LinkedIn's refresh token API.
    """
    logger.info("Scanning for expiring LinkedIn connections...")
    threshold = datetime.utcnow() + timedelta(days=7)
    
    async with SessionLocal() as session:
        async with session.begin():
            q = select(SocialConnection).where(SocialConnection.expires_at <= threshold)
            res = await session.execute(q)
            connections = res.scalars().all()
            
            for conn in connections:
                logger.info(f"Refreshing connection for account {conn.account_id}")
                
                # Mock Mode Bypass
                if conn.encrypted_access_token == "mock" or not conn.encrypted_refresh_token:
                    conn.expires_at = datetime.utcnow() + timedelta(days=60)
                    logger.info(f"Mock connection for {conn.account_id} refreshed to 60 days.")
                    continue
                
                # Real refresh
                try:
                    refresh_token = decrypt_token(conn.encrypted_refresh_token)
                    client_id = os.getenv("LINKEDIN_CLIENT_ID")
                    client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")
                    
                    if not client_id or not client_secret:
                        logger.error("LinkedIn client credentials missing for token refresh.")
                        continue
                        
                    token_url = "https://www.linkedin.com/oauth/v2/accessToken"
                    payload = {
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": client_id,
                        "client_secret": client_secret
                    }
                    
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(token_url, data=payload, timeout=10.0)
                        if resp.status_code == 200:
                            data = resp.json()
                            conn.encrypted_access_token = encrypt_token(data["access_token"])
                            if "refresh_token" in data:
                                conn.encrypted_refresh_token = encrypt_token(data["refresh_token"])
                            expires_in = data.get("expires_in", 5184000)
                            conn.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                            logger.info(f"Connection for {conn.account_id} refreshed successfully.")
                        else:
                            logger.error(f"LinkedIn token refresh failed: {resp.text}")
                except Exception as e:
                    logger.error(f"Error during refresh loop for account {conn.account_id}: {e}")
                    
async def start_token_refresher_loop():
    """Loop running every 12 hours to refresh credentials."""
    logger.info("LinkedIn token refresher daemon started.")
    while True:
        try:
            await refresh_linkedin_tokens()
        except Exception as e:
            logger.error(f"Error in token refresher loop: {e}")
        # Run every 12 hours
        await asyncio.sleep(43200)
