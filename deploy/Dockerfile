# Polymarket Markov Trading Bot — Docker Image
FROM python:3.11-slim

# Metadata
LABEL maintainer="Hermes Agent"
LABEL description="Markov Chain quantitative trading bot for Polymarket"
LABEL version="1.0.0"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Workdir
WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create non-root user (optional)
# RUN useradd -m -u 1000 bot && chown -R bot:bot /app
# USER bot

# Runtime env
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health/live || exit 1

# Entrypoint (dry-run by default)
ENTRYPOINT ["python", "-m", "polymarket_bot"]
CMD ["--dry-run"]
