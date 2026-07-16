import uuid
import os
import redis
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Dict, Any
import httpx

from core.database import SessionLocal
from models.models import AuditLog

router = APIRouter(prefix="/admin", tags=["admin"])

async def get_db():
    async with SessionLocal() as session:
        yield session

# Role checks
def get_user_role(x_user_role: str = Header(None)):
    if not x_user_role:
        raise HTTPException(status_code=401, detail="X-User-Role header missing")
    return x_user_role

def require_superadmin(role: str = Depends(get_user_role)):
    if role != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin privileges required")

@router.get("/sessions")
async def list_active_sessions(
    role: str = Depends(get_user_role),
    _ = Depends(require_superadmin)
):
    """
    Get list of all active JWT sessions directly from Redis.
    """
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
    
    try:
        # Fetch all JTI session keys
        keys = r.keys("auth:jti:*")
        sessions = []
        for key in keys:
            jti = key.replace("auth:jti:", "")
            user_id = r.get(key)
            sessions.append({
                "jti": jti,
                "user_id": user_id
            })
        return sessions
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query Redis: {e}")

@router.delete("/sessions/{jti}")
async def revoke_session(
    jti: str,
    db: AsyncSession = Depends(get_db),
    _ = Depends(require_superadmin)
):
    """
    Immediately invalidate a session by removing its JTI from Redis.
    """
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
    
    try:
        r.delete(f"auth:jti:{jti}")
        return {"status": f"session {jti} revoked"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {e}")

@router.get("/audit-log")
async def list_audit_trail(
    db: AsyncSession = Depends(get_db),
    _ = Depends(require_superadmin)
):
    """
    Retrieve global audit timeline.
    """
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)
    res = await db.execute(q)
    
    logs = []
    for row in res.scalars().all():
        logs.append({
            "id": str(row.id),
            "event_id": row.event_id,
            "routing_key": row.routing_key,
            "payload": row.payload,
            "created_at": row.created_at.isoformat()
        })
    return logs

@router.get("/workspaces/{account_id}/summary")
async def get_workspace_summary(
    account_id: uuid.UUID,
    x_account_id: str = Header(None),
    x_user_role: str = Header(None)
):
    """
    Aggregate metrics across microservices (plan, balance, tokens) to feed the dashboard.
    Tenant admins are restricted to their own account_id.
    """
    # Verify Tenant Admin restriction
    if not x_account_id or x_account_id != str(account_id):
        # Unless they are SuperAdmin, raise error
        if x_user_role != "superadmin":
             raise HTTPException(status_code=403, detail="Unauthorized to view workspace logs")

    # Define URLs
    user_url = os.getenv("USER_SERVICE_URL", "http://user_service:8002")
    credits_url = os.getenv("CREDITS_SERVICE_URL", "http://credits_service:8004")
    usage_url = os.getenv("USAGE_SERVICE_URL", "http://usage_service:8005")

    headers = {"X-Account-Id": str(account_id)}
    
    summary = {
        "account_id": str(account_id),
        "plan_tier": "free",
        "members_count": 0,
        "credit_balance": 0,
        "total_tokens_used": 0
    }

    async with httpx.AsyncClient() as client:
        # 1. Fetch User Workspace profile
        try:
            resp = await client.get(f"{user_url}/api/v1/accounts/profile", headers=headers, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                summary["plan_tier"] = data.get("plan_tier", "free")
        except Exception:
            pass

        # 2. Fetch Members count
        try:
            resp = await client.get(f"{user_url}/api/v1/accounts/members", headers=headers, timeout=3.0)
            if resp.status_code == 200:
                summary["members_count"] = len(resp.json())
        except Exception:
            pass

        # 3. Fetch Credit Balance
        try:
            resp = await client.get(f"{credits_url}/api/v1/credits/balance", headers=headers, timeout=3.0)
            if resp.status_code == 200:
                summary["credit_balance"] = resp.json().get("balance", 0)
        except Exception:
            pass

        # 4. Fetch Usage summary
        try:
            resp = await client.get(f"{usage_url}/api/v1/usage/summary", headers=headers, timeout=3.0)
            if resp.status_code == 200:
                summary["total_tokens_used"] = resp.json().get("total_tokens", 0)
        except Exception:
            pass

    return summary

@router.get("/workspaces")
async def list_workspaces_with_summaries(
    x_user_role: str = Header(None),
    _ = Depends(require_superadmin)
):
    """
    SuperAdmin endpoint to list all workspaces on the platform with aggregated summary metrics.
    """
    user_url = os.getenv("USER_SERVICE_URL", "http://user_service:8002")
    credits_url = os.getenv("CREDITS_SERVICE_URL", "http://credits_service:8004")
    usage_url = os.getenv("USAGE_SERVICE_URL", "http://usage_service:8005")

    async with httpx.AsyncClient() as client:
        try:
            # 1. Fetch all accounts
            headers = {"X-User-Role": "superadmin"}
            resp = await client.get(f"{user_url}/api/v1/accounts/admin/all", headers=headers, timeout=5.0)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=f"User service error: {resp.text}")
            accounts = resp.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch accounts from User Service: {e}")

        # 2. Iterate and aggregate metrics
        summaries = []
        for acc in accounts:
            account_id = acc["id"]
            acc_headers = {
                "X-Account-Id": str(account_id),
                "X-User-Role": "superadmin"
            }
            summary = {
                "account_id": str(account_id),
                "name": acc["name"],
                "type": acc["type"],
                "plan_tier": acc["plan_tier"],
                "created_at": acc.get("created_at"),
                "members_count": 0,
                "credit_balance": 0,
                "total_tokens_used": 0
            }
            
            # Fetch Members count
            try:
                r = await client.get(f"{user_url}/api/v1/accounts/members", headers=acc_headers, timeout=2.0)
                if r.status_code == 200:
                    summary["members_count"] = len(r.json())
            except Exception:
                pass

            # Fetch Credit Balance
            try:
                r = await client.get(f"{credits_url}/api/v1/credits/balance", headers=acc_headers, timeout=2.0)
                if r.status_code == 200:
                    summary["credit_balance"] = r.json().get("balance", 0)
            except Exception:
                pass

            # Fetch Usage summary
            try:
                r = await client.get(f"{usage_url}/api/v1/usage/summary", headers=acc_headers, timeout=2.0)
                if r.status_code == 200:
                    summary["total_tokens_used"] = r.json().get("total_tokens", 0)
            except Exception:
                pass

            summaries.append(summary)

    return summaries

