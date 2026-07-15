import asyncio
import json
import logging
import os
import resend
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from shared.messaging import RabbitMQClient, process_event_idempotently
from core.database import SessionLocal
from models.models import NotificationLog

logger = logging.getLogger("notification_service.consumer")

# Configure Resend
resend.api_key = os.getenv("RESEND_API_KEY", "re_placeholder")

async def send_resend_email(session: AsyncSession, to_email: str, subject: str, body_html: str) -> str:
    """Send email via Resend API and log to Postgres."""
    sender = os.getenv("EMAIL_SENDER", "onboarding@resend.dev")
    status = "sent"
    
    # Always print simulated email with any links to console for easy local sandbox copy-paste
    import re
    links = re.findall(r'href="([^"]+)"', body_html)
    link_info = f" | Links: {links}" if links else ""
    logger.info(f"[EMAIL OUTBOX SIMULATION] To: {to_email} | Subject: {subject}{link_info}")
    
    # Check if key is placeholders (sandbox testing fallback)
    if not resend.api_key or resend.api_key.startswith("re_placeholder"):
        logger.info(f"Simulated email sent to {to_email} (no API key configured)")
    else:
        try:
            await asyncio.to_thread(
                resend.Emails.send,
                {
                    "from": sender,
                    "to": [to_email],
                    "subject": subject,
                    "html": body_html
                }
            )
            logger.info(f"Email sent successfully to {to_email}")
        except Exception as e:
            logger.error(f"Failed to send Resend email: {e}")
            status = "failed"
            
    # Save log
    log = NotificationLog(
        type="email",
        recipient=to_email,
        subject=subject,
        body=body_html,
        status=status
    )
    session.add(log)
    return status

