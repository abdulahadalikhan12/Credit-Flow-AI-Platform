import asyncio
import json
import logging
import uuid
from sqlalchemy.future import select
from shared.messaging import RabbitMQClient, process_event_idempotently
from models.models import Content, ContentVersion
from core.database import SessionLocal

logger = logging.getLogger("content_service.consumer")

async def handle_ai_completed(session, body):
    """
    On AI text generation completion, automatically save the generated text 
    as a new draft Content item in the workspace.
    """
    account_id_str = body.get("account_id")
    prompt = body.get("prompt", "")
    response = body.get("response", "")
    model = body.get("model", "")
    
    if not account_id_str or not response:
        return
        
    # Ignore image generation events for creating text draft posts directly
    if "image" in model:
        logger.info("Ignoring image completion event for draft post creation.")
        return
        
    account_id = uuid.UUID(account_id_str)
    
    # 1. Deduce a title (first 30 characters of the prompt or fallback)
    title = prompt[:40] + "..." if len(prompt) > 40 else prompt
    if not title:
        title = f"AI Draft Post ({model})"

    # SYSTEM user ID placeholder
    system_user_id = uuid.UUID(int=0)

    # 2. Create content draft
    content = Content(
        account_id=account_id,
        title=title,
        body=response,
        image_url=None,
        status="draft",
        created_by=system_user_id
    )
    session.add(content)
    await session.flush() # get content.id

    # 3. Create version record
    version = ContentVersion(
        content_id=content.id,
        body=response,
        image_url=None,
        version=1,
        created_by=system_user_id
    )
    session.add(version)
    logger.info(f"Automatically created AI draft post {content.id} for account {account_id}")

async def start_consumer():
    rabbitmq = RabbitMQClient()
    
    while True:
        try:
            await rabbitmq.connect()
            break
        except Exception as e:
            logger.warning(f"RabbitMQ connection failed in content consumer: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

    queue = await rabbitmq.declare_queue("content_service_queue")
    ai_ex = await rabbitmq.declare_exchange("ai_events")
    await queue.bind(ai_ex, routing_key="ai.generation_completed")

    logger.info("Content Service background consumer started.")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                try:
                    payload = json.loads(message.body.decode())
                    event_id = payload["event_id"]
                    routing_key = payload["routing_key"]
                    body = payload["body"]
                    
                    logger.info(f"Content consumer received event: {routing_key} ({event_id})")
                    
                    if routing_key == "ai.generation_completed":
                        await process_event_idempotently(
                            SessionLocal, event_id, handle_ai_completed, body
                        )
                except Exception as e:
                    logger.error(f"Error handling content queue event: {e}", exc_info=True)
