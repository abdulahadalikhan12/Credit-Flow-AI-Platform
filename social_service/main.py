import asyncio
import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from core.database import engine
from models.models import Base
from shared.database import wait_for_db, bootstrap_database
from routes.social import router as social_router
from services.publisher import start_consumer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("social_service")

from services.refresher import start_token_refresher_loop

# Background consumer task reference
consumer_task = None
refresher_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global consumer_task, refresher_task
    logger.info("Starting up Social Publishing Service...")
    
    # 1. Wait for database
    wait_for_db()
    
    # 2. Bootstrap tables
    await bootstrap_database(engine, Base.metadata)
    
    # 3. Start background RabbitMQ subscriber
    consumer_task = asyncio.create_task(start_consumer())
    
    # 4. Start background token refresher loop
    refresher_task = asyncio.create_task(start_token_refresher_loop())
    
    yield
    
    # Clean up on shutdown
    logger.info("Shutting down Social Publishing Service...")
    if consumer_task:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            logger.info("Background consumer stopped.")
            
    if refresher_task:
        refresher_task.cancel()
        try:
            await refresher_task
        except asyncio.CancelledError:
            logger.info("Background refresher stopped.")
            
    logger.info("Shutdown completed.")

app = FastAPI(title="Social Publishing Service", lifespan=lifespan)

# Register routes
app.include_router(social_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "social_service"}
