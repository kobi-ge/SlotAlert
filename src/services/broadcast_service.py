from typing import List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.customer import Customer
from src.models.slot import Slot, SlotStatus
from src.schemas.broadcast import BroadcastResponse
from src.services.matching_service import find_matching_customers
from src.services.messaging.spam_guard import can_send_notification
from src.tasks.queue import task_queue


class BroadcastError(Exception):
    """Custom domain exception for broadcast failures."""
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def filter_spam_candidates(
    db: AsyncSession,
    candidates: List[Customer],
) -> Tuple[List[int], int]:
    """
    Evaluate waitlisted candidates against spam rate limiting (max 2 alerts / 24h).
    Returns tuple: (eligible_customer_ids, skipped_count).
    """
    eligible_ids: List[int] = []
    skipped_count = 0

    for customer in candidates:
        is_allowed = await can_send_notification(db, customer.id)
        if is_allowed:
            eligible_ids.append(customer.id)
        else:
            skipped_count += 1

    return eligible_ids, skipped_count


async def prepare_and_queue_broadcast(
    db: AsyncSession,
    slot_id: int,
) -> BroadcastResponse:
    """
    Orchestrates the slot broadcast workflow:
    1. Validates slot existence and OPEN status.
    2. Identifies matching waitlist customers based on preference rules.
    3. Filters out customers who have hit the spam threshold.
    4. Transitions slot to SENDING to guarantee idempotency.
    5. Enqueues background dispatch job in Redis task queue.
    """
    # 1. Validate slot
    stmt = select(Slot).where(Slot.id == slot_id)
    res = await db.execute(stmt)
    slot = res.scalar_one_or_none()

    if not slot:
        raise BroadcastError("Slot not found", status_code=404)

    if slot.status == SlotStatus.SENDING:
        raise BroadcastError("Broadcast for this slot is already in progress", status_code=409)

    if slot.status != SlotStatus.OPEN:
        raise BroadcastError(
            f"Cannot broadcast slot with status '{slot.status.value}'. Slot must be OPEN.",
            status_code=400,
        )

    # 2. Find matching customers
    candidates = await find_matching_customers(db, slot_id)
    total_matched = len(candidates)

    # 3. Filter candidates through SpamGuard
    eligible_ids, skipped_count = await filter_spam_candidates(db, candidates)

    # 4. Mark slot as SENDING to prevent duplicate triggers
    if eligible_ids:
        slot.status = SlotStatus.SENDING
        await db.commit()

        # 5. Enqueue background broadcast task
        await task_queue.enqueue(
            "send_slot_broadcast_task",
            slot_id=slot.id,
            recipient_customer_ids=eligible_ids,
        )

    return BroadcastResponse(
        status="queued",
        slot_id=slot.id,
        total_matched=total_matched,
        eligible_recipients=len(eligible_ids),
        skipped_spam_guard=skipped_count,
    )