async def post_slack_webhook(session: AsyncSession, text_msg: str) -> str:
    """Post notice to Slack webhook and log to Postgres."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    status = "sent"
    
    if not webhook_url:
        logger.info(f"[SIMULATED SLACK NOTICE] Text: {text_msg}")
    else:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(webhook_url, json={"text": text_msg}, timeout=5.0)
                if resp.status_code not in [200, 201]:
                    raise Exception(f"Slack webhook returned status code {resp.status_code}")
                logger.info("Slack notification posted successfully.")
        except Exception as e:
            logger.error(f"Failed to post to Slack: {e}")
            status = "failed"
            
    log = NotificationLog(
        type="slack",
        recipient=webhook_url or "mock_channel",
        subject="Slack Alert",
        body=text_msg,
        status=status
    )
    session.add(log)
    return status

# Event Handlers
async def handle_user_registered(session: AsyncSession, body: dict):
    email = body["email"]
    user_id = body["user_id"]
    verification_token = body.get("verification_token", user_id)
    verification_link = f"http://localhost:3000/verify-email?token={verification_token}"
    
    subject = "Verify your email for CreditFlow"
    body_html = f"""
    <h1>Welcome to CreditFlow AI!</h1>
    <p>Please verify your email address to activate your account by clicking the link below:</p>
    <p><a href="{verification_link}">{verification_link}</a></p>
    <p>If you did not sign up, please ignore this email.</p>
    """
    await send_resend_email(session, email, subject, body_html)

async def handle_password_reset(session: AsyncSession, body: dict):
    email = body["email"]
    token = body["token"]
    
    subject = "Reset your CreditFlow password"
    body_html = f"""
    <h1>Password Reset Request</h1>
    <p>You requested a password reset. Use the following 6-digit OTP code to update your password:</p>
    <h2>{token}</h2>
    <p>This code will expire in 1 hour.</p>
    """
    await send_resend_email(session, email, subject, body_html)

async def handle_invoice_paid(session: AsyncSession, body: dict):
    # In a real app, User Service would return the user email. 
    # For simulation, we send notification to a mock customer email or dashboard log
    account_id = body.get("account_id", "Unknown")
    plan = body.get("plan_tier", "free")
    amount = body.get("amount_paid", 0) / 100
    
    subject = f"Invoice Payment Succeeded - CreditFlow Workspace"
    body_html = f"""
    <h1>Payment Received!</h1>
    <p>Thank you! Your workspace payment for the {plan.upper()} plan was successfully processed.</p>
    <p><strong>Amount Paid:</strong> ${amount:.2f}</p>
    <p><strong>Workspace:</strong> {account_id}</p>
    """
    await send_resend_email(session, "billing-recipient@creditflow.local", subject, body_html)

async def handle_payment_failed(session: AsyncSession, body: dict):
    customer = body.get("customer_id", "Unknown")
    amount = body.get("amount_due", 0) / 100
    
    # Email alert
    subject = "Urgent: Payment Failed for CreditFlow"
    body_html = f"<h3>Payment Failed</h3><p>An attempt to charge your card for ${amount:.2f} failed. Please update your billing info.</p>"
    await send_resend_email(session, "billing-recipient@creditflow.local", subject, body_html)
    
    # Slack ops alert
    slack_msg = f"⚠️ [Billing Alert] Payment failed for customer {customer}. Amount: ${amount:.2f}"
    await post_slack_webhook(session, slack_msg)

async def handle_member_invited(session: AsyncSession, body: dict):
    email = body["email"]
    token = body["token"]
    role = body["role"]
    invite_link = f"http://localhost:3000/invite/accept?token={token}"
    
    subject = "You have been invited to join a CreditFlow Workspace"
    body_html = f"""
    <h1>Team Invitation</h1>
    <p>You have been invited to join a CreditFlow workspace as a <strong>{role}</strong>.</p>
    <p>Click the link below to accept the invitation and join your team:</p>
    <p><a href="{invite_link}">{invite_link}</a></p>
    """
    await send_resend_email(session, email, subject, body_html)

async def handle_post_published(session: AsyncSession, body: dict):
    account_id = body.get("account_id")
    post_url = body.get("post_url")
    
    subject = "LinkedIn Post Published Successfully!"
    body_html = f"""
    <h3>Post Published!</h3>
    <p>Your scheduled post was successfully published to LinkedIn.</p>
    <p>View it live here: <a href="{post_url}">{post_url}</a></p>
    """
    await send_resend_email(session, "owner-recipient@creditflow.local", subject, body_html)

async def handle_post_failed(session: AsyncSession, body: dict):
    account_id = body.get("account_id")
    content_id = body.get("content_id")
    reason = body.get("reason", "unknown")
    
    # Email
    subject = "Scheduled Post Failed to Publish"
    body_html = f"<h3>Publishing Failed</h3><p>Your scheduled post (ID: {content_id}) failed to publish due to: <strong>{reason}</strong>.</p>"
    await send_resend_email(session, "owner-recipient@creditflow.local", subject, body_html)
    
    # Slack
    slack_msg = f"❌ [Publishing Failed] Scheduled post {content_id} failed for workspace {account_id}. Reason: {reason}"
    await post_slack_webhook(session, slack_msg)

async def handle_threshold_reached(session: AsyncSession, body: dict):
    account_id = body.get("account_id")
    threshold = body.get("threshold", 80)
    total_used = body.get("total_used")
    quota = body.get("quota")
    
    subject = f"Warning: CreditFlow API Quota crossed {threshold}%"
    body_html = f"""
    <h3>Quota Limit Warning</h3>
    <p>Your workspace {account_id} has consumed {total_used} out of {quota} tokens ({threshold}% of your monthly limit).</p>
    <p>Please upgrade your plan to prevent API interruptions.</p>
    """
    await send_resend_email(session, "owner-recipient@creditflow.local", subject, body_html)

# Background subscriber setup
async def start_consumer():
    rabbitmq = RabbitMQClient()
    
    while True:
        try:
            await rabbitmq.connect()
            break
        except Exception as e:
            logger.warning(f"RabbitMQ connection failed in notification consumer: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

    queue = await rabbitmq.declare_queue("notification_service_queue")
    
    # Bind various exchanges
    auth_ex = await rabbitmq.declare_exchange("auth_events")
    await queue.bind(auth_ex, routing_key="user.registered")
    await queue.bind(auth_ex, routing_key="user.password_reset_requested")

    billing_ex = await rabbitmq.declare_exchange("billing_events")
    await queue.bind(billing_ex, routing_key="invoice.paid")
    await queue.bind(billing_ex, routing_key="payment.failed")

    user_ex = await rabbitmq.declare_exchange("user_events")
    await queue.bind(user_ex, routing_key="member.invited")

    social_ex = await rabbitmq.declare_exchange("social_events")
    await queue.bind(social_ex, routing_key="post.published")
    await queue.bind(social_ex, routing_key="post.failed")

    usage_ex = await rabbitmq.declare_exchange("usage_events")
    await queue.bind(usage_ex, routing_key="usage.threshold_reached")

    logger.info("Notification Service subscriber started. Listening to events...")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                try:
                    payload = json.loads(message.body.decode())
                    event_id = payload["event_id"]
                    routing_key = payload["routing_key"]
                    body = payload["body"]
                    
                    logger.info(f"Notification consumer received event: {routing_key} ({event_id})")
                    
                    if routing_key == "user.registered":
                        await process_event_idempotently(SessionLocal, event_id, handle_user_registered, body)
                    elif routing_key == "user.password_reset_requested":
                        await process_event_idempotently(SessionLocal, event_id, handle_password_reset, body)
                    elif routing_key == "invoice.paid":
                        await process_event_idempotently(SessionLocal, event_id, handle_invoice_paid, body)
                    elif routing_key == "payment.failed":
                        await process_event_idempotently(SessionLocal, event_id, handle_payment_failed, body)
                    elif routing_key == "member.invited":
                        await process_event_idempotently(SessionLocal, event_id, handle_member_invited, body)
                    elif routing_key == "post.published":
                        await process_event_idempotently(SessionLocal, event_id, handle_post_published, body)
                    elif routing_key == "post.failed":
                        await process_event_idempotently(SessionLocal, event_id, handle_post_failed, body)
                    elif routing_key == "usage.threshold_reached":
                        await process_event_idempotently(SessionLocal, event_id, handle_threshold_reached, body)
                except Exception as e:
                    logger.error(f"Error handling notification queue event: {e}", exc_info=True)
