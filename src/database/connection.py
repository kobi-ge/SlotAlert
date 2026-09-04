from typing import AsyncGenerator
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.settings import get_settings

settings = get_settings()

# Asynchronous SQLAlchemy Engine
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    pool_pre_ping=True,
    future=True,
)

# Asynchronous Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Asynchronous Redis Client
redis_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    """Return singleton Redis client instance."""
    global redis_client
    if redis_client is None:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return redis_client


async def close_redis_client() -> None:
    """Close Redis client connection pool."""
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an AsyncSession for a request and handles cleanup."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
