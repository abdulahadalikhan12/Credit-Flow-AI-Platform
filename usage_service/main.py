import asyncio
import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from core.database import engine
from models.models import Base
from shared.database import wait_for_db, bootstrap_database
from routes.usage import router as usage_router
from services.consumer import start_consumer
from services.reconciler import start_reconciler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("usage_service")

# Background tasks references
consumer_task = None
reconciler_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global consumer_task, reconciler_task
    logger.info("Starting up Usage/Metering Service...")
    
    # 1. Wait for Postgres database
    wait_for_db()
    
    # 2. Bootstrap database schema
    await bootstrap_database(engine, Base.metadata)
    
    # 3. Start background processes
    consumer_task = asyncio.create_task(start_consumer())
    reconciler_task = asyncio.create_task(start_reconciler())
    
    yield
    
    # Cancel background loops on shutdown
    logger.info("Shutting down Usage/Metering Service...")
    if consumer_task:
        consumer_task.cancel()
    if reconciler_task:
        reconciler_task.cancel()
        
    await asyncio.gather(consumer_task, reconciler_task, return_exceptions=True)
    logger.info("Shutdown completed.")

app = FastAPI(title="Usage Service", lifespan=lifespan)

# Register routes
app.include_router(usage_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "usage_service"}
