import asyncio
import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from routes.scraper import router as scraper_router
from services.scraper import start_consumer
from services.scheduler import start_scraper_scheduler_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scraper_service")

# Background task references
consumer_task = None
scheduler_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global consumer_task, scheduler_task
    logger.info("Starting up Scraper Service...")
    
    # Start background consumer
    consumer_task = asyncio.create_task(start_consumer())
    
    # Start background scheduler
    scheduler_task = asyncio.create_task(start_scraper_scheduler_loop())
    
    yield
    
    # Clean up on shutdown
    logger.info("Shutting down Scraper Service...")
    if consumer_task:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            logger.info("Background consumer stopped.")
            
    if scheduler_task:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            logger.info("Background scheduler stopped.")
            
    logger.info("Shutdown completed.")

app = FastAPI(title="Scraper Service", lifespan=lifespan)

# Register routes
app.include_router(scraper_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "scraper_service"}
