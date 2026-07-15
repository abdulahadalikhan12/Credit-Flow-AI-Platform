import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from core.database import engine
from models.models import Base
from shared.database import wait_for_db, bootstrap_database
from routes.ai import router as ai_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_service")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up AI Generation Service...")
    
    # 1. Wait for database
    wait_for_db()
    
    # 2. Bootstrap tables
    await bootstrap_database(engine, Base.metadata)
    
    yield
    logger.info("Shutting down AI Generation Service...")

app = FastAPI(title="AI Generation Service", lifespan=lifespan)

# Register routes
app.include_router(ai_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "ai_service"}
