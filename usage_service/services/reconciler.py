import asyncio
import logging
import os
import redis
from sqlalchemy.future import select
from sqlalchemy import func
from core.database import SessionLocal
from models.models import UsageLedgerEntry

logger = logging.getLogger("usage_service.reconciler")

async def start_reconciler():
    """
    Periodic job that reconciles Redis quota counters with actual Postgres values.
    Runs every 5 minutes to prevent counter drift.
    """
    logger.info("Initializing usage counter reconciler...")
    
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    
    while True:
        try:
            r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
            r.ping()
            break
        except Exception as e:
            logger.warning(f"Redis not ready in reconciler: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

    logger.info("Usage reconciler started.")

    while True:
        try:
            async with SessionLocal() as session:
                # 1. Fetch total tokens used per account
                query = select(
                    UsageLedgerEntry.account_id,
                    func.sum(UsageLedgerEntry.tokens_used)
                ).group_by(UsageLedgerEntry.account_id)
                
                result = await session.execute(query)
                
                # 2. Sync to Redis
                for row in result.all():
                    account_id, total_tokens = row
                    redis_key = f"usage:tokens:{account_id}"
                    r.set(redis_key, str(total_tokens))
                    logger.info(f"Reconciled Redis key {redis_key} to {total_tokens} tokens")
                    
        except Exception as e:
            logger.error(f"Error in counter reconciler loop: {e}", exc_info=True)
            
        await asyncio.sleep(300) # Run every 5 minutes
