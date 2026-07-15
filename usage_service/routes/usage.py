import uuid
import os
import redis
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from core.database import SessionLocal
from models.models import UsageLedgerEntry
from schemas.schemas import UsageSummary, ModelBreakdown
from services.consumer import PLAN_QUOTAS, fetch_account_plan_tier

router = APIRouter(prefix="/usage", tags=["usage"])

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

@router.get("/summary", response_model=UsageSummary)
async def get_usage_summary(
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Get per-model token usage breakdown for the dashboard.
    """
    # 1. Total tokens and cost
    q_total = select(
        func.sum(UsageLedgerEntry.tokens_used),
        func.sum(UsageLedgerEntry.cost)
    ).where(UsageLedgerEntry.account_id == account_id)
    
    total_res = await db.execute(q_total)
    total_row = total_res.first()
    total_tokens = total_row[0] if total_row and total_row[0] else 0
    total_cost = total_row[1] if total_row and total_row[1] else 0

    # 2. Breakdown by model
    q_breakdown = select(
        UsageLedgerEntry.model,
        func.sum(UsageLedgerEntry.tokens_used),
        func.sum(UsageLedgerEntry.cost)
    ).where(UsageLedgerEntry.account_id == account_id).group_by(UsageLedgerEntry.model)
    
    breakdown_res = await db.execute(q_breakdown)
    
    breakdown = []
    for row in breakdown_res.all():
        breakdown.append(ModelBreakdown(
            model=row[0],
            tokens_used=row[1] if row[1] else 0,
            cost=row[2] if row[2] else 0
        ))

    return {
        "account_id": account_id,
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "breakdown": breakdown
    }

@router.get("/quota-check/{account_id}")
async def check_quota(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Synchronous quota verification endpoint for the AI service.
    """
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    
    with redis.Redis(host=redis_host, port=redis_port, decode_responses=True) as r:
        # 1. Read Redis counter
        redis_key = f"usage:tokens:{account_id}"
        tokens_used = r.get(redis_key)
        if tokens_used is None:
            # Default to 0 if not present, reconciler will sync it
            tokens_used = 0
        else:
            tokens_used = int(tokens_used)
        
    # 2. Get plan tier and quota
    plan_tier = await fetch_account_plan_tier(account_id)
    quota = PLAN_QUOTAS.get(plan_tier, 10000)
    
    allowed = tokens_used < quota
    
    return {
        "account_id": account_id,
        "tokens_used": tokens_used,
        "quota": quota,
        "allowed": allowed
    }
