import asyncio
import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from shared.messaging import RabbitMQClient, process_event_idempotently
from core.database import SessionLocal
from models.models import AuditLog

logger = logging.getLogger("admin_service.consumer")

async def log_event_to_audit_trail(session: AsyncSession, body: dict, routing_key: str, event_id: str):
    """Save event record directly to postgres audit trail."""
    log_entry = AuditLog(
        event_id=event_id,
        routing_key=routing_key,
        payload=body
    )
    session.add(log_entry)
    logger.info(f"Audited event {routing_key} ({event_id})")

async def start_consumer():
    rabbitmq = RabbitMQClient()
    
    while True:
        try:
            await rabbitmq.connect()
            break
        except Exception as e:
            logger.warning(f"RabbitMQ connection failed in admin consumer: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

    queue = await rabbitmq.declare_queue("admin_service_audit_queue")
    
    # List of all topic exchanges to listen to
    exchanges = [
        "auth_events",
        "user_events",
        "billing_events",
        "credits_events",
        "usage_events",
        "ai_events",
        "content_events",
        "scheduler_events",
        "social_events",
        "scraper_events",
        "notification_events"
    ]
    
    for ex_name in exchanges:
        ex = await rabbitmq.declare_exchange(ex_name)
        # Bind using wildcard '#' to get all routing keys
        await queue.bind(ex, routing_key="#")

    logger.info("Admin Service wildcard event auditor started.")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                try:
                    payload = json.loads(message.body.decode())
                    event_id = payload["event_id"]
                    routing_key = payload["routing_key"]
                    body = payload["body"]
                    
                    # Store audit records
                    async with SessionLocal() as session:
                        async with session.begin():
                            # Since this is an audit trail, we record it directly 
                            # (no deduplication needed as we want to log every delivery attempt,
                            # but we can check processed_events if we want strict once-only audit logging).
                            # We will use direct logging to track retry attempts as well.
                            await log_event_to_audit_trail(session, body, routing_key, event_id)
                except Exception as e:
                    logger.error(f"Error executing audit log task: {e}")
