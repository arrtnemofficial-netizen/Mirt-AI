# =============================================================================
# MIRT AI - Production Dockerfile
# =============================================================================
# Multi-stage build for minimal production image
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Builder
# -----------------------------------------------------------------------------
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: Production
# -----------------------------------------------------------------------------
FROM python:3.11-slim as production

# Labels
LABEL maintainer="MIRT Team"
LABEL description="MIRT AI Shopping Assistant"
LABEL version="1.0.0"

# Security: Run as non-root user
RUN groupadd -r mirt && useradd -r -g mirt mirt

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY --chown=mirt:mirt src/ ./src/
COPY --chown=mirt:mirt data/ ./data/

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    # Default settings (override in docker-compose or k8s)
    PUBLIC_BASE_URL=http://localhost:8000 \
    TELEGRAM_WEBHOOK_PATH=/webhooks/telegram

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Switch to non-root user
USER mirt

# Run the application
CMD ["uvicorn", "src.server.main:app", "--host", "0.0.0.0", "--port", "8000"]

# -----------------------------------------------------------------------------
# Stage 3: Development (optional, for local development)
# -----------------------------------------------------------------------------
FROM production as development

USER root

# Install dev dependencies
RUN pip install --no-cache-dir pytest pytest-asyncio pytest-cov ruff mypy

# Switch back to non-root
USER mirt

# Override command for development
CMD ["uvicorn", "src.server.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
