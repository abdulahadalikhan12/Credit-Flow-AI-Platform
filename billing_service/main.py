import asyncio
import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from core.database import engine
from models.models import Base
from shared.database import wait_for_db, bootstrap_database
from routes.billing import router as billing_router
from services.consumer import start_consumer
from services.outbox_publisher import start_outbox_publisher
from services.dunning import start_dunning_reconciler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("billing_service")

# References to background tasks
consumer_task = None
outbox_task = None
dunning_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global consumer_task, outbox_task, dunning_task
    logger.info("Starting up Billing Service...")
    
    # 1. Wait for Postgres
    wait_for_db()
    
    # 2. Bootstrap database schema
    await bootstrap_database(engine, Base.metadata)
    
    # 3. Start background loops
    consumer_task = asyncio.create_task(start_consumer())
    outbox_task = asyncio.create_task(start_outbox_publisher())
    dunning_task = asyncio.create_task(start_dunning_reconciler())
    
    yield
    
    # Cancel background loops on shutdown
    logger.info("Shutting down Billing Service...")
    if consumer_task:
        consumer_task.cancel()
    if outbox_task:
        outbox_task.cancel()
    if dunning_task:
        dunning_task.cancel()
        
    await asyncio.gather(consumer_task, outbox_task, dunning_task, return_exceptions=True)
    logger.info("Shutdown completed.")

app = FastAPI(title="Billing Service", lifespan=lifespan)

# Register routes
app.include_router(billing_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "billing_service"}
