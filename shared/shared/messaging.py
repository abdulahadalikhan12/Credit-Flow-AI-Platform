import json
import logging
import uuid
import os
from typing import Callable, Any, Dict, Awaitable
import aio_pika
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy.sql import text

logger = logging.getLogger("shared.messaging")

class RabbitMQClient:
    def __init__(self):
        user = os.getenv("RABBITMQ_USER", "guest")
        password = os.getenv("RABBITMQ_PASS", "guest")
        host = os.getenv("RABBITMQ_HOST", "rabbitmq")
        port = os.getenv("RABBITMQ_PORT", "5672")
        self.amqp_url = f"amqp://{user}:{password}@{host}:{port}/"
        self.connection: Any = None
        self.channel: Any = None

    async def connect(self):
        """
        Establish connection to RabbitMQ broker and open a channel with publisher confirms.
        """
        logger.info("Connecting to RabbitMQ...")
        self.connection = await aio_pika.connect_robust(self.amqp_url)
        self.channel = await self.connection.channel()
        # Enable publisher confirms
        await self.channel.confirm_delivery()
        logger.info("Connected to RabbitMQ with publisher confirms enabled")

    async def declare_exchange(self, name: str, type: str = "topic") -> aio_pika.Exchange:
        """
        Declare a durable topic exchange.
        """
        return await self.channel.declare_exchange(name, type, durable=True)

    async def declare_queue(self, name: str, dlx_exchange: str = "dlx", dlx_routing_key: str = "dead_letter") -> aio_pika.Queue:
        """
        Declare a queue bound to a Dead Letter Exchange (DLX) with a dead-letter queue.
        """
        # Declare DLX and DLQ
        dlx = await self.channel.declare_exchange(dlx_exchange, "direct", durable=True)
        dlq = await self.channel.declare_queue(f"{name}_dlq", durable=True)
        await dlq.bind(dlx, routing_key=dlx_routing_key)

        # Declare main queue pointing to DLX
        arguments = {
            "x-dead-letter-exchange": dlx_exchange,
            "x-dead-letter-routing-key": dlx_routing_key
        }
        queue = await self.channel.declare_queue(name, durable=True, arguments=arguments)
        return queue

    async def publish(self, exchange_name: str, routing_key: str, body: Dict[str, Any], event_id: str = None) -> str:
        """
        Publish persistent message with a generated or passed event_id.
        """
        if not event_id:
            event_id = str(uuid.uuid4())

        if not self.channel:
            await self.connect()

        exchange = await self.declare_exchange(exchange_name)

        payload = {
            "event_id": event_id,
            "routing_key": routing_key,
            "body": body
        }

        message = aio_pika.Message(
            body=json.dumps(payload).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json"
        )

        await exchange.publish(message, routing_key=routing_key)
        logger.info(f"Published event {event_id} to exchange '{exchange_name}' with routing key '{routing_key}'")
        return event_id

class NoopTransaction:
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

async def process_event_idempotently(
    session_maker: async_sessionmaker[AsyncSession],
    event_id: str,
    handler_func: Callable[[AsyncSession, Dict[str, Any]], Awaitable[Any]],
    event_body: Dict[str, Any]
) -> bool:
    """
    Checks processed_events table and executes handler inside the database transaction.
    Returns True if already processed (skipped), False if processed successfully.
    """
    async with session_maker() as session:
        async with session.begin():
            # Check if event has already been processed
            query = text("SELECT 1 FROM processed_events WHERE event_id = :event_id FOR UPDATE")
            result = await session.execute(query, {"event_id": event_id})
            if result.fetchone() is not None:
                logger.info(f"Event {event_id} already processed. Skipping.")
                return True

            # Mark as processed
            insert_query = text("INSERT INTO processed_events (event_id, processed_at) VALUES (:event_id, NOW())")
            await session.execute(insert_query, {"event_id": event_id})

            # Override session.begin and session.commit to be a no-op since we are already in a transaction
            original_begin = session.begin
            session.begin = lambda: NoopTransaction()
            
            async def noop_commit():
                pass
            original_commit = session.commit
            session.commit = noop_commit
            
            try:
                # Execute business handler inside the same transaction
                await handler_func(session, event_body)
            finally:
                session.begin = original_begin
                session.commit = original_commit
                
    return False
