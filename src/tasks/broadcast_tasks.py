import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.database.connection import AsyncSessionLocal
from src.models.broadcast_log import BroadcastLog
from src.models.customer import Customer
from src.models.slot import Slot, SlotStatus
from src.services.messaging import get_message_provider, increment_customer_alert_count
from src.tasks.queue import task_queue

logger = logging.getLogger("slotalert.tasks.broadcast")


async def send_slot_broadcast_task(
    slot_id: int,
    recipient_customer_ids: Optional[List[int]] = None,
    base_url: str = "http://localhost:8000",
) -> None:
    """
    Background worker task to dispatch WhatsApp cancellation alerts to eligible customers.
    Controlled concurrency with asyncio.Semaphore(10).
    Persists dispatch status in broadcast_logs.
    """
    logger.info(f"Starting broadcast task for slot_id={slot_id}")
    provider = get_message_provider()

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
            logger.error(f"Slot {slot_id} not found in database. Broadcast aborted.")
            return

        # 2. Fetch recipients
        if not recipient_customer_ids:
            logger.warning(f"No recipient IDs provided for slot {slot_id}. Broadcast complete.")
            return

        cust_stmt = select(Customer).where(Customer.id.in_(recipient_customer_ids))
        cust_res = await session.execute(cust_stmt)
        customers = list(cust_res.scalars().all())

        start_time_str = slot.start_time.strftime("%d/%m/%Y בשעה %H:%M")
        claim_url = f"{base_url}/api/v1/slots/{slot.id}/claim"
        semaphore = asyncio.Semaphore(10)

        # 3. Controlled dispatch worker coroutine
        async def dispatch_one(customer: Customer) -> None:
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
                except Exception as exc:
                    logger.error(f"Failed to send alert to customer {customer.id}: {exc}")
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

        # Run all dispatches with semaphore bounding
        await asyncio.gather(*(dispatch_one(c) for c in customers))

        # 4. If slot is still in SENDING status (wasn't claimed yet), revert to OPEN
        if slot.status == SlotStatus.SENDING:
            slot.status = SlotStatus.OPEN

        await session.commit()
        logger.info(f"Finished broadcast for slot {slot_id}. Sent to {len(customers)} recipients.")


# Register task handler with the queue
task_queue.register_task("send_slot_broadcast_task", send_slot_broadcast_task)
