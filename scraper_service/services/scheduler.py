import asyncio
import logging
import uuid
from datetime import datetime
from services.scraper import get_mongo_db
from shared.messaging import RabbitMQClient

logger = logging.getLogger("scraper_service.scheduler")

async def check_and_trigger_scheduled_scrapes():
    """
    Scans the 'scrapes_schedule' collection in MongoDB for due scraping jobs,
    and publishes a scrape request to RabbitMQ.
    """
    db = await get_mongo_db()
    now_ts = datetime.utcnow().timestamp()
    
    # Cursor of all active schedules
    cursor = db.scrapes_schedule.find({"active": True})
    rabbitmq = RabbitMQClient()
    
    async for schedule in cursor:
        last_run = schedule.get("last_run", 0)
        interval = schedule.get("interval_seconds", 86400) # Default to daily (86400s)
        
        if last_run + interval <= now_ts:
            url = schedule["url"]
            account_id = schedule["account_id"]
            job_id = str(uuid.uuid4())
            
            logger.info(f"Triggering scheduled scrape for {url} (Account: {account_id})")
            
            # Emit scrape request
            try:
                await rabbitmq.publish(
                    exchange_name="scraper_events",
                    routing_key="scrape.requested",
                    body={
                        "job_id": job_id,
                        "url": url,
                        "account_id": str(account_id)
                    }
                )
                
                # Update last run
                await db.scrapes_schedule.update_one(
                    {"_id": schedule["_id"]},
                    {"$set": {"last_run": now_ts}}
                )
            except Exception as e:
                logger.error(f"Failed to publish scheduled scrape trigger: {e}")

async def start_scraper_scheduler_loop():
    """Loop running every 30 seconds to check scheduled scrape jobs."""
    logger.info("Scraper scheduler daemon started.")
    
    # Bootstrap a default schedule (e.g. competitor check) if database is empty
    try:
        db = await get_mongo_db()
        count = await db.scrapes_schedule.count_documents({})
        if count == 0:
            await db.scrapes_schedule.insert_one({
                "url": "https://news.ycombinator.com",
                "account_id": "00000000-0000-0000-0000-000000000000",
                "interval_seconds": 3600, # check every hour
                "last_run": 0,
                "active": True
            })
            logger.info("Bootstrapped default HackerNews competitor scrape schedule.")
    except Exception as e:
         logger.warning(f"Failed to bootstrap default schedule: {e}")
         
    while True:
        try:
            await check_and_trigger_scheduled_scrapes()
        except Exception as e:
            logger.error(f"Error in scraper scheduler loop: {e}")
        await asyncio.sleep(30)
