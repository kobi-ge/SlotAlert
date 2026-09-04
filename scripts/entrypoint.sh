#!/bin/bash
set -e

echo "=== SlotAlert Container Startup ==="

# 1. Wait for PostgreSQL and Redis to be ready
echo "Checking database and cache connectivity..."
python - << 'EOF'
import sys
import time
import socket
from urllib.parse import urlparse
import os

def check_service(url, name, default_port):
    if not url:
        return
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or default_port
    
    for attempt in range(1, 31):
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"[OK] {name} is reachable at {host}:{port}")
                return
        except (socket.error, ConnectionRefusedError):
            print(f"[WAIT] Waiting for {name} ({host}:{port})... attempt {attempt}/30")
            time.sleep(1)
            
    print(f"[ERROR] Could not connect to {name} at {host}:{port}")
    sys.exit(1)

db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/slotalert")
# Remove driver prefix for parsing if needed
if "postgresql+" in db_url:
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
check_service(db_url, "PostgreSQL", 5432)

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6337/0")
check_service(redis_url, "Redis", 6379)
EOF

# 2. Run Database Migrations
echo "Running database schema migrations..."
alembic upgrade head

# 3. Optional Auto-Seed
if [ "${AUTO_SEED,,}" = "true" ]; then
    echo "AUTO_SEED is enabled. Running seed script..."
    python -m src.database.seed || echo "Seed execution completed."
fi

# 4. Launch Production Uvicorn
WORKERS=${WEB_CONCURRENCY:-2}
echo "Starting SlotAlert ASGI server with ${WORKERS} workers on port 8000..."
exec uvicorn src.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${WORKERS}" \
    --proxy-headers \
    --forwarded-allow-ips='*'
