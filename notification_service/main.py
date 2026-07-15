import asyncio
import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from core.database import engine
from models.models import Base
from shared.database import wait_for_db, bootstrap_database
from services.consumer import start_consumer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notification_service")

# Background consumer task reference
consumer_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global consumer_task
    logger.info("Starting up Notification Service...")
    
    # 1. Wait for database
    wait_for_db()
    
    # 2. Bootstrap tables
    await bootstrap_database(engine, Base.metadata)
    
    # 3. Start background event consumer
    consumer_task = asyncio.create_task(start_consumer())
    
    yield
    
    # Clean up on shutdown
    logger.info("Shutting down Notification Service...")
    if consumer_task:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            logger.info("Background consumer stopped.")
            
    logger.info("Shutdown completed.")

app = FastAPI(title="Notification Service", lifespan=lifespan)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "notification_service"}
