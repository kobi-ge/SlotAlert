from decimal import Decimal
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from src.models.broadcast_log import BroadcastLog
from src.models.business import Business
from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.service import Service
from src.models.slot import Slot, SlotStatus
from src.services.messaging import get_message_provider
from src.tasks.queue import task_queue


@pytest.mark.asyncio
async def test_broadcast_slot_orchestration_and_spam_skipping(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Integration test for slot broadcast pipeline:
    1. Dedicated business & service for total isolation
    2. 1 open slot (Sunday 10:00, MORNING)
    3. Exactly 3 matching customers with Sunday MORNING preferences
    4. Customer 3 already received 2 alerts in last 24h (hitting spam limit)
    5. Trigger POST /api/v1/slots/{slot_id}/broadcast
    6. Assert 202 Accepted response with:
       - total_matched: 3
       - eligible_recipients: 2
       - skipped_spam_guard: 1
    7. Execute queue task and verify MockMessageProvider received 2 messages
    8. Verify broadcast_logs in database has 2 new SENT records for this slot
    """
    from src.database.connection import get_redis_client
    redis = get_redis_client()
    await redis.delete(task_queue.queue_key)

    provider = get_message_provider()
    provider.clear()

    uid = uuid.uuid4().hex[:6]

    # Create dedicated business and service for this test
    biz = Business(
        name="מרפאת בדיקת שידור",
        phone_number=f"+97258{uid}11",
        business_type="clinic",
        slug=f"broadcast-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="טיפול פנים",
        duration_minutes=60,
        price=Decimal("250.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    # Create 3 customers
    cust1 = Customer(
        business_id=biz.id,
        full_name="לקוח פתוח 1",
        phone_number=f"+97254{uid}01",
    )
    cust2 = Customer(
        business_id=biz.id,
        full_name="לקוח פתוח 2",
        phone_number=f"+97254{uid}02",
    )
    cust3 = Customer(
        business_id=biz.id,
        full_name="לקוח ספאמר",
        phone_number=f"+97254{uid}03",
    )
    db_session.add_all([cust1, cust2, cust3])
    await db_session.flush()

    # Preferences: Sunday (0), MORNING
    pref1 = CustomerPreference(
        customer_id=cust1.id,
        day_of_week=0,
        time_slot="MORNING",
        service_id=svc.id,
    )
    pref2 = CustomerPreference(
        customer_id=cust2.id,
        day_of_week=0,
        time_slot="MORNING",
        service_id=svc.id,
    )
    pref3 = CustomerPreference(
        customer_id=cust3.id,
        day_of_week=0,
        time_slot="MORNING",
        service_id=svc.id,
    )
    db_session.add_all([pref1, pref2, pref3])
    await db_session.flush()

    # Create target slot (Sunday 10:00)
    slot = Slot(
        business_id=biz.id,
        service_id=svc.id,
        start_time=datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 27, 11, 0, tzinfo=timezone.utc),
        status=SlotStatus.OPEN,
        version=1,
    )
    db_session.add(slot)
    await db_session.flush()

    # Pre-seed 2 broadcast logs for customer 3 to trigger spam limit
    pre_log1 = BroadcastLog(
        slot_id=slot.id,
        customer_id=cust3.id,
        message_sid="pre_msg_01",
        delivery_status="SENT",
        sent_at=datetime.now(timezone.utc),
    )
    pre_log2 = BroadcastLog(
        slot_id=slot.id,
        customer_id=cust3.id,
        message_sid="pre_msg_02",
        delivery_status="SENT",
        sent_at=datetime.now(timezone.utc),
    )
    db_session.add_all([pre_log1, pre_log2])
    await db_session.commit()

    # Trigger Broadcast API endpoint
    response = await client.post(f"/api/v1/slots/{slot.id}/broadcast")
    assert response.status_code == 202
    data = response.json()

    print("\n[BROADCAST API RESPONSE]")
    print(data)

    assert data["status"] == "queued"
    assert data["slot_id"] == slot.id
    assert data["total_matched"] == 3
    assert data["eligible_recipients"] == 2
    assert data["skipped_spam_guard"] == 1

    # Process the background task from Redis queue
    job_processed = await task_queue.process_one_job(timeout=2.0)
    assert job_processed is True

    # Assert MockMessageProvider received exactly 2 messages
    assert len(provider.sent_messages) == 2
    sent_phones = [m.phone_number for m in provider.sent_messages]
    assert cust1.phone_number in sent_phones
    assert cust2.phone_number in sent_phones
    assert cust3.phone_number not in sent_phones

    # Verify broadcast_logs in DB
    logs_stmt = (
        select(BroadcastLog)
        .where(
            BroadcastLog.slot_id == slot.id,
            BroadcastLog.customer_id.in_([cust1.id, cust2.id]),
        )
    )
    logs_res = await db_session.execute(logs_stmt)
    dispatched_logs = list(logs_res.scalars().all())

    assert len(dispatched_logs) == 2
    for l in dispatched_logs:
        assert l.delivery_status == "SENT"
        assert l.message_sid is not None
        assert l.message_sid.startswith("mock_msg_")

    # Verify slot status remains/reverts to OPEN for claiming
    await db_session.refresh(slot)
    assert slot.status == SlotStatus.OPEN
    print("Broadcast and spam-skipping verification succeeded!")
