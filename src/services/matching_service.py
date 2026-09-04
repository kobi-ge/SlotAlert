from typing import List, Optional
from datetime import datetime
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.slot import Slot
from src.utils.time import (
    calculate_day_of_week,
    determine_time_slot,
    get_time_slot,
)



async def find_matching_customers(db: AsyncSession, slot_id: int) -> List[Customer]:
    """
    Find matching waitlisted customers for a newly released slot.

    Matching Rules:
    1. Retrieve slot, verifying existence.
    2. Extract day_of_week (0=Sunday ... 6=Saturday).
    3. Categorize time_slot ('MORNING', 'AFTERNOON', 'EVENING').
    4. Query CustomerPreference joined with Customer matching:
       - business_id == slot.business_id
       - day_of_week == slot's day_of_week
       - time_slot == slot's time_slot
       - preference.service_id IS NULL OR preference.service_id == slot.service_id
    5. Deduplicate and return list of matching Customer instances.
    """
    slot_stmt = select(Slot).where(Slot.id == slot_id)
    slot_result = await db.execute(slot_stmt)
    slot = slot_result.scalar_one_or_none()

    if not slot:
        return []

    day_of_week = calculate_day_of_week(slot.start_time)
    time_slot = determine_time_slot(slot.start_time)

    if not time_slot:
        return []

    if slot.service_id is not None:
        service_filter = or_(
            CustomerPreference.service_id.is_(None),
            CustomerPreference.service_id == slot.service_id,
        )
    else:
        service_filter = CustomerPreference.service_id.is_(None)

    query = (
        select(Customer)
        .join(CustomerPreference, CustomerPreference.customer_id == Customer.id)
        .where(
            Customer.business_id == slot.business_id,
            CustomerPreference.day_of_week == day_of_week,
            CustomerPreference.time_slot == time_slot,
            service_filter,
        )
        .distinct()
        .order_by(Customer.id)
    )

    result = await db.execute(query)
    customers = list(result.scalars().all())
    return customers
