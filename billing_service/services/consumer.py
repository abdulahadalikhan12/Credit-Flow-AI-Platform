import asyncio
import json
import logging
import uuid
import stripe
from datetime import datetime, timedelta
from sqlalchemy.future import select
from shared.messaging import RabbitMQClient, process_event_idempotently
from models.models import Subscription, Invoice, OutboxEvent
from core.database import SessionLocal

logger = logging.getLogger("billing_service.consumer")

async def handle_account_created(session, body):
    """
    Creates a Stripe customer when a new account is registered, 
    and sets up a default 'free' subscription record.
    """
    account_id_str = body.get("account_id")
    name = body.get("name")
    if not account_id_str:
        return

    account_id = uuid.UUID(account_id_str)
    
    # Check if a subscription record already exists
    q = select(Subscription).where(Subscription.account_id == account_id)
    res = await session.execute(q)
    if res.scalar_one_or_none():
        logger.info(f"Subscription already exists for account {account_id}")
        return

    # Provision Stripe customer
    stripe_customer_id = f"cus_mock_{uuid.uuid4().hex[:12]}"
    try:
        customer = stripe.Customer.create(
            name=name,
            metadata={"account_id": str(account_id)}
        )
        stripe_customer_id = customer.id
        logger.info(f"Created real Stripe customer: {stripe_customer_id}")
    except Exception as e:
        logger.warning(f"Failed to create Stripe customer, falling back to mock: {e}")

    # Save subscription info
    sub = Subscription(
        account_id=account_id,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=None,
        plan_tier="free",
        status="active"
    )
    session.add(sub)
    logger.info(f"Initialized free plan subscription for account {account_id}")

async def handle_stripe_invoice_paid(session, body):
    """
    On Stripe invoice payment success, upgrade plan tier and save invoice.
    """
    account_id_str = body.get("account_id")
    customer_id = body.get("customer_id")
    subscription_id = body.get("subscription_id")
    invoice_id = body.get("invoice_id")
    plan_tier = body.get("plan_tier", "pro")
    amount_paid = body.get("amount_paid", 1900)

    # 1. Resolve account_id from Subscription if missing (read-only)
    if account_id_str:
        account_id = uuid.UUID(account_id_str)
    else:
        q = select(Subscription).where(Subscription.stripe_customer_id == customer_id)
        res = await session.execute(q)
        sub = res.scalar_one_or_none()
        if sub:
            account_id = sub.account_id
        else:
            logger.error(f"Cannot resolve account_id for Stripe customer {customer_id}")
            return

    # 2. Update Subscription and create logs inside transaction
    q = select(Subscription).where(Subscription.account_id == account_id).with_for_update()
    res = await session.execute(q)
    sub = res.scalar_one_or_none()
    if sub:
        sub.plan_tier = plan_tier
        sub.status = "active"
        sub.stripe_subscription_id = subscription_id
        sub.current_period_end = datetime.utcnow() + timedelta(days=30)
    
    # Save invoice
    invoice = Invoice(
        account_id=account_id,
        stripe_invoice_id=invoice_id or f"inv_mock_{uuid.uuid4().hex[:12]}",
        amount=amount_paid,
        status="paid"
    )
    session.add(invoice)

    # Save outbox event
    outbox = OutboxEvent(
        event_id=str(uuid.uuid4()),
        exchange="billing_events",
        routing_key="invoice.paid",
        payload={
            "account_id": str(account_id),
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "plan_tier": plan_tier,
            "amount_paid": amount_paid
        }
    )
    session.add(outbox)
    logger.info(f"Stripe invoice paid parsed: updated subscription and queued outbox for account {account_id}")

async def handle_stripe_payment_failed(session, body):
    """
    On Stripe payment failed, downgrade/suspend status.
    """
    customer_id = body.get("customer_id")
    subscription_id = body.get("subscription_id")
    amount_due = body.get("amount_due", 0)

    # Resolve account_id
    q = select(Subscription).where(Subscription.stripe_customer_id == customer_id).with_for_update()
    res = await session.execute(q)
    sub = res.scalar_one_or_none()
    if not sub:
        logger.error(f"Payment failed received for unknown customer: {customer_id}")
        return

    sub.status = "past_due"

    outbox = OutboxEvent(
        event_id=str(uuid.uuid4()),
        exchange="billing_events",
        routing_key="payment.failed",
        payload={
            "account_id": str(sub.account_id),
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "amount_due": amount_due
        }
    )
    session.add(outbox)
    logger.info(f"Stripe payment failed parsed: updated subscription and queued outbox for account {sub.account_id}")

async def start_consumer():
    """
    Connect to RabbitMQ and consume user workspace events.
    """
    rabbitmq = RabbitMQClient()
    
    while True:
        try:
            await rabbitmq.connect()
            break
        except Exception as e:
            logger.warning(f"RabbitMQ connection failed in billing consumer: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

    queue = await rabbitmq.declare_queue("billing_service_queue")
    user_exchange = await rabbitmq.declare_exchange("user_events")
    await queue.bind(user_exchange, routing_key="account.created")

    # Bind Stripe Webhooks
    billing_exchange = await rabbitmq.declare_exchange("billing_events")
    await queue.bind(billing_exchange, routing_key="stripe.webhook.invoice_paid")
    await queue.bind(billing_exchange, routing_key="stripe.webhook.payment_failed")

    logger.info("Billing Service background event consumer started.")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            try:
                payload = json.loads(message.body.decode())
                event_id = payload.get("event_id")
                routing_key = payload.get("routing_key")
                body = payload.get("body", {})
                
                logger.info(f"Billing consumer received event: {routing_key} ({event_id})")
                
                if routing_key == "account.created":
                    await process_event_idempotently(
                        SessionLocal, event_id, handle_account_created, body
                    )
                elif routing_key == "stripe.webhook.invoice_paid":
                    await process_event_idempotently(
                        SessionLocal, event_id, handle_stripe_invoice_paid, body
                    )
                elif routing_key == "stripe.webhook.payment_failed":
                    await process_event_idempotently(
                        SessionLocal, event_id, handle_stripe_payment_failed, body
                    )
                
                await message.ack()
            except Exception as e:
                logger.error(f"Error handling billing event: {e}", exc_info=True)
                if message.redelivered:
                    logger.error(f"Billing event processing failed twice. Rejecting to DLQ: {message.body.decode()}")
                    await message.reject(requeue=False)
                else:
                    logger.warning("Billing event processing failed. Requeuing for retry.")
                    await message.reject(requeue=True)
