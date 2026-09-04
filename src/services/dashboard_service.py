from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.business import Business
from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.service import Service
from src.models.slot import Slot, SlotStatus
from src.schemas.dashboard import (
    DashboardSummaryResponse,
    QuickPublishSlotResponse,
    RecentSlotItem,
    SlotCandidatePreviewResponse,
    WaitlistCustomerItem,
)
from src.schemas.slot import SlotCreateRequest
from src.services.broadcast_service import prepare_and_queue_broadcast
from src.services.slot_service import create_slot
from src.utils.time import (
    HEBREW_DAYS,
    TIME_SLOT_HEBREW_LABELS,
    TIME_SLOT_LABELS,
    calculate_day_of_week,
    get_time_slot,
)

logger = logging.getLogger("slotalert.dashboard_service")



async def get_dashboard_summary(
    db: AsyncSession,
    business: Business,
) -> DashboardSummaryResponse:
    """
    Aggregate metrics and recent slot activity for business mobile dashboard.
    """
    # 1. Total distinct registered customers
    count_stmt = select(func.count(Customer.id)).where(Customer.business_id == business.id)
    count_res = await db.execute(count_stmt)
    active_count = count_res.scalar() or 0

    # 2. 10 most recent slots
    slots_stmt = (
        select(Slot)
        .options(
            selectinload(Slot.service),
            selectinload(Slot.claimed_by_customer),
        )
        .where(Slot.business_id == business.id)
        .order_by(Slot.created_at.desc())
        .limit(10)
    )
    slots_res = await db.execute(slots_stmt)
    slots = slots_res.scalars().all()

    recent_items: List[RecentSlotItem] = []
    for s in slots:
        claimed_name = s.claimed_by_customer.full_name if s.claimed_by_customer else None
        claimed_phone = s.claimed_by_customer.phone_number if s.claimed_by_customer else None
        recent_items.append(
            RecentSlotItem(
                id=s.id,
                start_time=s.start_time,
                end_time=s.end_time,
                status=s.status.value,
                service_name=s.effective_service_name,
                price=s.effective_price,
                claimed_by_name=claimed_name,
                claimed_by_phone=claimed_phone,
                created_at=s.created_at,
            )
        )

    return DashboardSummaryResponse(
        business_id=business.id,
        business_name=business.name,
        slug=business.slug,
        active_waitlist_count=active_count,
        recent_slots=recent_items,
    )


async def preview_candidates_for_slot(
    db: AsyncSession,
    business_id: int,
    service_id: Optional[int],
    start_time: datetime,
) -> SlotCandidatePreviewResponse:
    """
    Calculate matched candidates without creating a slot record.
    Provides live instant feedback for business owner in the quick-publish modal.
    Guarantees non-None time_slot and defensive label mapping.
    """
    day_of_week = calculate_day_of_week(start_time)
    time_slot = get_time_slot(start_time) or "MORNING"

    # Query matching distinct customers - time_slot is guaranteed non-None
    query = (
        select(func.count(func.distinct(Customer.id)))
        .join(CustomerPreference, CustomerPreference.customer_id == Customer.id)
        .where(
            Customer.business_id == business_id,
            CustomerPreference.day_of_week == day_of_week,
            CustomerPreference.time_slot == time_slot,
        )
    )

    if service_id is not None:
        query = query.where(
            (CustomerPreference.service_id.is_(None))
            | (CustomerPreference.service_id == service_id)
        )
    else:
        query = query.where(CustomerPreference.service_id.is_(None))

    result = await db.execute(query)
    matched_count = result.scalar() or 0

    time_slot_label = TIME_SLOT_HEBREW_LABELS.get(time_slot, "שעות כלליות / גמיש")

    return SlotCandidatePreviewResponse(
        matched_count=matched_count,
        day_name=HEBREW_DAYS.get(day_of_week, f"יום {day_of_week}"),
        time_slot_label=time_slot_label,
        time_slot=time_slot,
    )


async def quick_publish_and_broadcast_slot(
    db: AsyncSession,
    business: Business,
    start_time: datetime,
    service_id: Optional[int] = None,
    duration_minutes: Optional[int] = None,
    custom_service_name: Optional[str] = None,
    custom_price: Optional[Decimal] = None,
) -> QuickPublishSlotResponse:
    """
    Atomically creates slot and immediately enqueues the broadcast task.
    Supports both catalog services (with optional price/duration overrides)
    and completely ad-hoc custom services.
    """
    # 1. Determine duration and validate service if provided
    if service_id is not None:
        svc_stmt = select(Service).where(
            Service.id == service_id,
            Service.business_id == business.id,
        )
        svc_res = await db.execute(svc_stmt)
        service = svc_res.scalar_one_or_none()
        if not service:
            raise ValueError(f"Service ID {service_id} does not belong to business {business.id}")
        duration = duration_minutes or service.duration_minutes
    else:
        if not (custom_service_name and custom_service_name.strip()):
            raise ValueError("Either service_id or custom_service_name must be provided.")
        duration = duration_minutes or 60

    end_time = start_time + timedelta(minutes=duration)

    # 2. Create slot record
    slot_in = SlotCreateRequest(
        business_id=business.id,
        service_id=service_id,
        custom_service_name=custom_service_name.strip() if custom_service_name else None,
        custom_price=custom_price,
        start_time=start_time,
        end_time=end_time,
    )
    slot = await create_slot(db=db, slot_in=slot_in)

    # 3. Immediately queue broadcast
    broadcast_res = await prepare_and_queue_broadcast(db=db, slot_id=slot.id)

    return QuickPublishSlotResponse(
        slot_id=slot.id,
        status=slot.status.value,
        start_time=slot.start_time,
        broadcast_status=broadcast_res.status,
        total_matched=broadcast_res.total_matched,
        eligible_recipients=broadcast_res.eligible_recipients,
        skipped_spam_guard=broadcast_res.skipped_spam_guard,
    )


async def list_waitlist_customers(
    db: AsyncSession,
    business_id: int,
) -> List[WaitlistCustomerItem]:
    """
    List all active customers in the waitlist with human-readable preference tags.
    """
    stmt = (
        select(Customer)
        .options(selectinload(Customer.preferences))
        .where(Customer.business_id == business_id)
        .order_by(Customer.created_at.desc())
    )
    res = await db.execute(stmt)
    customers = res.scalars().all()

    items: List[WaitlistCustomerItem] = []
    for c in customers:
        # Build concise summaries
        days = sorted(list({HEBREW_DAYS.get(p.day_of_week, str(p.day_of_week)) for p in c.preferences}))
        slots = sorted(list({p.time_slot for p in c.preferences}))

        summary: List[str] = []
        if days:
            summary.append(f"ימים: {', '.join(days)}")
        if slots:
            slot_labels = [s.replace("MORNING", "בוקר").replace("AFTERNOON", "צהריים").replace("EVENING", "ערב") for s in slots]
            summary.append(f"שעות: {', '.join(slot_labels)}")

        items.append(
            WaitlistCustomerItem(
                id=c.id,
                full_name=c.full_name,
                phone_number=c.phone_number,
                created_at=c.created_at,
                preferences_summary=summary,
            )
        )

    return items
