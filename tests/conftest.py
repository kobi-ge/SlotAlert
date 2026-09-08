from typing import AsyncGenerator
from decimal import Decimal
import pytest
import pytest_asyncio
import httpx
from sqlalchemy import select
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.settings import get_settings
from src.database.connection import get_db
from src.main import app
from src.models.business import Business
from src.models.service import Service

settings = get_settings()

# Create test engine with NullPool to prevent asyncpg connection leaking across test loops
test_engine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=NullPool,
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@pytest_asyncio.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Ensure tests always run with MockMessageProvider and test environment."""
    from src.services.messaging.factory import reset_provider_instance
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "mock")
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", None)
    reset_provider_instance()
    yield
    reset_provider_instance()


@pytest_asyncio.fixture(autouse=True)
def override_db_dependency():
    """Automatically override FastAPI get_db dependency for all tests."""
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture(autouse=True)
async def cleanup_redis_queue():
    """Ensure Redis task queue is clean before and after each test."""
    from src.database.connection import get_redis_client
    from src.tasks.queue import task_queue
    try:
        redis = get_redis_client()
        await redis.delete(task_queue.queue_key)
    except Exception:
        pass
    yield
    try:
        redis = get_redis_client()
        await redis.delete(task_queue.queue_key)
    except Exception:
        pass


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated test database session with NullPool."""
    async with TestSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an async test client for HTTP requests."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def test_business() -> Business:
    """Fixture to provide a test business entity."""
    async with TestSessionLocal() as session:
        stmt = select(Business).where(Business.slug == "test-concurrency-clinic")
        res = await session.execute(stmt)
        biz = res.scalar_one_or_none()

        if not biz:
            biz = Business(
                name="מרפאת בדיקה",
                phone_number="+972599999999",
                business_type="clinic",
                slug="test-concurrency-clinic",
                is_active=True,
            )
            session.add(biz)
            await session.commit()
            await session.refresh(biz)

        return biz


@pytest_asyncio.fixture
async def test_service(test_business: Business) -> Service:
    """Fixture to provide a test service entity."""
    async with TestSessionLocal() as session:
        stmt = select(Service).where(
            Service.business_id == test_business.id,
            Service.name == "טיפול בדיקה",
        )
        res = await session.execute(stmt)
        svc = res.scalar_one_or_none()

        if not svc:
            svc = Service(
                business_id=test_business.id,
                name="טיפול בדיקה",
                duration_minutes=60,
                price=Decimal("200.00"),
            )
            session.add(svc)
            await session.commit()
            await session.refresh(svc)

        return svc
