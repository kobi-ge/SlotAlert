import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.config.settings import get_settings
from src.database.connection import AsyncSessionLocal
from src.models.broadcast_log import BroadcastLog
from src.models.customer import Customer
from src.models.slot import Slot, SlotStatus
from src.services.messaging.factory import get_configured_message_provider
from src.services.messaging.spam_guard import increment_customer_alert_count
from src.tasks.queue import task_queue

logger = logging.getLogger("slotalert.tasks.broadcast")
settings = get_settings()


async def execute_slot_broadcast(
    slot_id: int,
    recipient_customer_ids: Optional[List[int]] = None,
    base_url: Optional[str] = None,
) -> None:
    """
    Background execution task to dispatch WhatsApp cancellation alerts to eligible customers.
    Can run directly via FastAPI BackgroundTasks, asyncio.create_task(), or Redis task worker.
    - Controlled concurrency with asyncio.Semaphore(10).
    - Database idempotency: skips customers who already received an alert for this slot.
    - Persists dispatch status in broadcast_logs.
    """
    effective_base_url = (base_url or settings.BASE_WEB_URL).rstrip("/")
    provider = get_configured_message_provider()

    async with AsyncSessionLocal() as session:
        # 1. Fetch slot with business and service details
        stmt = (
            select(Slot)
            .options(
                selectinload(Slot.business),
                selectinload(Slot.service),
            )
            .where(Slot.id == slot_id)
        )
        res = await session.execute(stmt)
        slot = res.scalar_one_or_none()

        if not slot:
            logger.error(f"❌ [Broadcast Aborted] Slot {slot_id} not found in database.")
            return

        # 2. Fetch recipients
        if not recipient_customer_ids:
            logger.warning(f"⚠️ [Broadcast Skip] No recipient IDs provided for slot {slot_id}.")
            if slot.status == SlotStatus.SENDING:
                slot.status = SlotStatus.OPEN
                await session.commit()
            return

        # Idempotency check: find which customers already received an alert for this slot
        existing_logs_stmt = select(BroadcastLog.customer_id).where(
            BroadcastLog.slot_id == slot_id,
            BroadcastLog.customer_id.in_(recipient_customer_ids),
        )
        existing_res = await session.execute(existing_logs_stmt)
        already_alerted_ids = set(existing_res.scalars().all())

        pending_ids = [cid for cid in recipient_customer_ids if cid not in already_alerted_ids]
        if not pending_ids:
            logger.info(f"ℹ️ [Broadcast Idempotent] All {len(recipient_customer_ids)} recipients already have broadcast logs for slot {slot_id}. Skipping duplicate send.")
            if slot.status == SlotStatus.SENDING:
                slot.status = SlotStatus.OPEN
                await session.commit()
            return

        cust_stmt = select(Customer).where(Customer.id.in_(pending_ids))
        cust_res = await session.execute(cust_stmt)
        customers = list(cust_res.scalars().all())

        logger.info(
            f"🚀 [Broadcast Start] slot_id={slot_id} | Pending recipients: {len(customers)} "
            f"(Total requested: {len(recipient_customer_ids)}, Already sent: {len(already_alerted_ids)}) "
            f"| Provider: {provider.__class__.__name__} | Base URL: {effective_base_url}"
        )

        start_time_str = slot.start_time.strftime("%d/%m/%Y בשעה %H:%M")
        claim_url = f"{effective_base_url}/api/v1/slots/{slot.id}/claim"
        semaphore = asyncio.Semaphore(10)
        sent_count = 0
        failed_count = 0

        # 3. Controlled dispatch worker coroutine
        async def dispatch_one(customer: Customer) -> None:
            nonlocal sent_count, failed_count
            async with semaphore:
                try:
                    sid = await provider.send_slot_alert(
                        phone_number=customer.phone_number,
                        customer_name=customer.full_name,
                        business_name=slot.business.name,
                        service_name=slot.effective_service_name,
                        start_time_formatted=start_time_str,
                        claim_url=claim_url,
                        price=slot.effective_price,
                    )
                    log_entry = BroadcastLog(
                        slot_id=slot.id,
                        customer_id=customer.id,
                        message_sid=sid,
                        wamid=sid,
                        delivery_status="SENT",
                        sent_at=datetime.now(timezone.utc),
                    )
                    session.add(log_entry)
                    await increment_customer_alert_count(customer.id)
                    sent_count += 1
                except Exception as exc:
                    logger.error(f"Failed to send alert to customer {customer.id} ({customer.phone_number}): {exc}")
                    log_entry = BroadcastLog(
                        slot_id=slot.id,
                        customer_id=customer.id,
                        message_sid=None,
                        wamid=None,
                        delivery_status="FAILED",
                        failure_reason=str(exc)[:255],
                        sent_at=datetime.now(timezone.utc),
                    )
                    session.add(log_entry)
                    failed_count += 1

        # Run all dispatches with semaphore bounding
        await asyncio.gather(*(dispatch_one(c) for c in customers))

        # 4. If slot is still in SENDING status (wasn't claimed yet during broadcast), revert to OPEN
        if slot.status == SlotStatus.SENDING:
            slot.status = SlotStatus.OPEN

        await session.commit()
        logger.info(
            f"✅ [Broadcast Complete] slot_id={slot_id} | Sent: {sent_count} | Failed: {failed_count} "
            f"| Slot status: {slot.status.value}"
        )


# Alias for backward compatibility
send_slot_broadcast_task = execute_slot_broadcast


def _async_delay(*args: Any, **kwargs: Any) -> asyncio.Task:
    """Fallback stub allowing Celery-style .delay() dispatch in asyncio event loop."""
    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(execute_slot_broadcast(*args, **kwargs))
    except RuntimeError:
        return asyncio.run(execute_slot_broadcast(*args, **kwargs))


# Attach .delay helper to both function objects
setattr(execute_slot_broadcast, "delay", _async_delay)
setattr(send_slot_broadcast_task, "delay", _async_delay)

# Register task handlers with the native Redis queue
task_queue.register_task("execute_slot_broadcast", execute_slot_broadcast)
task_queue.register_task("send_slot_broadcast_task", send_slot_broadcast_task)
