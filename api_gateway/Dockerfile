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
COPY api_gateway /app/api_gateway

# Install service-specific dependencies
WORKDIR /app/api_gateway
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
