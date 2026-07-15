import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from core.database import engine
from models.models import Base
from core.security import load_or_generate_keys
from shared.database import wait_for_db, bootstrap_database
from routes.auth import router as auth_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("auth_service")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Auth Service...")
    # 1. Wait for Postgres database port to become available
    wait_for_db()
    # 2. Automatically bootstrap the database tables
    await bootstrap_database(engine, Base.metadata)
    # 3. Load or generate RSA key pair and publish the public key to Redis
    load_or_generate_keys()
    
    yield
    logger.info("Shutting down Auth Service...")

app = FastAPI(title="Auth Service", lifespan=lifespan)

# Register routes
app.include_router(auth_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "auth_service"}
