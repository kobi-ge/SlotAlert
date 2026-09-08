import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_redis_client
from src.models.broadcast_log import BroadcastLog

logger = logging.getLogger("slotalert.spam_guard")

MAX_ALERTS_PER_24H = 2


async def can_send_notification(
    db: AsyncSession,
    customer_id: int,
    now: Optional[datetime] = None,
) -> bool:
    """
    Check if a notification can be sent to a customer under spam prevention rules:
    Maximum 2 notifications per customer per rolling 24-hour window.
    Enforces PostgreSQL as the authoritative source of truth and keeps Redis in sync.

    :param db: Async database session
    :param customer_id: ID of the customer to check
    :param now: Reference timestamp (defaults to current UTC time)
    :return: True if eligible, False if blocked by spam guard
    """
    current_time = now or datetime.now(timezone.utc)
    date_str = current_time.strftime("%Y-%m-%d")
    redis_key = f"alerts:customer:{customer_id}:{date_str}"

    # 1. Database Authority: Count actual SENT broadcast_logs within rolling 24-hour window
    cutoff = current_time - timedelta(hours=24)
    stmt = (
        select(func.count(BroadcastLog.id))
        .where(
            BroadcastLog.customer_id == customer_id,
            BroadcastLog.sent_at >= cutoff,
            BroadcastLog.delivery_status == "SENT",
        )
    )

    result = await db.execute(stmt)
    db_count = result.scalar() or 0

    # 2. Resync Redis counter to reflect true database count
    try:
        redis = get_redis_client()
        await redis.set(redis_key, db_count, ex=86400)
    except Exception:
        pass

    # 3. Evaluate limit
    if db_count >= MAX_ALERTS_PER_24H:
        logger.warning(
            f"🚫 [SpamGuard Blocked] Customer ID {customer_id} reached 24h limit: "
            f"{db_count}/{MAX_ALERTS_PER_24H} alerts sent since {cutoff.strftime('%Y-%m-%d %H:%M:%S UTC')}."
        )
        return False

    return True


async def increment_customer_alert_count(customer_id: int, now: Optional[datetime] = None) -> None:
    """Increment Redis fast counter for customer daily alert rate limiting."""
    try:
        current_time = now or datetime.now(timezone.utc)
        date_str = current_time.strftime("%Y-%m-%d")
        redis = get_redis_client()
        redis_key = f"alerts:customer:{customer_id}:{date_str}"
        pipe = redis.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, 86400)  # 24 hour TTL
        await pipe.execute()
    except Exception:
        pass
