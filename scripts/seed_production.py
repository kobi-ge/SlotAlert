import asyncio
import os
import logging
from decimal import Decimal
from sqlalchemy import select

from src.database.connection import AsyncSessionLocal
from src.models.business import Business
from src.models.service import Service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("slotalert.production_seed")


async def seed_production_business():
    """Idempotently bootstrap initial business tenant in production."""
    biz_name = os.environ.get("INITIAL_BUSINESS_NAME", "קליניקת שירן")
    biz_phone = os.environ.get("INITIAL_BUSINESS_PHONE", "+972501112233")
    biz_slug = os.environ.get("INITIAL_BUSINESS_SLUG", "shiran-clinic")
    biz_type = os.environ.get("INITIAL_BUSINESS_TYPE", "clinic")

    async with AsyncSessionLocal() as session:
        # Check if business exists
        stmt = select(Business).where(Business.slug == biz_slug)
        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            logger.info(f"Business '{biz_slug}' already exists (ID: {existing.id}). Skipping bootstrap.")
            return

        business = Business(
            name=biz_name,
            phone_number=biz_phone,
            business_type=biz_type,
            slug=biz_slug,
            is_active=True,
        )
        session.add(business)
        await session.flush()

        services = [
            Service(
                business_id=business.id,
                name="טיפול פנים קלאסי",
                duration_minutes=60,
                price=Decimal("350.00"),
            ),
            Service(
                business_id=business.id,
                name="עיסוי שוודי",
                duration_minutes=50,
                price=Decimal("280.00"),
            ),
        ]
        session.add_all(services)
        await session.commit()
        logger.info(f"Successfully bootstrapped production tenant: {biz_name} ({biz_slug}) with {len(services)} services.")


if __name__ == "__main__":
    asyncio.run(seed_production_business())
