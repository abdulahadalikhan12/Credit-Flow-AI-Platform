import os
import subprocess
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

logger = logging.getLogger("shared.database")

# Declarative base class for models
Base = declarative_base()

def get_database_url(db_name: str) -> str:
    """
    Get connection string for a service's PostgreSQL database.
    Reads connection details from environment variables.
    """
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres_secure_pass_2026")
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"

def init_db_engine(db_name: str):
    """
    Initialize SQLAlchemy engine and async session maker for a specific database.
    """
    db_url = get_database_url(db_name)
    engine = create_async_engine(db_url, echo=False, future=True, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_maker

def run_migrations(service_dir: str):
    """
    Run Alembic database upgrades programmatically by invoking the alembic CLI.
    """
    logger.info(f"Running Alembic migrations in directory: {service_dir}")
    try:
        # Run alembic upgrade head using subprocess
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=service_dir,
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(f"Migration output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Migration failed with exit code {e.returncode}")
        logger.error(f"Stdout: {e.stdout}")
        logger.error(f"Stderr: {e.stderr}")
        raise e

def wait_for_db(host: str = None, port: int = None, timeout: int = 60):
    """
    Wait for PostgreSQL port to accept TCP connections before proceeding.
    """
    import socket
    import time
    
    db_host = host or os.getenv("POSTGRES_HOST", "postgres")
    db_port = port or int(os.getenv("POSTGRES_PORT", "5432"))
    
    logger.info(f"Waiting for database at {db_host}:{db_port}...")
    start_time = time.time()
    while True:
        try:
            with socket.create_connection((db_host, db_port), timeout=2):
                logger.info("Database is ready!")
                break
        except (socket.timeout, ConnectionRefusedError, OSError):
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Database at {db_host}:{db_port} was not ready within {timeout} seconds.")
            time.sleep(2)

async def bootstrap_database(engine, metadata):
    """
    Bootstrap the database by creating tables if they do not exist.
    """
    logger.info("Bootstrapping database schema...")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    logger.info("Database schema bootstrapped successfully.")

