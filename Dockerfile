# ==========================================
# Stage 1: Builder (Compile Wheels)
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Install compilation build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Build wheels from requirements (including all dependencies)
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# ==========================================
# Stage 2: Runtime (Minimal Hardened Image)
# ==========================================
FROM python:3.11-slim AS runtime

# Set optimal Python production flags
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    WEB_CONCURRENCY=2

WORKDIR /app

# Install minimal runtime shared libraries (libpq5 for PostgreSQL, curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Install pre-built wheels from builder stage offline
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels

# Create dedicated non-root user and group
RUN groupadd -r slotalert && useradd -r -g slotalert -d /app -s /sbin/nologin slotalert

# Copy application code and database migration files
COPY alembic.ini .
COPY alembic/ alembic/
COPY src/ src/
COPY scripts/ scripts/

# Set file permissions and switch to non-root user
RUN chmod +x scripts/entrypoint.sh && \
    chown -R slotalert:slotalert /app

USER slotalert

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/bin/bash", "/app/scripts/entrypoint.sh"]
