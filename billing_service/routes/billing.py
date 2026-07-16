import uuid
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
import stripe

from core.database import SessionLocal
from models.models import Subscription, Invoice, OutboxEvent, Refund
from schemas.schemas import CheckoutSessionRequest, CheckoutSessionResponse, InvoiceOut

router = APIRouter(prefix="/billing", tags=["billing"])

async def get_db():
    async with SessionLocal() as session:
        yield session

# Helper dependencies to extract gateway headers
def get_user_id(x_user_id: str = Header(None)):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header missing")
    return uuid.UUID(x_user_id)

def get_account_id(x_account_id: str = Header(None)):
    if not x_account_id:
        raise HTTPException(status_code=400, detail="X-Account-Id header missing")
    return uuid.UUID(x_account_id)

def get_user_role(x_user_role: str = Header(None)):
    return x_user_role

@router.post("/checkout", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    payload: CheckoutSessionRequest,
    account_id: uuid.UUID = Depends(get_account_id),
    role: str = Depends(get_user_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate a Stripe Checkout Session for subscription upgrades.
    Only Owner can purchase or upgrade billing.
    """
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only the workspace owner can manage billing")

    # Find subscription record
    q = select(Subscription).where(Subscription.account_id == account_id)
    res = await db.execute(q)
    sub = res.scalar_one_or_none()
    
    if not sub:
        raise HTTPException(status_code=404, detail="Workspace subscription not initialized")

    plan_tier = payload.plan_tier.lower()
    is_pack = plan_tier.startswith("credits_")
    
    if not is_pack and plan_tier not in ["pro", "team"]:
        raise HTTPException(status_code=400, detail="Invalid plan tier specified")

    if is_pack:
        if plan_tier == "credits_100":
            amount = 500
        elif plan_tier == "credits_500":
            amount = 2000
        elif plan_tier == "credits_1000":
            amount = 3500
        else:
            raise HTTPException(status_code=400, detail="Invalid credit pack specified")
    else:
        amount = 1900 if plan_tier == "pro" else 4900 # $19.00 or $49.00

    try:
        # Create Stripe Checkout Session
        if is_pack:
            session = stripe.checkout.Session.create(
                customer=sub.stripe_customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': f'CreditFlow {plan_tier.replace("credits_", "")} Credits Pack',
                            'description': f'One-time purchase of additional {plan_tier.replace("credits_", "")} credits.',
                        },
                        'unit_amount': amount,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url='http://localhost:3000/dashboard?billing=success',
                cancel_url='http://localhost:3000/dashboard?billing=cancel',
                client_reference_id=str(account_id),
                metadata={
                    "plan_tier": plan_tier,
                    "account_id": str(account_id)
                }
            )
        else:
            session = stripe.checkout.Session.create(
                customer=sub.stripe_customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': f'CreditFlow {plan_tier.title()} Subscription',
                            'description': f'Access to {plan_tier.title()} tier features and monthly credits.',
                        },
                        'unit_amount': amount,
                        'recurring': {
                            'interval': 'month',
                        },
                    },
                    'quantity': 1,
                }],
                mode='subscription',
                success_url='http://localhost:3000/dashboard?billing=success',
                cancel_url='http://localhost:3000/dashboard?billing=cancel',
                client_reference_id=str(account_id),
                metadata={
                    "plan_tier": plan_tier,
                    "account_id": str(account_id)
                }
            )
        return {"checkout_url": session.url}
    except Exception as e:
        # Fallback to local sandbox mock URL in case API keys are invalid or Stripe is down
        mock_url = f"http://localhost:3000/dashboard?mock_checkout=true&account_id={account_id}&plan_tier={plan_tier}"
        logger_msg = f"Stripe Checkout creation failed ({e}). Falling back to local mock URL."
        import logging
        logging.getLogger("billing_service").warning(logger_msg)
        return {"checkout_url": mock_url}

@router.get("/invoices", response_model=List[InvoiceOut])
async def list_invoices(
    account_id: uuid.UUID = Depends(get_account_id),
    role: str = Depends(get_user_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Get payment history for the active workspace.
    """
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only owners can view workspace invoices")
        
    q = select(Invoice).where(Invoice.account_id == account_id).order_by(Invoice.created_at.desc())
    res = await db.execute(q)
    return res.scalars().all()

@router.post("/webhook/stripe")
async def handle_stripe_webhook_direct(
    payload: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    Directly receive verified & normalized webhook payloads forwarded from API Gateway.
    Saves state and writes to outbox inside a single transaction.
    """
    event_type = payload.get("event_type")
    body = payload.get("body", {})
    
    if event_type == "invoice.paid":
        account_id_str = body.get("account_id")
        customer_id = body.get("customer_id")
        subscription_id = body.get("subscription_id")
        plan_tier = body.get("plan_tier", "pro")
        amount_paid = body.get("amount_paid", 1900)
        
        async with db.begin():
            # Resolve account_id
            if account_id_str:
                account_id = uuid.UUID(account_id_str)
            else:
                q = select(Subscription).where(Subscription.stripe_customer_id == customer_id)
                res = await db.execute(q)
                sub = res.scalar_one_or_none()
                if sub:
                    account_id = sub.account_id
                else:
                    raise HTTPException(status_code=400, detail="Cannot resolve account")
            
            # Update subscription (only if not a credit pack purchase)
            if not plan_tier.startswith("credits_"):
                q = select(Subscription).where(Subscription.account_id == account_id).with_for_update()
                res = await db.execute(q)
                sub = res.scalar_one_or_none()
                if sub:
                    sub.plan_tier = plan_tier
                    sub.status = "active"
                    sub.stripe_subscription_id = subscription_id
                    from datetime import datetime, timedelta
                    sub.current_period_end = datetime.utcnow() + timedelta(days=30)
            
            # Save invoice
            invoice = Invoice(
                account_id=account_id,
                stripe_invoice_id=subscription_id or f"inv_mock_{uuid.uuid4().hex[:12]}",
                amount=amount_paid,
                status="paid"
            )
            db.add(invoice)
            
            # Outbox write
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
            db.add(outbox)
            
    elif event_type == "payment.failed":
        customer_id = body.get("customer_id")
        subscription_id = body.get("subscription_id")
        amount_due = body.get("amount_due", 0)
        
        async with db.begin():
            q = select(Subscription).where(Subscription.stripe_customer_id == customer_id).with_for_update()
            res = await db.execute(q)
            sub = res.scalar_one_or_none()
            if sub:
                sub.status = "past_due"
                account_id = sub.account_id
                
                # Outbox write
                outbox = OutboxEvent(
                    event_id=str(uuid.uuid4()),
                    exchange="billing_events",
                    routing_key="payment.failed",
                    payload={
                        "account_id": str(account_id),
                        "customer_id": customer_id,
                        "subscription_id": subscription_id,
                        "amount_due": amount_due
                    }
                )
                db.add(outbox)
                
    return {"status": "success"}

@router.post("/refund")
async def issue_refund(
    payload: dict,
    role: str = Depends(get_user_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin endpoint to trigger a manual subscription refund and publish refund.issued.
    """
    if role not in ["admin", "owner", "superadmin"]:
        raise HTTPException(status_code=403, detail="Unauthorized")
        
    account_id_str = payload.get("account_id")
    amount = payload.get("amount", 0)
    
    if not account_id_str:
         raise HTTPException(status_code=400, detail="account_id missing")
         
    async with db.begin():
        account_id = uuid.UUID(account_id_str)
        
        # Save Refund record
        refund_rec = Refund(
            account_id=account_id,
            invoice_id=None,
            amount=amount,
            reason="admin_manual_refund"
        )
        db.add(refund_rec)
        
        outbox = OutboxEvent(
            event_id=str(uuid.uuid4()),
            exchange="billing_events",
            routing_key="refund.issued",
            payload={
                "account_id": str(account_id),
                "amount": amount
            }
        )
        db.add(outbox)
        
    return {"status": "refund_queued", "account_id": account_id_str, "amount": amount}
