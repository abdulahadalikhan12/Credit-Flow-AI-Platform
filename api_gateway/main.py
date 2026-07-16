import os
import time
import logging
import asyncio
import httpx
import redis
import uuid
import json
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
import stripe

from shared.security import JWTVerifier
from shared.messaging import RabbitMQClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_gateway")

app = FastAPI(title="CreditFlow API Gateway")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize shared utilities
jwt_verifier = JWTVerifier()
rabbitmq_client = RabbitMQClient()

# Redis Client
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# Stripe Keys
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
stripe.api_key = STRIPE_SECRET_KEY

# URL Mapping
SERVICE_URLS = {
    "auth": os.getenv("AUTH_SERVICE_URL", "http://auth_service:8001"),
    "accounts": os.getenv("USER_SERVICE_URL", "http://user_service:8002"),
    "billing": os.getenv("BILLING_SERVICE_URL", "http://billing_service:8003"),
    "credits": os.getenv("CREDITS_SERVICE_URL", "http://credits_service:8004"),
    "usage": os.getenv("USAGE_SERVICE_URL", "http://usage_service:8005"),
    "ai": os.getenv("AI_SERVICE_URL", "http://ai_service:8006"),
    "content": os.getenv("CONTENT_SERVICE_URL", "http://content_service:8007"),
    "scheduler": os.getenv("SCHEDULER_SERVICE_URL", "http://scheduler_service:8008"),
    "social": os.getenv("SOCIAL_SERVICE_URL", "http://social_service:8009"),
    "scraper": os.getenv("SCRAPER_SERVICE_URL", "http://scraper_service:8010"),
    "notification": os.getenv("NOTIFICATION_SERVICE_URL", "http://notification_service:8011"),
    "admin": os.getenv("ADMIN_SERVICE_URL", "http://admin_service:8012")
}

PUBLIC_PATHS = [
    "/api/v1/auth/signup",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/switch",
    "/api/v1/auth/verify-email",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    "/api/v1/billing/webhook/stripe",
    "/api/v1/ai/stream/",
    "/health"
]

# Webhook signatures verify bypass paths
WEBHOOK_PATHS = [
    "/webhooks/stripe",
    "/webhooks/linkedin",
    "/webhooks/openrouter"
]

# Rate limit implementation
async def is_rate_limited(client_key: str, limit: int, window: int) -> bool:
    """Sliding window rate limit check in Redis."""
    try:
        now = time.time()
        pipe = redis_client.pipeline()
        pipe.zremrangebyscore(client_key, 0, now - window)
        pipe.zadd(client_key, {str(now): now})
        pipe.zcard(client_key)
        pipe.expire(client_key, window)
        _, _, count, _ = pipe.execute()
        return count > limit
    except Exception as e:
        logger.error(f"Rate limiting failure: {e}")
        return False # Fail open in case Redis is down

@app.middleware("http")
async def gateway_middleware(request: Request, call_next):
    # Pass OPTIONS preflight requests directly to CORSMiddleware
    if request.method == "OPTIONS":
        return await call_next(request)

    # Helper to append CORS headers to responses returned directly from middleware
    def with_cors(response: Response) -> Response:
        response.headers["Access-Control-Allow-Origin"] = "http://localhost:3000"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    path = request.url.path
    
    # 1. Skip middleware for webhooks (handled in endpoints directly)
    if any(path.startswith(w) for w in WEBHOOK_PATHS):
        return await call_next(request)

    # 2. Rate Limiting: IP-based (Global)
    client_ip = request.client.host if request.client else "unknown"
    ip_limit_key = f"rate:ip:{client_ip}"
    if await is_rate_limited(ip_limit_key, limit=100, window=60):
        return with_cors(JSONResponse(status_code=429, content={"detail": "Too many requests. IP Rate limit exceeded."}))

    # 3. Authentication & RBAC Enrichment
    is_public = any(path == p or path.startswith(p) for p in PUBLIC_PATHS)
    
    user_id = None
    account_id = None
    role = None

    if not is_public:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return with_cors(JSONResponse(status_code=401, content={"detail": "Authorization header missing or invalid"}))
        
        token = auth_header.split(" ")[1]
        try:
            # Verify and decode using RS256/HS256 in shared package
            payload = jwt_verifier.verify_token(token)
            jti = payload.get("jti")
            
            # Check session revocation state in Redis
            if not redis_client.exists(f"auth:jti:{jti}"):
                return with_cors(JSONResponse(status_code=401, content={"detail": "Session has been revoked or expired"}))

            user_id = payload.get("user_id")
            account_id = payload.get("account_id")
            role = payload.get("role")
            
            # 4. Account-based Rate Limiting
            if account_id:
                account_limit_key = f"rate:account:{account_id}"
                # Limit based on role/tier (e.g. Free: 30 req/min, Paid: 200 req/min)
                limit = 200 if role in ["owner", "admin"] else 50
                if await is_rate_limited(account_limit_key, limit=limit, window=60):
                    return with_cors(JSONResponse(status_code=429, content={"detail": "Workspace rate limit exceeded."}))

        except Exception as e:
            return with_cors(JSONResponse(status_code=401, content={"detail": f"Invalid token: {str(e)}"}))

    # 5. Attach context headers for downstream microservices
    # Modifying state directly on request scope
    request.state.user_id = user_id
    request.state.account_id = account_id
    request.state.role = role

    return await call_next(request)


