import asyncio
import logging
from typing import List, Optional, Tuple
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.models.customer import Customer
from src.models.slot import Slot, SlotStatus
from src.schemas.broadcast import BroadcastResponse
from src.services.matching_service import find_matching_customers
from src.services.messaging.spam_guard import can_send_notification
from src.tasks.broadcast_tasks import execute_slot_broadcast
from src.tasks.queue import task_queue

logger = logging.getLogger("slotalert.broadcast")
settings = get_settings()


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
    Logs explicit reason for any candidate filtered out.
    """
    eligible_ids: List[int] = []
    skipped_count = 0

    for customer in candidates:
        is_allowed = await can_send_notification(db, customer.id)
        if is_allowed:
            eligible_ids.append(customer.id)
        else:
            skipped_count += 1
            logger.warning(
                f"⚠️ [Candidate Filtered] Customer ID {customer.id} ({customer.full_name}, {customer.phone_number}) "
                f"filtered out by SpamGuard: reached maximum 2 alerts in past 24 hours."
            )

    return eligible_ids, skipped_count


async def prepare_and_queue_broadcast(
    db: AsyncSession,
    slot_id: int,
    background_tasks: Optional[BackgroundTasks] = None,
    base_url: Optional[str] = None,
) -> BroadcastResponse:
    """
    Orchestrates the slot broadcast workflow:
    1. Validates slot existence and OPEN status.
    2. Identifies matching waitlist customers based on preference rules.
    3. Filters out customers who have hit the spam threshold.
    4. Transitions slot to SENDING to guarantee idempotency.
    5. Dispatches execution immediately via FastAPI BackgroundTasks (or event loop task fallback)
       AND registers job with Redis task queue for auditability.
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

    # 2. Find matching customers (passing slot to prevent redundant query)
    candidates = await find_matching_customers(db, slot_id=slot.id, slot=slot)
    total_matched = len(candidates)

    # 3. Filter candidates through SpamGuard
    eligible_ids, skipped_count = await filter_spam_candidates(db, candidates)

    logger.info(
        f"📊 [Broadcast Evaluation] slot_id={slot.id} | "
        f"Matched by preferences: {total_matched} | "
        f"Eligible to receive alert: {len(eligible_ids)} | "
        f"Skipped by spam guard: {skipped_count}"
    )

    if total_matched > 0 and len(eligible_ids) == 0:
        logger.warning(
            f"⚠️ [Broadcast 0 Recipients] All {total_matched} matched customer(s) "
            f"were skipped due to spam rate limiting (max 2 alerts / 24h)."
        )
    elif total_matched == 0:
        logger.info(
            f"ℹ️ [Broadcast 0 Matched] No waitlisted customers matched preferences for slot {slot.id}."
        )

    # 4. Mark slot as SENDING to prevent duplicate triggers
    if eligible_ids:
        slot.status = SlotStatus.SENDING
        await db.commit()

        effective_base_url = (base_url or settings.BASE_WEB_URL).rstrip("/")

        # 5. Immediate In-Process ASGI Dispatch (FastAPI BackgroundTasks or Event Loop)
        if background_tasks is not None:
            logger.info(f"⚡ [Dispatch] Enqueueing broadcast for slot {slot.id} to FastAPI native BackgroundTasks")
            background_tasks.add_task(
                execute_slot_broadcast,
                slot_id=slot.id,
                recipient_customer_ids=eligible_ids,
                base_url=effective_base_url,
            )
        else:
            logger.info(f"⚡ [Dispatch] Enqueueing broadcast for slot {slot.id} to active asyncio event loop task")
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    execute_slot_broadcast(
                        slot_id=slot.id,
                        recipient_customer_ids=eligible_ids,
                        base_url=effective_base_url,
                    )
                )
            except RuntimeError:
                # No running loop, will rely on queue
                pass

        # 6. Also register in Redis task queue for auditability and external workers if present
        try:
            await task_queue.enqueue(
                "send_slot_broadcast_task",
                slot_id=slot.id,
                recipient_customer_ids=eligible_ids,
                base_url=effective_base_url,
            )
        except Exception as q_err:
            logger.warning(f"Could not enqueue task to Redis (non-fatal): {q_err}")

    return BroadcastResponse(
        status="queued",
        slot_id=slot.id,
        total_matched=total_matched,
        eligible_recipients=len(eligible_ids),
        skipped_spam_guard=skipped_count,
    )
