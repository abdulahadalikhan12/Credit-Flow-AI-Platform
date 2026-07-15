import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from core.database import engine
from models.models import Base
from shared.database import wait_for_db, bootstrap_database
from routes.scheduler import router as scheduler_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler_service")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Scheduler Service...")
    
    # 1. Wait for database
    wait_for_db()
    
    # 2. Bootstrap tables
    await bootstrap_database(engine, Base.metadata)
    
    yield
    logger.info("Shutting down Scheduler Service...")

app = FastAPI(title="Scheduler Service", lifespan=lifespan)

# Register routes
app.include_router(scheduler_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "scheduler_service"}
