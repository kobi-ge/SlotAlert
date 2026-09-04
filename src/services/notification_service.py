from datetime import datetime, timezone
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.broadcast_log import BroadcastLog
from src.models.customer import Customer
from src.models.slot import Slot
from src.services.messaging.factory import get_configured_message_provider

logger = logging.getLogger("slotalert.notification_service")


async def notify_business_owner_on_claim(
    db: AsyncSession,
    slot_id: int,
    customer_id: int,
) -> None:
    """
    Send an immediate WhatsApp notification to the business owner when a customer
    successfully claims a slot, closing the loop with real-time feedback.
    """
    # 1. Fetch slot with business, service, and customer
    slot_stmt = (
        select(Slot)
        .options(
            selectinload(Slot.business),
            selectinload(Slot.service),
        )
        .where(Slot.id == slot_id)
    )
    slot_res = await db.execute(slot_stmt)
    slot = slot_res.scalar_one_or_none()

    cust_stmt = select(Customer).where(Customer.id == customer_id)
    cust_res = await db.execute(cust_stmt)
    customer = cust_res.scalar_one_or_none()

    if not slot or not slot.business or not customer:
        logger.warning(
            f"Cannot send owner claim alert: slot={slot_id}, business={getattr(slot, 'business', None)}, customer={customer_id}"
        )
        return

    business = slot.business
    service_name = slot.service.name if slot.service else "השירות"
    start_formatted = slot.start_time.strftime("%d/%m/%Y בשעה %H:%M")

    # 2. Build owner alert message
    owner_message = (
        f"🎉 יש! התור ל-{service_name} בתאריך {start_formatted} "
        f"נתפס הרגע ע\"י {customer.full_name} ({customer.phone_number})!"
    )

    # 3. Dispatch WhatsApp to business owner
    try:
        provider = get_configured_message_provider()
        message_sid = await provider.send_text_message(business.phone_number, owner_message)
        logger.info(f"Owner alert sent to {business.phone_number} for slot {slot_id} (SID: {message_sid})")

        # 4. Record in broadcast_logs for audit
        log = BroadcastLog(
            slot_id=slot.id,
            customer_id=customer.id,
            message_sid=message_sid,
            delivery_status="SENT",
            sent_at=datetime.now(timezone.utc),
        )
        db.add(log)
        await db.commit()
    except Exception as exc:
        logger.error(f"Failed to dispatch owner claim notification: {exc}")