# SSE Re-stream endpoint
@app.get("/api/v1/ai/stream/{job_id}")
async def restream_ai(job_id: str):
    """
    Subscribes to Redis Pub/Sub for a specific generation job and streams chunks back as SSE.
    """
    async def sse_generator():
        pubsub = redis_client.pubsub()
        channel = f"job:{job_id}"
        pubsub.subscribe(channel)
        logger.info(f"Subscribed to Redis SSE channel: {channel}")
        
        try:
            while True:
                # Fetch message
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    data = message["data"]
                    if data == "[DONE]":
                        yield {"event": "done", "data": "[DONE]"}
                        break
                    elif data.startswith("[ERROR]"):
                        yield {"event": "error", "data": data.replace("[ERROR]", "")}
                        break
                    yield {"event": "token", "data": data}
                await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"Error in SSE streamer for job {job_id}: {e}")
            yield {"event": "error", "data": "Streaming connection aborted"}
        finally:
            pubsub.unsubscribe(channel)
            logger.info(f"Unsubscribed from Redis SSE channel: {channel}")

    return EventSourceResponse(sse_generator())

# Webhook Endpoints
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")
    
    # 1. Verify Signature
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2. Deduplicate Event
    event_id = event["id"]
    dedup_key = f"webhooks:stripe:{event_id}"
    if not redis_client.set(dedup_key, "1", ex=86400, nx=True):
        logger.info(f"Stripe event {event_id} already processed. Ignoring.")
        return {"status": "ignored_duplicate"}

    # 3. Normalize and publish to RabbitMQ
    logger.info(f"Processing Stripe Webhook event: {event['type']} ({event_id})")
    
    routing_key = None
    body = {}
    
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        routing_key = "stripe.webhook.invoice_paid"
        body = {
            "event_id": event_id,
            "account_id": session.get("client_reference_id"),
            "customer_id": session.get("customer"),
            "subscription_id": session.get("subscription"),
            "invoice_id": session.get("invoice"),
            "plan_tier": session.get("metadata", {}).get("plan_tier", "pro"),
            "amount_paid": session.get("amount_total")
        }
    elif event["type"] == "invoice.payment_failed":
        invoice = event["data"]["object"]
        routing_key = "stripe.webhook.payment_failed"
        body = {
            "event_id": event_id,
            "customer_id": invoice.get("customer"),
            "subscription_id": invoice.get("subscription"),
            "amount_due": invoice.get("amount_due")
        }
    
    if routing_key:
        await rabbitmq_client.publish(
            exchange_name="billing_events",
            routing_key=routing_key,
            body=body,
            event_id=event_id
        )

    return {"status": "success"}

@app.post("/webhooks/linkedin")
async def linkedin_webhook(request: Request):
    # Dummy placeholder for LinkedIn Webhook reception and RabbitMQ publish
    payload = await request.json()
    event_id = payload.get("id", str(uuid.uuid4()))
    
    dedup_key = f"webhooks:linkedin:{event_id}"
    if not redis_client.set(dedup_key, "1", ex=86400, nx=True):
        return {"status": "ignored_duplicate"}

    await rabbitmq_client.publish(
        exchange_name="social_events",
        routing_key="post.published",
        body=payload,
        event_id=event_id
    )
    return {"status": "success"}

@app.post("/webhooks/openrouter")
async def openrouter_webhook(request: Request):
    payload = await request.json()
    event_id = payload.get("id", str(uuid.uuid4()))
    
    dedup_key = f"webhooks:openrouter:{event_id}"
    if not redis_client.set(dedup_key, "1", ex=86400, nx=True):
        return {"status": "ignored_duplicate"}

    await rabbitmq_client.publish(
        exchange_name="ai_events",
        routing_key="generation.webhook",
        body=payload,
        event_id=event_id
    )
    return {"status": "success"}

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "api_gateway"}

# Catch-all Reverse Proxy Route
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def reverse_proxy(path: str, request: Request):
    # Determine downstream service
    parts = path.split("/")
    if len(parts) < 3: # expected format: api/v1/{service}/...
        raise HTTPException(status_code=404, detail="Resource not found")
    
    service_key = parts[2] # e.g. auth, accounts, billing...
    
    if service_key not in SERVICE_URLS:
         raise HTTPException(status_code=404, detail=f"Service '{service_key}' not found")
         
    target_url = f"{SERVICE_URLS[service_key]}/{path}"
    
    # Inject context headers
    headers = dict(request.headers)
    if hasattr(request.state, "user_id") and request.state.user_id:
        headers["X-User-Id"] = str(request.state.user_id)
    if hasattr(request.state, "account_id") and request.state.account_id:
        headers["X-Account-Id"] = str(request.state.account_id)
    if hasattr(request.state, "role") and request.state.role:
        headers["X-User-Role"] = str(request.state.role)

    # Clean Host header to prevent downstream hostname mismatch errors
    headers.pop("host", None)

    # Forward the request
    async with httpx.AsyncClient() as client:
        try:
            req_body = await request.body()
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                params=dict(request.query_params),
                content=req_body,
                timeout=30.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            logger.error(f"Failed to forward request to {target_url}: {e}")
            raise HTTPException(status_code=502, detail="Bad Gateway: Downstream service is unreachable")
