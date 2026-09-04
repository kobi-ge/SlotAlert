import asyncio
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.base import Base
from src.database.connection import AsyncSessionLocal, engine
from src.models.business import Business
from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.service import Service


async def seed_database(session: AsyncSession) -> None:
    """Populate database with demo business, services, customers and preferences."""
    print("Checking for existing demo data...")

    # Check if demo business already exists
    existing_biz_stmt = select(Business).where(Business.slug == "shiran-clinic")
    existing_biz = (await session.execute(existing_biz_stmt)).scalar_one_or_none()

    if existing_biz:
        print(f"Demo business '{existing_biz.name}' (slug: {existing_biz.slug}) already exists. Skipping seed.")
        return

    print("Creating demo business: 'קליניקת שירן'...")
    business = Business(
        name="קליניקת שירן",
        phone_number="+972501112233",
        business_type="clinic",
        slug="shiran-clinic",
        is_active=True,
    )
    session.add(business)
    await session.flush()  # populate business.id

    print("Creating services...")
    service_facial = Service(
        business_id=business.id,
        name="טיפול פנים קלאסי",
        duration_minutes=60,
        price=Decimal("350.00"),
    )
    service_massage = Service(
        business_id=business.id,
        name="עיסוי רקמות עמוק",
        duration_minutes=60,
        price=Decimal("400.00"),
    )
    session.add_all([service_facial, service_massage])
    await session.flush()

    print("Creating customers & preferences...")
    # Customer 1
    cust1 = Customer(
        business_id=business.id,
        full_name="דנה לוי",
        phone_number="+972501234567",
    )
    session.add(cust1)
    await session.flush()

    pref1_1 = CustomerPreference(
        customer_id=cust1.id,
        day_of_week=0,  # Sunday
        time_slot="MORNING",
        service_id=service_facial.id,
    )
    pref1_2 = CustomerPreference(
        customer_id=cust1.id,
        day_of_week=2,  # Tuesday
        time_slot="AFTERNOON",
        service_id=service_facial.id,
    )
    session.add_all([pref1_1, pref1_2])

    # Customer 2
    cust2 = Customer(
        business_id=business.id,
        full_name="יוסי כהן",
        phone_number="+972522345678",
    )
    session.add(cust2)
    await session.flush()

    pref2_1 = CustomerPreference(
        customer_id=cust2.id,
        day_of_week=1,  # Monday
        time_slot="MORNING",
        service_id=service_massage.id,
    )
    pref2_2 = CustomerPreference(
        customer_id=cust2.id,
        day_of_week=3,  # Wednesday
        time_slot="EVENING",
        service_id=service_massage.id,
    )
    session.add_all([pref2_1, pref2_2])

    # Customer 3
    cust3 = Customer(
        business_id=business.id,
        full_name="מיכל אברהם",
        phone_number="+972543456789",
    )
    session.add(cust3)
    await session.flush()

    pref3_1 = CustomerPreference(
        customer_id=cust3.id,
        day_of_week=4,  # Thursday
        time_slot="EVENING",
        service_id=None,  # Any service
    )
    pref3_2 = CustomerPreference(
        customer_id=cust3.id,
        day_of_week=5,  # Friday
        time_slot="MORNING",
        service_id=service_facial.id,
    )
    session.add_all([pref3_1, pref3_2])

    await session.commit()
    print("Seed completed successfully!")
    print(f"Created: 1 Business ({business.name}), 2 Services, 3 Customers with preferences.")


async def main() -> None:
    """Initialize database tables and run seed."""
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await seed_database(session)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
