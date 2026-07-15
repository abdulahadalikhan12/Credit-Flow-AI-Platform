import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
from celery import Celery
import redis

# Insert service path to enable local imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import init_db_engine
from models.models import ScheduledPost
from shared.messaging import RabbitMQClient
from sqlalchemy.future import select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler_service.celery")

redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = os.getenv("REDIS_PORT", "6379")

# Create Celery instance
celery_app = Celery(
    "scheduler_tasks",
    broker=f"redis://{redis_host}:{redis_port}/1",
    backend=f"redis://{redis_host}:{redis_port}/1"
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

# Celery Beat Periodic schedule config
celery_app.conf.beat_schedule = {
    "scan-due-posts-every-30-seconds": {
        "task": "core.celery.scan_due_posts",
        "schedule": 30.0,
    }
}

async def check_and_publish_due_posts():
    """
    Asynchronously queries due posts, publishes event to RabbitMQ,
    and updates scheduled post records (supporting recurring schedules).
    """
    # 1. Establish Redis connection for distributed locking
    r_lock = redis.Redis(host=redis_host, port=int(redis_port), decode_responses=True)
    
    # Try to acquire lock for 25 seconds
    lock = r_lock.lock("scheduler:scan_lock", timeout=25)
    acquired = lock.acquire(blocking=False)
    if not acquired:
        logger.info("Scheduler scan already in progress by another worker. Skipping.")
        return

    # Initialize dynamic engine/session maker to avoid event loop conflicts in celery worker
    engine, local_session_maker = init_db_engine("scheduler_db")

    try:
        async with local_session_maker() as session:
            now = datetime.utcnow()
            # Fetch all due posts that are still scheduled
            query = select(ScheduledPost).where(
                ScheduledPost.publish_at <= now,
                ScheduledPost.status == "scheduled"
            )
            result = await session.execute(query)
            due_posts = result.scalars().all()
            
            if not due_posts:
                return

            logger.info(f"Found {len(due_posts)} due scheduled posts to publish.")
            
            rabbitmq = RabbitMQClient()
            await rabbitmq.connect()
            
            for post in due_posts:
                logger.info(f"Triggering publish event for post content {post.content_id} in account {post.account_id}")
                
                # Emit event
                await rabbitmq.publish(
                    exchange_name="scheduler_events",
                    routing_key="content.scheduled",
                    body={
                        "content_id": str(post.content_id),
                        "account_id": str(post.account_id),
                        "scheduled_post_id": str(post.id)
                    }
                )
                
                # 2. Update status / repeat cadence
                cadence = post.repeat_cadence.lower()
                if cadence == "daily":
                    post.publish_at = post.publish_at + timedelta(days=1)
                    post.last_published_at = now
                elif cadence == "weekly":
                    post.publish_at = post.publish_at + timedelta(weeks=1)
                    post.last_published_at = now
                elif cadence == "monthly":
                    post.publish_at = post.publish_at + timedelta(days=30)
                    post.last_published_at = now
                else:
                    post.status = "published"
                    post.last_published_at = now
                    
            await session.commit()
            logger.info("Database updated for due posts.")
    except Exception as e:
        logger.error(f"Error executing due posts scanner: {e}", exc_info=True)
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
             pass
        await engine.dispose()

@celery_app.task
def scan_due_posts():
    """
    Celery Beat entrypoint task.
    """
    asyncio.run(check_and_publish_due_posts())
