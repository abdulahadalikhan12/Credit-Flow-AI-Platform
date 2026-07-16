import uuid
import os
import redis
import json
import logging
import asyncio
import httpx
import urllib.parse
from fastapi import APIRouter, Depends, HTTPException, Header, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Dict, Any

from core.database import SessionLocal
from models.models import PromptHistory, GenerationJob
from schemas.schemas import GenerateRequest, GenerateResponse, ImageGenerateRequest, ImageGenerateResponse, HistoryOut
from shared.messaging import RabbitMQClient

logger = logging.getLogger("ai_service.routes")
router = APIRouter(prefix="/ai", tags=["ai"])

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

async def check_quota_limit(account_id: uuid.UUID) -> bool:
    """Query Usage Service to check if quota is available."""
    usage_service_url = os.getenv("USAGE_SERVICE_URL", "http://usage_service:8005")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{usage_service_url}/api/v1/usage/quota-check/{account_id}", timeout=3.0)
            if response.status_code == 200:
                return response.json().get("allowed", True)
    except Exception as e:
        logger.error(f"Failed to query usage service quota-check: {e}")
    return True # Fail open if usage service is down

async def generate_mock_text_stream(job_id: str, account_id: str, prompt: str, model_type: str, r):
    """Fallback generator to simulate token-by-token stream offline."""
    mock_tokens = [
        "Hello! ", "This ", "is ", "a ", "simulated ", "response ", "generated ", "by ", 
        "the ", "CreditFlow ", "AI ", "engine.\n\n", "You ", "submitted ", "the ", "prompt: \n",
        f'"{prompt}"\n\n', "This ", "proves ", "the ", "asynchronous ", "SSE ", "streaming ", 
        "architecture ", "via ", "Redis ", "Pub/Sub ", "fan-out ", "works ", "flawlessly! "
    ]
    
    full_response = []
    tokens_count = 0
    
    # 1. Update job to running
    async with SessionLocal() as db_session:
        async with db_session.begin():
            q = select(GenerationJob).where(GenerationJob.job_id == job_id)
            res = await db_session.execute(q)
            job = res.scalar_one_or_none()
            if not job:
                job = GenerationJob(job_id=job_id, status="running")
                db_session.add(job)
            else:
                job.status = "running"

    for token in mock_tokens:
        full_response.append(token)
        tokens_count += 1
        r.publish(f"job:{job_id}", token)
        await asyncio.sleep(0.08) # sleep 80ms to feel natural
        
    final_text = "".join(full_response)
    credits_cost = 1
    
    # 2. Save completion to Postgres history
    async with SessionLocal() as db_session:
        async with db_session.begin():
            history_entry = PromptHistory(
                account_id=uuid.UUID(account_id),
                prompt=prompt,
                response=final_text,
                tokens_used=tokens_count,
                cost=credits_cost,
                model=f"mock-{model_type}"
            )
            db_session.add(history_entry)
            
            # Update job status
            job_query = select(GenerationJob).where(GenerationJob.job_id == job_id)
            res = await db_session.execute(job_query)
            job = res.scalar_one_or_none()
            if job:
                job.status = "completed"
        
    # 3. Emit ai.generation_completed to RabbitMQ
    rabbitmq = RabbitMQClient()
    await rabbitmq.publish(
        exchange_name="ai_events",
        routing_key="ai.generation_completed",
        body={
            "account_id": account_id,
            "tokens_used": tokens_count,
            "credits_cost": credits_cost,
            "model": f"mock-{model_type}",
            "job_id": job_id
        }
    )
    # Emit final signal to Redis
    r.publish(f"job:{job_id}", "[DONE]")

