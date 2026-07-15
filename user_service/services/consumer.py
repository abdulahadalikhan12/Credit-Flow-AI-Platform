import asyncio
import json
import logging
import uuid
from sqlalchemy.future import select
from shared.messaging import RabbitMQClient, process_event_idempotently
from models.models import Account, AccountMember
from core.database import SessionLocal

logger = logging.getLogger("user_service.consumer")

async def handle_user_registered(session, body):
    """
    On user signup, automatically create an 'individual' Account for the user and make them the Owner.
    """
    user_id_str = body["user_id"]
    email = body["email"]
    user_id = uuid.UUID(user_id_str)
    
    # 1. Check if user already has an individual account (to enforce idempotency at model level too)
    q = select(AccountMember).join(Account).where(AccountMember.user_id == user_id, Account.type == "individual")
    res = await session.execute(q)
    if res.scalar_one_or_none():
        logger.info(f"User {user_id} already has an individual account. Skipping.")
        return

    # 2. Create default individual Account
    account = Account(
        id=user_id,
        name=f"{email.split('@')[0]}'s Workspace",
        type="individual",
        plan_tier="free"
    )
    session.add(account)
    await session.flush() # get account.id

    # 3. Bind user as Owner
    member = AccountMember(
        account_id=account.id,
        user_id=user_id,
        role="owner"
    )
    session.add(member)
    logger.info(f"Created default individual workspace {account.id} for user {user_id}")

    # Emit account.created event
    rabbitmq = RabbitMQClient()
    await rabbitmq.publish(
        exchange_name="user_events",
        routing_key="account.created",
        body={
            "account_id": str(user_id),
            "name": f"{email.split('@')[0]}'s Workspace",
            "type": "individual",
            "owner_id": str(user_id)
        }
    )

async def handle_invoice_paid(session, body):
    """
    On successful subscription payment, update the workspace plan tier.
    """
    account_id_str = body.get("account_id")
    plan_tier = body.get("plan_tier")
    if not account_id_str or not plan_tier:
        logger.warning("Invoice paid event payload missing account_id or plan_tier")
        return

    account_id = uuid.UUID(account_id_str)
    q = select(Account).where(Account.id == account_id)
    res = await session.execute(q)
    account = res.scalar_one_or_none()
    if account:
        account.plan_tier = plan_tier
        logger.info(f"Upgraded account {account_id} plan tier to {plan_tier}")
    else:
        logger.error(f"Invoice paid received for non-existent account {account_id}")

async def start_consumer():
    """
    Connect to RabbitMQ, declare queues, bind exchanges, and process incoming events asynchronously.
    """
    logger.info("Initializing RabbitMQ consumer for User Service...")
    rabbitmq = RabbitMQClient()
    
    # Keep retrying connection in case RabbitMQ is booting up
    while True:
        try:
            await rabbitmq.connect()
            break
        except Exception as e:
            logger.warning(f"RabbitMQ connection failed: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
            
    # Declare queue
    queue = await rabbitmq.declare_queue("user_service_queue")

    # Bind auth_events.user.registered
    auth_exchange = await rabbitmq.declare_exchange("auth_events")
    await queue.bind(auth_exchange, routing_key="user.registered")

    # Bind billing_events.invoice.paid
    billing_exchange = await rabbitmq.declare_exchange("billing_events")
    await queue.bind(billing_exchange, routing_key="invoice.paid")

    logger.info("RabbitMQ consumer for User Service started. Waiting for messages...")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                try:
                    payload = json.loads(message.body.decode())
                    event_id = payload["event_id"]
                    routing_key = payload["routing_key"]
                    body = payload["body"]
                    
                    logger.info(f"Received event '{routing_key}' with ID '{event_id}'")
                    
                    if routing_key == "user.registered":
                        await process_event_idempotently(
                            SessionLocal, event_id, handle_user_registered, body
                        )
                    elif routing_key == "invoice.paid":
                        await process_event_idempotently(
                            SessionLocal, event_id, handle_invoice_paid, body
                        )
                except Exception as e:
                    logger.error(f"Error handling user queue message: {e}", exc_info=True)
