FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install shared library first
COPY shared /app/shared
RUN pip install --no-cache-dir -e /app/shared

# Copy service code
COPY scraper_service /app/scraper_service

# Install service-specific dependencies
WORKDIR /app/scraper_service
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8010

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