async def generate_text_stream_task(job_id: str, account_id: str, prompt: str, model_type: str):
    """Task to stream completions from OpenRouter to Redis."""
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
    
    api_key = os.getenv("OPENROUTER_API_KEY")
    
    # Check if we should fallback to mock
    if not api_key or api_key.startswith("sk-or-v1-placeholder") or "test" in api_key:
        logger.info("Using simulated mock generator.")
        await generate_mock_text_stream(job_id, account_id, prompt, model_type, r)
        return
        
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:3000",
        "X-Title": "CreditFlow AI Platform"
    }

    models_to_try = [
        "google/gemma-2-9b-it:free",
        "meta-llama/llama-3-8b-instruct:free",
        "mistralai/mistral-7b-instruct:free",
        "qwen/qwen-2.5-coder-32b-instruct:free",
        "openrouter/free"
    ]
    
    # Mark job as running
    async with SessionLocal() as db_session:
        async with db_session.begin():
            job = GenerationJob(job_id=job_id, status="running")
            db_session.add(job)

    url = "https://openrouter.ai/api/v1/chat/completions"
    
    success = False
    final_model_used = None
    full_response = []
    tokens_count = 0
    
    try:
        for model_name in models_to_try:
            logger.info(f"Attempting content generation using OpenRouter model: {model_name}")
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True
            }
            
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream("POST", url, headers=headers, json=payload, timeout=60.0) as response:
                        if response.status_code != 200:
                            err_text = await response.aread()
                            logger.warning(f"Model {model_name} failed with status {response.status_code}: {err_text.decode()}")
                            continue
                            
                        async for chunk in response.aiter_lines():
                            if not chunk.strip():
                                continue
                            if chunk.startswith("data: "):
                                data_str = chunk[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data_json = json.loads(data_str)
                                    token = data_json["choices"][0]["delta"].get("content", "")
                                    if token:
                                        full_response.append(token)
                                        tokens_count += 1
                                        r.publish(f"job:{job_id}", token)
                                except Exception:
                                    pass
                        
                        success = True
                        final_model_used = model_name
                        break
            except Exception as e:
                logger.warning(f"Exception while trying model {model_name}: {e}")
                continue

        if not success:
            logger.info("All OpenRouter models failed or rate-limited. Falling back to mock text generator.")
            await generate_mock_text_stream(job_id, account_id, prompt, model_type, r)
            return
                                
        # Complete DB updates
        final_text = "".join(full_response)
        credits_cost = 1
        
        async with SessionLocal() as db_session:
            async with db_session.begin():
                history_entry = PromptHistory(
                    account_id=uuid.UUID(account_id),
                    prompt=prompt,
                    response=final_text,
                    tokens_used=tokens_count,
                    cost=credits_cost,
                    model=final_model_used or "openrouter/free"
                )
                db_session.add(history_entry)
                
                # Update job
                job_query = select(GenerationJob).where(GenerationJob.job_id == job_id)
                res = await db_session.execute(job_query)
                job = res.scalar_one_or_none()
                if job:
                    job.status = "completed"
                
        # Emit ai.generation_completed
        rabbitmq = RabbitMQClient()
        await rabbitmq.publish(
            exchange_name="ai_events",
            routing_key="ai.generation_completed",
            body={
                "account_id": account_id,
                "tokens_used": tokens_count,
                "credits_cost": credits_cost,
                "model": final_model_used or "openrouter/free",
                "job_id": job_id,
                "prompt": prompt,
                "response": final_text
            }
        )
        
        r.publish(f"job:{job_id}", "[DONE]")
        
    except Exception as e:
        logger.error(f"Error in streaming background task: {e}")
        r.publish(f"job:{job_id}", f"[ERROR] {str(e)}")
        # Fallback to mock on error
        await generate_mock_text_stream(job_id, account_id, prompt, model_type, r)

@router.post("/generate", response_model=GenerateResponse)
async def generate_content(
    payload: GenerateRequest,
    background_tasks: BackgroundTasks,
    account_id: uuid.UUID = Depends(get_account_id)
):
    """
    Triggers content generation, spawns background streaming worker and returns job_id immediately.
    """
    # 1. Synchronously verify quota
    allowed = await check_quota_limit(account_id)
    if not allowed:
        raise HTTPException(
            status_code=402, 
            detail="Usage quota exceeded. Please upgrade your subscription plan."
        )
        
    job_id = str(uuid.uuid4())
    
    # 2. Spawn background task
    background_tasks.add_task(
        generate_text_stream_task,
        job_id,
        str(account_id),
        payload.prompt,
        payload.model
    )
    
    return {"job_id": job_id}

@router.post("/generate-image", response_model=ImageGenerateResponse)
async def generate_image(
    payload: ImageGenerateRequest,
    account_id: uuid.UUID = Depends(get_account_id)
):
    """
    AI Image Generation utilizing Pollinations.ai (requires no API key).
    Debits 10 credits upon completion.
    """
    allowed = await check_quota_limit(account_id)
    if not allowed:
        raise HTTPException(status_code=402, detail="Usage quota exceeded.")

    encoded_prompt = urllib.parse.quote(payload.prompt)
    img_model = payload.model or "flux"
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&model={img_model}"
    
    # Save image generation to PostgreSQL history
    async with SessionLocal() as db_session:
        async with db_session.begin():
            entry = PromptHistory(
                account_id=account_id,
                prompt=payload.prompt,
                response=image_url,
                tokens_used=0,
                cost=10, # image costs 10 credits
                model="pollinations-image-gen"
            )
            db_session.add(entry)
        
    # Emit completion event so credits deduct
    try:
        rabbitmq = RabbitMQClient()
        await rabbitmq.publish(
            exchange_name="ai_events",
            routing_key="ai.generation_completed",
            body={
                "account_id": str(account_id),
                "tokens_used": 0,
                "credits_cost": 10,
                "model": "pollinations-image-gen",
                "job_id": str(uuid.uuid4()),
                "prompt": payload.prompt,
                "response": image_url
            }
        )
    except Exception as e:
        logger.error(f"Failed to publish event for image generation: {e}")

    return {"image_url": image_url}

@router.get("/history", response_model=List[HistoryOut])
async def list_generation_history(
    account_id: uuid.UUID = Depends(get_account_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Get prompt and response history for the active workspace.
    """
    q = select(PromptHistory).where(PromptHistory.account_id == account_id).order_by(PromptHistory.created_at.desc())
    res = await db.execute(q)
    return res.scalars().all()
