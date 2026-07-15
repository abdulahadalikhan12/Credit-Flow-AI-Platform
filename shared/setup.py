from setuptools import setup, find_packages

setup(
    name="shared",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "sqlalchemy[asyncio]>=2.0.0",
        "asyncpg>=0.28.0",
        "pika>=1.3.2",
        "aio-pika>=9.3.0",
        "pyjwt[crypto]>=2.8.0",
        "cryptography>=41.0.0",
        "pydantic>=2.0.0",
        "alembic>=1.12.0",
    ],
)
