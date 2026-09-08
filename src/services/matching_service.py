import logging
from typing import List, Optional
from datetime import datetime
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.slot import Slot
from src.utils.time import (
    HEBREW_DAYS,
    calculate_day_of_week,
    determine_time_slot,
    get_time_slot,
)

logger = logging.getLogger("slotalert.matching")


async def find_matching_customers_by_criteria(
    db: AsyncSession,
    business_id: int,
    start_time: datetime,
    service_id: Optional[int] = None,
) -> List[Customer]:
    """
    Unified candidate matching query logic used by BOTH /preview-candidates AND slot broadcast.
    Guarantees 100% query parity between preview calculations and live broadcast execution.
    """
    day_of_week = calculate_day_of_week(start_time)
    time_slot = get_time_slot(start_time) or "MORNING"

    if service_id is not None:
        service_filter = or_(
            CustomerPreference.service_id.is_(None),
            CustomerPreference.service_id == service_id,
        )
    else:
        service_filter = CustomerPreference.service_id.is_(None)

    query = (
        select(Customer)
        .join(CustomerPreference, CustomerPreference.customer_id == Customer.id)
        .where(
            Customer.business_id == business_id,
            CustomerPreference.day_of_week == day_of_week,
            CustomerPreference.time_slot == time_slot,
            service_filter,
        )
        .distinct()
        .order_by(Customer.id)
    )

    result = await db.execute(query)
    customers = list(result.scalars().all())

    day_name = HEBREW_DAYS.get(day_of_week, str(day_of_week))
    logger.info(
        f"🔍 [Candidate Matching] business_id={business_id} | start_time={start_time} | "
        f"day={day_of_week} ({day_name}) | time_slot={time_slot} | service_id={service_id} | "
        f"Found {len(customers)} matching customer(s): {[c.id for c in customers]}"
    )

    return customers


async def find_matching_customers(
    db: AsyncSession,
    slot_id: int,
    slot: Optional[Slot] = None,
) -> List[Customer]:
    """
    Find matching waitlisted customers for a slot by delegating to find_matching_customers_by_criteria.
    Accepts optional slot instance to prevent redundant database roundtrips.
    """
    if slot is None:
        slot_stmt = select(Slot).where(Slot.id == slot_id)
        slot_result = await db.execute(slot_stmt)
        slot = slot_result.scalar_one_or_none()

    if not slot:
        logger.error(f"❌ [Matching Aborted] Slot ID {slot_id} not found.")
        return []

    return await find_matching_customers_by_criteria(
        db=db,
        business_id=slot.business_id,
        start_time=slot.start_time,
        service_id=slot.service_id,
    )
