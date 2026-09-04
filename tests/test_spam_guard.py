import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.broadcast_log import BroadcastLog
from src.models.business import Business
from src.models.customer import Customer
from src.models.service import Service
from src.models.slot import Slot, SlotStatus
from src.services.messaging.spam_guard import can_send_notification


@pytest.mark.asyncio
async def test_spam_guard_enforcement_and_window_expiry(
    db_session: AsyncSession,
    test_business: Business,
    test_service: Service,
):
    """
    Verify SpamGuard compliance rule (Max 2 notifications per rolling 24-hour window):
    1. Customer is initially eligible (0 sent alerts).
    2. Customer receives alert #1 -> remains eligible.
    3. Customer receives alert #2 -> blocked (attempt #3 denied).
    4. 25 hours later, rolling window expires -> customer becomes eligible again.
    """
    uid = uuid.uuid4().hex[:6]
    customer = Customer(
        business_id=test_business.id,
        full_name="לקוח בדיקת ספאם",
        phone_number=f"+97253{uid}99",
    )
    db_session.add(customer)
    await db_session.flush()

    slot = Slot(
        business_id=test_business.id,
        service_id=test_service.id,
        start_time=datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 20, 11, 0, tzinfo=timezone.utc),
        status=SlotStatus.OPEN,
        version=1,
    )
    db_session.add(slot)
    await db_session.commit()

    now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

    # Step 1: Initial state (0 alerts sent)
    assert await can_send_notification(db_session, customer.id, now=now) is True

    # Step 2: Customer receives alert #1
    log1 = BroadcastLog(
        slot_id=slot.id,
        customer_id=customer.id,
        message_sid="msg_test_01",
        delivery_status="SENT",
        sent_at=now,
    )
    db_session.add(log1)
    await db_session.commit()

    # Still eligible (1 < 2)
    assert await can_send_notification(db_session, customer.id, now=now) is True

    # Step 3: Customer receives alert #2
    log2 = BroadcastLog(
        slot_id=slot.id,
        customer_id=customer.id,
        message_sid="msg_test_02",
        delivery_status="SENT",
        sent_at=now + timedelta(minutes=30),
    )
    db_session.add(log2)
    await db_session.commit()

    # Step 4: Alert #3 is BLOCKED by SpamGuard (2 >= 2)
    assert await can_send_notification(db_session, customer.id, now=now + timedelta(hours=1)) is False

    # Step 5: 25 hours after alert #1 & #2, customer becomes eligible again
    future_time = now + timedelta(hours=25)
    assert await can_send_notification(db_session, customer.id, now=future_time) is True
