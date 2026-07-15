import uuid
import os
import logging
from datetime import datetime, timedelta
import urllib.parse
from fastapi import APIRouter, Depends, HTTPException, Header, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Dict, Any
import httpx

from core.database import SessionLocal
from models.models import SocialConnection, PublishJob
from schemas.schemas import ConnectionOut, JobOut
from services.encryption import encrypt_token

router = APIRouter(prefix="/social", tags=["social"])
logger = logging.getLogger("social_service.routes")

async def get_db():
    async with SessionLocal() as session:
        yield session

# Helper dependencies to extract gateway headers
def get_user_id(x_user_id: str = Header(None)):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header missing")
    return uuid.UUID(x_user_id)

def get_account_id(x_account_id: str = Header(None)):
    if not x_account_id:
        raise HTTPException(status_code=400, detail="X-Account-Id header missing")
    return uuid.UUID(x_account_id)

@router.get("/connect/linkedin")
async def connect_linkedin(
    account_id: uuid.UUID = Depends(get_account_id)
):
    """
    Generate LinkedIn OAuth authorization redirect URL.
    Uses 'account_id' as state payload.
    """
    client_id = os.getenv("LINKEDIN_CLIENT_ID")
    redirect_uri = os.getenv("LINKEDIN_REDIRECT_URI")
    
    if not client_id or client_id.startswith("your_"):
        # Simulated Connect Link for Sandbox Mock Mode
        mock_callback = f"{redirect_uri}?code=mock_code_123&state={account_id}"
        return {"authorization_url": mock_callback}

    scope = "openid profile email w_member_social"
    auth_url = (
        f"https://www.linkedin.com/oauth/v2/authorization?"
        f"response_type=code&client_id={client_id}&"
        f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
        f"state={account_id}&scope={urllib.parse.quote(scope)}"
    )
    return {"authorization_url": auth_url}

@router.get("/callback")
async def linkedin_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Exchange auth code for access tokens, retrieve Person URN, 
    encrypt credentials, and store connection state.
    """
    account_id = uuid.UUID(state)
    redirect_uri = os.getenv("LINKEDIN_REDIRECT_URI")
    client_id = os.getenv("LINKEDIN_CLIENT_ID")
    client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")

    # Sandbox Mock check
    if code == "mock_code_123" or not client_id or client_id.startswith("your_"):
        logger.info(f"[MOCK] Saving mock LinkedIn connection for account {account_id}")
        
        # Save mock connection
        async with db.begin():
            # Delete old connection if exists
            q_del = select(SocialConnection).where(SocialConnection.account_id == account_id)
            res_del = await db.execute(q_del)
            old_conn = res_del.scalar_one_or_none()
            if old_conn:
                await db.delete(old_conn)

            connection = SocialConnection(
                account_id=account_id,
                platform="linkedin",
                person_urn="urn:li:person:mock_profile_urn",
                encrypted_access_token="mock",
                encrypted_refresh_token="mock",
                expires_at=datetime.utcnow() + timedelta(days=60)
            )
            db.add(connection)
        return RedirectResponse(url="http://localhost:3000/dashboard?linkedin=connected")

    # Real LinkedIn token exchange
    token_url = "https://www.linkedin.com/oauth/v2/accessToken"
    exchange_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret
    }

    try:
        async with httpx.AsyncClient() as client:
            # 1. Fetch access token
            token_resp = await client.post(token_url, data=exchange_payload, timeout=10.0)
            if token_resp.status_code != 200:
                raise Exception(f"Failed to exchange code: {token_resp.text}")
                
            token_data = token_resp.json()
            access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 5184000) # Default to 60 days
            refresh_token = token_data.get("refresh_token")

            # 2. Fetch Person URN using profile API
            profile_url = "https://api.linkedin.com/v2/userinfo"
            headers = {"Authorization": f"Bearer {access_token}"}
            prof_resp = await client.get(profile_url, headers=headers, timeout=5.0)
            if prof_resp.status_code != 200:
                 raise Exception(f"Failed to fetch profile: {prof_resp.text}")
                 
            prof_data = prof_resp.json()
            person_urn = prof_data.get("sub") # Person ID / URN

            # 3. Encrypt access/refresh tokens
            enc_access = encrypt_token(access_token)
            enc_refresh = encrypt_token(refresh_token) if refresh_token else None
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

            # 4. Save to Database
            async with db.begin():
                # Remove existing
                q_del = select(SocialConnection).where(SocialConnection.account_id == account_id)
                res_del = await db.execute(q_del)
                old_conn = res_del.scalar_one_or_none()
                if old_conn:
                    await db.delete(old_conn)

                connection = SocialConnection(
                    account_id=account_id,
                    platform="linkedin",
                    person_urn=person_urn,
                    encrypted_access_token=enc_access,
                    encrypted_refresh_token=enc_refresh,
                    expires_at=expires_at
                )
                db.add(connection)
            return RedirectResponse(url="http://localhost:3000/dashboard?linkedin=connected")
    except Exception as e:
        logger.error(f"LinkedIn Callback failed: {e}", exc_info=True)
        return RedirectResponse(url="http://localhost:3000/dashboard?linkedin=failed")

@router.get("/connections", response_model=List[ConnectionOut])
async def get_connections(
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Get active social connection list for active account.
    """
    q = select(SocialConnection).where(SocialConnection.account_id == account_id)
    res = await db.execute(q)
    return res.scalars().all()

@router.post("/disconnect")
async def disconnect_account(
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Remove LinkedIn connection credentials.
    """
    q = select(SocialConnection).where(SocialConnection.account_id == account_id)
    res = await db.execute(q)
    conn = res.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="No active connection found")
        
    await db.delete(conn)
    await db.commit()
    return {"status": "disconnected"}

@router.get("/history", response_model=List[JobOut])
async def list_publish_jobs(
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all publishing histories for the active workspace.
    """
    q = select(PublishJob).where(PublishJob.account_id == account_id).order_by(PublishJob.created_at.desc())
    res = await db.execute(q)
    return res.scalars().all()
