import asyncio
import os
import json
import logging
import uuid
from typing import Optional, Dict, Any
import httpx
from datetime import datetime
from sqlalchemy.future import select
from shared.messaging import RabbitMQClient, process_event_idempotently
from core.database import SessionLocal
from models.models import SocialConnection, PublishJob
from services.encryption import decrypt_token

logger = logging.getLogger("social_service.publisher")

async def fetch_post_details(content_id: uuid.UUID, account_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    """Query Content Service to fetch the actual post body and image."""
    content_service_url = os.getenv("CONTENT_SERVICE_URL", "http://content_service:8007")
    url = f"{content_service_url}/api/v1/content/{content_id}"
    
    headers = {
        "X-Account-Id": str(account_id),
        "X-User-Id": str(uuid.UUID(int=0)), # system user
        "X-User-Role": "admin"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=5.0)
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch post details from Content Service: {e}")
    return None

async def download_image_bytes(image_url: str) -> Optional[bytes]:
    """Download image files locally from the content service static path or web."""
    # Resolve relative uploads URL if pointing to local content static path
    resolved_url = image_url
    if image_url.startswith("/api/v1/content/"):
        content_service_url = os.getenv("CONTENT_SERVICE_URL", "http://content_service:8007")
        resolved_url = f"{content_service_url}{image_url}"
        
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(resolved_url, timeout=10.0)
            if response.status_code == 200:
                return response.content
    except Exception as e:
        logger.error(f"Failed to download image bytes from {resolved_url}: {e}")
    return None

async def publish_to_linkedin(access_token: str, person_urn: str, body: str, image_bytes: Optional[bytes]) -> str:
    """
    Publish text-only or text+image post to LinkedIn API.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    person_id = person_urn.split(":")[-1] if ":" in person_urn else person_urn
    author_urn = f"urn:li:person:{person_id}"
    
    image_urn = None
    
    # 1. Image Upload Flow if image bytes exist
    if image_bytes:
        logger.info("Starting LinkedIn Image Upload Flow...")
        # Register image upload
        register_url = "https://api.linkedin.com/v2/images?action=registerUpload"
        register_payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": author_urn,
                "relationshipType": "OWNER"
            }
        }
        
        async with httpx.AsyncClient() as client:
            reg_resp = await client.post(register_url, headers=headers, json=register_payload, timeout=10.0)
            if reg_resp.status_code != 200:
                raise Exception(f"Failed to register image upload: {reg_resp.text}")
                
            reg_data = reg_resp.json()
            upload_url = reg_data["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
            image_urn = reg_data["value"]["image"]
            
            # PUT binary payload
            put_headers = {"Authorization": f"Bearer {access_token}"}
            put_resp = await client.put(upload_url, headers=put_headers, content=image_bytes, timeout=30.0)
            if put_resp.status_code not in [200, 201]:
                raise Exception(f"Failed to upload image binary to LinkedIn: {put_resp.text}")
                
            logger.info(f"Image uploaded successfully. URN: {image_urn}")

    # 2. Publish UGC Post
    ugc_url = "https://api.linkedin.com/v2/ugcPosts"
    
    if image_urn:
        # Text + Image share
        share_content = {
            "shareCommentary": {"text": body},
            "shareMediaCategory": "IMAGE",
            "media": [{
                "status": "READY",
                "media": image_urn,
                "title": {"text": "Post Image"}
            }]
        }
    else:
        # Text-only share
        share_content = {
            "shareCommentary": {"text": body},
            "shareMediaCategory": "NONE"
        }

    post_payload = {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": share_content
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(ugc_url, headers=headers, json=post_payload, timeout=15.0)
        if response.status_code not in [200, 201]:
             raise Exception(f"LinkedIn UGC Publish failed: {response.text}")
        
        post_data = response.json()
        post_urn = post_data.get("id")
        return f"https://www.linkedin.com/feed/update/{post_urn}"

async def handle_publish_job(session, body):
    """
    Executes publishing task: resolves credentials, downloads image,
    signs UGC payload, publishes to LinkedIn, and manages error retry state.
    """
    content_id_str = body["content_id"]
    account_id_str = body["account_id"]
    scheduled_post_id = body.get("scheduled_post_id")
    
    account_id = uuid.UUID(account_id_str)
    content_id = uuid.UUID(content_id_str)
    
    # 1. Fetch LinkedIn Social Connection
    q_conn = select(SocialConnection).where(SocialConnection.account_id == account_id)
    res_conn = await session.execute(q_conn)
    connection = res_conn.scalar_one_or_none()
    
    # Check if LinkedIn client keys or access tokens are missing (trigger Mock Mode)
    client_id = os.getenv("LINKEDIN_CLIENT_ID")
    is_mock_connection = (
        connection is None or 
        connection.encrypted_access_token == "mock" or 
        not client_id or 
        client_id.startswith("your_")
    )
    
    # Create publish job log
    async with session.begin():
        job = PublishJob(
            account_id=account_id,
            content_id=content_id,
            platform="linkedin",
            status="running"
        )
        session.add(job)
        await session.flush()
        job_id = job.id
    
    # Fetch content details
    post = await fetch_post_details(content_id, account_id)
    if not post:
        async with session.begin():
            q = select(PublishJob).where(PublishJob.id == job_id)
            res = await session.execute(q)
            j = res.scalar_one()
            j.status = "failed"
            j.error_reason = "Content details could not be retrieved"
        logger.error("Publish failed: Content details could not be retrieved")
        return

    post_body = post.get("body", "")
    image_url = post.get("image_url")
    
    rabbitmq = RabbitMQClient()
    
    if is_mock_connection:
        logger.info(f"[MOCK MODE] Simulating LinkedIn post for account {account_id}")
        await asyncio.sleep(2.0) # simulate API lag
        
        mock_post_id = f"mock_{uuid.uuid4().hex[:12]}"
        mock_post_url = f"https://www.linkedin.com/feed/update/urn:li:share:{mock_post_id}"
        
        async with session.begin():
            q = select(PublishJob).where(PublishJob.id == job_id)
            res = await session.execute(q)
            j = res.scalar_one()
            j.status = "success"
            j.post_url = mock_post_url
            
        logger.info(f"[MOCK MODE] Published post successfully. URL: {mock_post_url}")
        
        # Emit success
        await rabbitmq.publish(
            exchange_name="social_events",
            routing_key="post.published",
            body={
                "account_id": account_id_str,
                "content_id": content_id_str,
                "post_url": mock_post_url,
                "scheduled_post_id": scheduled_post_id
            }
        )
        return

    # Real LinkedIn API mode
    try:
        # Decrypt Access Token
        access_token = decrypt_token(connection.encrypted_access_token)
        
        # Download image bytes if attached
        image_bytes = None
        if image_url:
            image_bytes = await download_image_bytes(image_url)
            if not image_bytes:
                 logger.warning(f"Failed to download image from {image_url}. Proceeding with text-only post.")

        # Call LinkedIn API (retry transient errors with exponential backoff)
        max_retries = 3
        backoff = 2.0
        post_url = None
        
        for attempt in range(max_retries):
            try:
                post_url = await publish_to_linkedin(
                    access_token, connection.person_urn, post_body, image_bytes
                )
                break
            except Exception as api_err:
                if attempt == max_retries - 1:
                    raise api_err
                logger.warning(f"LinkedIn API call attempt {attempt+1} failed: {api_err}. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff *= 2.0
        
        async with session.begin():
            q = select(PublishJob).where(PublishJob.id == job_id)
            res = await session.execute(q)
            j = res.scalar_one()
            j.status = "success"
            j.post_url = post_url
            
        logger.info(f"Published post successfully to LinkedIn. URL: {post_url}")
        
        # Emit success
        await rabbitmq.publish(
            exchange_name="social_events",
            routing_key="post.published",
            body={
                "account_id": account_id_str,
                "content_id": content_id_str,
                "post_url": post_url,
                "scheduled_post_id": scheduled_post_id
            }
        )
    except Exception as e:
        logger.error(f"LinkedIn Publishing failed: {e}", exc_info=True)
        async with session.begin():
            q = select(PublishJob).where(PublishJob.id == job_id)
            res = await session.execute(q)
            j = res.scalar_one()
            j.status = "failed"
            j.error_reason = str(e)
            
        # Emit failure
        await rabbitmq.publish(
            exchange_name="social_events",
            routing_key="post.failed",
            body={
                "account_id": account_id_str,
                "content_id": content_id_str,
                "reason": str(e),
                "scheduled_post_id": scheduled_post_id
            }
        )
        raise e

async def start_consumer():
    rabbitmq = RabbitMQClient()
    
    while True:
        try:
            await rabbitmq.connect()
            break
        except Exception as e:
            logger.warning(f"RabbitMQ connection failed in social consumer: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

    queue = await rabbitmq.declare_queue("social_service_queue")
    scheduler_ex = await rabbitmq.declare_exchange("scheduler_events")
    await queue.bind(scheduler_ex, routing_key="content.scheduled")

    logger.info("Social Service background event consumer started.")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                try:
                    payload = json.loads(message.body.decode())
                    event_id = payload["event_id"]
                    routing_key = payload["routing_key"]
                    body = payload["body"]
                    
                    logger.info(f"Social consumer received event: {routing_key} ({event_id})")
                    
                    if routing_key == "content.scheduled":
                        await process_event_idempotently(
                            SessionLocal, event_id, handle_publish_job, body
                        )
                except Exception as e:
                    logger.error(f"Error handling social queue event: {e}")
                    # Accept message so it does not loop indefinitely, since handle_publish_job raised it,
                    # but normally a robust consumer can let it move to DLQ.
