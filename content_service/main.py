import asyncio
import logging
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from core.database import engine
from models.models import Base
from shared.database import wait_for_db, bootstrap_database
from routes.content import router as content_router
from services.consumer import start_consumer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("content_service")

# Background consumer task reference
consumer_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global consumer_task
    logger.info("Starting up Content Service...")
    
    # 1. Wait for database
    wait_for_db()
    
    # 2. Bootstrap database schema
    await bootstrap_database(engine, Base.metadata)
    
    # 3. Create static directories for manual image uploads
    uploads_dir = "/app/content_service/static/uploads"
    os.makedirs(uploads_dir, exist_ok=True)
    
    # 4. Start background consumer
    consumer_task = asyncio.create_task(start_consumer())
    
    yield
    
    # Cancel background loops on shutdown
    logger.info("Shutting down Content Service...")
    if consumer_task:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            logger.info("Background consumer stopped.")
            
    logger.info("Shutdown completed.")

app = FastAPI(title="Content Service", lifespan=lifespan)

# Register routes
app.include_router(content_router, prefix="/api/v1")

# Mount static directory for manual image uploads
app.mount("/api/v1/content/static", StaticFiles(directory="/app/content_service/static"), name="static")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "content_service"}
