# DevMesh Docker Image
# ====================
# Multi-stage build for production deployment

# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Production
FROM python:3.12-slim AS production

LABEL maintainer="DevMesh Contributors"
LABEL description="Multi-agent orchestration framework for AI CLI tools"

WORKDIR /app

# Create non-root user
RUN groupadd -r devmesh && useradd -r -g devmesh -s /bin/false devmesh

# Copy Python packages from builder
COPY --from=builder /root/.local /home/devmesh/.local

# Set environment variables
ENV PATH=/home/devmesh/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEVMESH_LOG_LEVEL=INFO

# Create necessary directories
RUN mkdir -p /app/.devmesh /app/logs && \
    chown -R devmesh:devmesh /app

# Copy application files
COPY --chown=devmesh:devmesh server.py agent_bridge.py config.py logger.py \
     errors.py storage.py security.py rate_limit.py middleware.py ./
COPY --chown=devmesh:devmesh dashboard.html ./
COPY --chown=devmesh:devmesh requirements.txt ./

# Switch to non-root user
USER devmesh

# Expose ports
# 7700 - WebSocket (agent connections)
# 7701 - HTTP (dashboard)
# 7702 - Dashboard WebSocket
EXPOSE 7700 7701 7702

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import socket; s = socket.socket(); s.connect(('127.0.0.1', 7701)); s.close()" || exit 1

# Default command
CMD ["python", "server.py"]

# Stage 3: Development (optional)
FROM production AS development

USER root

# Install development dependencies
RUN pip install --user --no-cache-dir \
    pytest \
    pytest-cov \
    pytest-asyncio \
    black \
    ruff \
    mypy \
    bandit \
    pre-commit

# Copy test files
COPY --chown=devmesh:devmesh tests/ ./tests/

USER devmesh

# Default command for development
CMD ["python", "-m", "pytest", "tests/", "-v"]
