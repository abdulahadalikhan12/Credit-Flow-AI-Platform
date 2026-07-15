import asyncio
import logging
from sqlalchemy.future import select
from core.database import SessionLocal
from models.models import OutboxEvent
from shared.messaging import RabbitMQClient

logger = logging.getLogger("billing_service.outbox_publisher")

async def start_outbox_publisher():
    """
    Background worker that queries the DB for unpublished events, 
    publishes them to RabbitMQ, and marks them as published.
    """
    logger.info("Initializing Transactional Outbox publisher...")
    rabbitmq = RabbitMQClient()
    
    while True:
        try:
            await rabbitmq.connect()
            break
        except Exception as e:
            logger.warning(f"RabbitMQ connection failed in outbox worker: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

    logger.info("Transactional Outbox publisher started.")

    while True:
        try:
            async with SessionLocal() as session:
                # Fetch up to 20 unpublished events
                query = select(OutboxEvent).where(OutboxEvent.published.is_(False)).limit(20)
                result = await session.execute(query)
                events = result.scalars().all()

                if events:
                    logger.info(f"Found {len(events)} unpublished outbox events. Publishing...")
                    for event in events:
                        try:
                            # Publish to RabbitMQ
                            await rabbitmq.publish(
                                exchange_name=event.exchange,
                                routing_key=event.routing_key,
                                body=event.payload,
                                event_id=event.event_id
                            )
                            event.published = True
                        except Exception as pub_err:
                            logger.error(f"Failed to publish event {event.event_id} due to: {pub_err}")
                            # Keep published = False to retry on next loop
                    
                    # Save changes
                    await session.commit()
                    logger.info("Outbox events updated in database.")
                    
        except Exception as loop_err:
            logger.error(f"Error in outbox publisher loop: {loop_err}", exc_info=True)
            
        await asyncio.sleep(2.0)
