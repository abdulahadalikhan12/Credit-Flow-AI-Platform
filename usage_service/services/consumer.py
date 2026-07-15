import asyncio
import json
import logging
import uuid
import os
import redis
import httpx
from shared.messaging import RabbitMQClient, process_event_idempotently
from models.models import UsageLedgerEntry
from core.database import SessionLocal

logger = logging.getLogger("usage_service.consumer")

# Quota limits (in tokens)
PLAN_QUOTAS = {
    "free": 10000,
    "pro": 500000,
    "team": 5000000
}

async def fetch_account_plan_tier(account_id: uuid.UUID) -> str:
    """Fetch the workspace plan tier from User Service."""
    user_service_url = os.getenv("USER_SERVICE_URL", "http://user_service:8002")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{user_service_url}/api/v1/accounts/profile", headers={"X-Account-Id": str(account_id)}, timeout=3.0)
            if response.status_code == 200:
                data = response.json()
                return data.get("plan_tier", "free").lower()
    except Exception as e:
        logger.error(f"Error fetching plan tier for account {account_id}: {e}")
    return "free"

async def handle_ai_completed(session, body):
    """
    Log actual token usage to SQL ledger and update Redis counter.
    Emits alerts if quota limits are crossed.
    """
    account_id_str = body.get("account_id")
    tokens_used = body.get("tokens_used", 0)
    credits_cost = body.get("credits_cost", 0)
    model = body.get("model", "unknown")
    
    if not account_id_str or tokens_used <= 0:
        return
        
    account_id = uuid.UUID(account_id_str)
    
    # 1. Log to Database
    entry = UsageLedgerEntry(
        account_id=account_id,
        tokens_used=tokens_used,
        cost=credits_cost,
        model=model
    )
    session.add(entry)
    
    # 2. Increment Redis Counter
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    
    with redis.Redis(host=redis_host, port=redis_port, decode_responses=True) as r:
        redis_key = f"usage:tokens:{account_id}"
        new_total = r.incrby(redis_key, tokens_used)
    
    # 3. Check Quota Thresholds
    plan_tier = await fetch_account_plan_tier(account_id)
    quota = PLAN_QUOTAS.get(plan_tier, 10000)
    
    pct_before = (new_total - tokens_used) / quota
    pct_after = new_total / quota
    
    # Check if crossed 80% or 100% threshold
    threshold_crossed = None
    if pct_before < 0.8 <= pct_after:
        threshold_crossed = 80
    elif pct_before < 1.0 <= pct_after:
        threshold_crossed = 100
        
    if threshold_crossed:
        logger.warning(f"Account {account_id} crossed {threshold_crossed}% usage threshold ({new_total}/{quota} tokens)")
        rabbitmq = RabbitMQClient()
        await rabbitmq.publish(
            exchange_name="usage_events",
            routing_key="usage.threshold_reached",
            body={
                "account_id": str(account_id),
                "threshold": threshold_crossed,
                "total_used": new_total,
                "quota": quota
            }
        )

async def start_consumer():
    rabbitmq = RabbitMQClient()
    
    while True:
        try:
            await rabbitmq.connect()
            break
        except Exception as e:
            logger.warning(f"RabbitMQ connection failed in usage consumer: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

    queue = await rabbitmq.declare_queue("usage_service_queue")
    ai_ex = await rabbitmq.declare_exchange("ai_events")
    await queue.bind(ai_ex, routing_key="ai.generation_completed")

    logger.info("Usage Service background event consumer started.")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            try:
                payload = json.loads(message.body.decode())
                event_id = payload.get("event_id")
                routing_key = payload.get("routing_key")
                body = payload.get("body", {})
                
                logger.info(f"Usage consumer received event: {routing_key} ({event_id})")
                
                if routing_key == "ai.generation_completed":
                    await process_event_idempotently(
                        SessionLocal, event_id, handle_ai_completed, body
                    )
                
                await message.ack()
            except Exception as e:
                logger.error(f"Error handling usage queue event: {e}", exc_info=True)
                if message.redelivered:
                    logger.error(f"Usage event processing failed twice. Rejecting to DLQ: {message.body.decode()}")
                    await message.reject(requeue=False)
                else:
                    logger.warning("Usage event processing failed. Requeuing for retry.")
                    await message.reject(requeue=True)
