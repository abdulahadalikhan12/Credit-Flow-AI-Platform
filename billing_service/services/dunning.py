import asyncio
import logging
import datetime
import uuid
from sqlalchemy.future import select
from core.database import SessionLocal
from models.models import Subscription, OutboxEvent

logger = logging.getLogger("billing_service.dunning")

async def start_dunning_reconciler():
    """
    Background job that checks for subscriptions in 'past_due' status.
    If the grace period has expired, it automatically downgrades the plan to 'free'.
    """
    logger.info("Initializing dunning grace-period checker...")
    
    # Grace period defaults to 3 days (259200 seconds), or 60 seconds for mock/test subscriptions
    grace_seconds = 259200
    
    while True:
        try:
            async with SessionLocal() as session:
                async with session.begin():
                    # Find all past_due subscriptions and lock the rows to prevent double processing
                    q = select(Subscription).where(Subscription.status == "past_due").with_for_update()
                    res = await session.execute(q)
                    subs = res.scalars().all()
                    
                    now = datetime.datetime.utcnow()
                    for sub in subs:
                        elapsed = (now - sub.updated_at).total_seconds()
                        
                        # Decide limit: 60s for mock, 3 days for real stripe subscriptions
                        is_mock = not sub.stripe_subscription_id or sub.stripe_subscription_id.startswith("sub_mock")
                        limit = 60 if is_mock else grace_seconds
                        
                        if elapsed >= limit:
                            logger.info(f"Dunning period expired for account {sub.account_id} (elapsed: {elapsed}s). Downgrading to free.")
                            sub.plan_tier = "free"
                            sub.status = "active"
                            
                            # Queue outbox event to propagate subscription downgrade
                            outbox = OutboxEvent(
                                event_id=str(uuid.uuid4()),
                                exchange="billing_events",
                                routing_key="subscription.downgraded",
                                payload={
                                    "account_id": str(sub.account_id),
                                    "plan_tier": "free",
                                    "reason": "dunning_failed"
                                }
                            )
                            session.add(outbox)
        except Exception as e:
            logger.error(f"Error in dunning reconciler loop: {e}", exc_info=True)
            
        await asyncio.sleep(10) # check every 10 seconds
