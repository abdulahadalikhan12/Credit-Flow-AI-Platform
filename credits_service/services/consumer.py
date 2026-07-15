import asyncio
import json
import logging
import uuid
from sqlalchemy.future import select
from sqlalchemy import func
from shared.messaging import RabbitMQClient, process_event_idempotently
from models.models import CreditLedgerEntry
from core.database import SessionLocal

logger = logging.getLogger("credits_service.consumer")

async def get_current_balance(session, account_id: uuid.UUID) -> int:
    q = select(func.sum(CreditLedgerEntry.amount)).where(CreditLedgerEntry.account_id == account_id)
    res = await session.execute(q)
    balance = res.scalar()
    return balance if balance is not None else 0

async def handle_invoice_paid(session, body):
    """
    Grant credits when a successful checkout/invoice occurs.
    """
    account_id_str = body.get("account_id")
    plan_tier = body.get("plan_tier", "free").lower()
    
    if not account_id_str:
        return
        
    account_id = uuid.UUID(account_id_str)
    
    # Determine credit amount based on tier
    # Free = 100, Pro = 1000, Team = 5000
    credit_amount = 100
    if plan_tier == "pro":
        credit_amount = 1000
    elif plan_tier == "team":
        credit_amount = 5000

    entry = CreditLedgerEntry(
        account_id=account_id,
        amount=credit_amount,
        transaction_type="grant",
        description=f"Monthly subscription grant for {plan_tier} tier"
    )
    session.add(entry)
    logger.info(f"Granted {credit_amount} credits to account {account_id} ({plan_tier})")

async def handle_refund_issued(session, body):
    """
    Claw back credits if a refund was issued.
    Maps Stripe cents to credit equivalent limits to prevent overcharging.
    """
    account_id_str = body.get("account_id")
    amount_cents = body.get("amount", 0)
    
    if not account_id_str:
        return
        
    account_id = uuid.UUID(account_id_str)
    
    if amount_cents >= 4900:
        credit_clawback = 5000
    elif amount_cents >= 1900:
        credit_clawback = 1000
    else:
        # Fallback or partial refund estimation: 1 credit per 1.9 cents
        credit_clawback = int(amount_cents / 1.9)
    
    entry = CreditLedgerEntry(
        account_id=account_id,
        amount=-credit_clawback,
        transaction_type="refund",
        description=f"Subscription refund clawback for {amount_cents} cents"
    )
    session.add(entry)
    logger.info(f"Clawed back {credit_clawback} credits from account {account_id} (refund: {amount_cents} cents)")

async def handle_ai_completed(session, body):
    """
    Debit credits for consumed AI generation calls.
    """
    account_id_str = body.get("account_id")
    credits_cost = body.get("credits_cost", 1) # default 1 credit
    model = body.get("model", "unknown")
    job_id = body.get("job_id", "unknown")
    
    if not account_id_str:
        return
        
    account_id = uuid.UUID(account_id_str)
    
    # Add debit entry
    entry = CreditLedgerEntry(
        account_id=account_id,
        amount=-credits_cost,
        transaction_type="debit",
        description=f"AI Completion ({model}) - Job {job_id}"
    )
    session.add(entry)
    logger.info(f"Debited {credits_cost} credits from account {account_id} for AI completion")
    
    # Check if balance is low (e.g. below 20 credits) and publish event
    await session.flush()
    balance = await get_current_balance(session, account_id)
    if balance < 20:
        logger.warning(f"Account {account_id} is running low on credits: {balance}")
        rabbitmq = RabbitMQClient()
        await rabbitmq.publish(
            exchange_name="credits_events",
            routing_key="credits.low_balance",
            body={"account_id": str(account_id), "balance": balance}
        )

async def start_consumer():
    rabbitmq = RabbitMQClient()
    
    while True:
        try:
            await rabbitmq.connect()
            break
        except Exception as e:
            logger.warning(f"RabbitMQ connection failed in credits consumer: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

    queue = await rabbitmq.declare_queue("credits_service_queue")

    # Bind to billing events
    billing_ex = await rabbitmq.declare_exchange("billing_events")
    await queue.bind(billing_ex, routing_key="invoice.paid")
    await queue.bind(billing_ex, routing_key="refund.issued")

    # Bind to AI completed events
    ai_ex = await rabbitmq.declare_exchange("ai_events")
    await queue.bind(ai_ex, routing_key="ai.generation_completed")

    logger.info("Credits Service consumer started.")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            try:
                payload = json.loads(message.body.decode())
                event_id = payload.get("event_id")
                routing_key = payload.get("routing_key")
                body = payload.get("body", {})
                
                logger.info(f"Credits consumer received event: {routing_key} ({event_id})")
                
                if routing_key == "invoice.paid":
                    await process_event_idempotently(
                        SessionLocal, event_id, handle_invoice_paid, body
                    )
                elif routing_key == "refund.issued":
                    await process_event_idempotently(
                        SessionLocal, event_id, handle_refund_issued, body
                    )
                elif routing_key == "ai.generation_completed":
                    await process_event_idempotently(
                        SessionLocal, event_id, handle_ai_completed, body
                    )
                
                await message.ack()
            except Exception as e:
                logger.error(f"Error handling credits queue event: {e}", exc_info=True)
                if message.redelivered:
                    logger.error(f"Credits event processing failed twice. Rejecting to DLQ: {message.body.decode()}")
                    await message.reject(requeue=False)
                else:
                    logger.warning("Credits event processing failed. Requeuing for retry.")
                    await message.reject(requeue=True)
