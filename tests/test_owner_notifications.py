from datetime import datetime, timezone
from decimal import Decimal
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from src.models.business import Business
from src.models.customer import Customer
from src.models.service import Service
from src.models.slot import Slot, SlotStatus
from src.services.messaging.mock_provider import get_message_provider


@pytest.mark.asyncio
async def test_owner_alert_on_api_slot_claim(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Verify business owner receives instant WhatsApp notification when a slot is claimed via API."""
    provider = get_message_provider()
    provider.clear()

    uid = uuid.uuid4().hex[:6]
    owner_phone = f"+97258{uid}01"
    customer_phone = f"+97250{uid}02"

    biz = Business(
        name="קליניקת התראות בעלים",
        phone_number=owner_phone,
        business_type="clinic",
        slug=f"owner-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="טיפול פנים זוהר",
        duration_minutes=60,
        price=Decimal("400.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    cust = Customer(
        business_id=biz.id,
        full_name="מאיה כרמי",
        phone_number=customer_phone,
    )
    db_session.add(cust)
    await db_session.flush()

    slot = Slot(
        business_id=biz.id,
        service_id=svc.id,
        start_time=datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 12, 1, 11, 0, tzinfo=timezone.utc),
        status=SlotStatus.OPEN,
        version=1,
    )
    db_session.add(slot)
    await db_session.commit()

    # Claim slot via API
    claim_res = await client.post(
        f"/api/v1/slots/{slot.id}/claim",
        json={"customer_id": cust.id},
    )
    assert claim_res.status_code == 200
    assert claim_res.json()["success"] is True

    # Check messages dispatched to MockMessageProvider
    # Should have sent an alert to the business owner
    owner_msgs = [m for m in provider.sent_messages if m.phone_number == owner_phone]
    assert len(owner_msgs) == 1
    owner_msg = owner_msgs[0]

    assert "נתפס הרגע ע\"י מאיה כרמי" in owner_msg.body
    assert "טיפול פנים זוהר" in owner_msg.body
    assert customer_phone in owner_msg.body


@pytest.mark.asyncio
async def test_owner_alert_on_webhook_button_claim(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Verify winning interactive button click dispatches:
    1. Winner feedback to the customer.
    2. Real-time alert to the business owner closing the loop.
    """
    provider = get_message_provider()
    provider.clear()

    uid = uuid.uuid4().hex[:6]
    owner_phone = f"+97258{uid}03"
    customer_phone = f"+97250{uid}04"

    biz = Business(
        name="קליניקת כפתור בעלים",
        phone_number=owner_phone,
        business_type="clinic",
        slug=f"btn-owner-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="עיסוי הריון",
        duration_minutes=60,
        price=Decimal("380.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    cust = Customer(
        business_id=biz.id,
        full_name="טל שרון",
        phone_number=customer_phone,
    )
    db_session.add(cust)
    await db_session.flush()

    slot = Slot(
        business_id=biz.id,
        service_id=svc.id,
        start_time=datetime(2026, 12, 1, 14, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 12, 1, 15, 0, tzinfo=timezone.utc),
        status=SlotStatus.OPEN,
        version=1,
    )
    db_session.add(slot)
    await db_session.commit()

    # Simulate webhook button click
    button_click_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": customer_phone,
                                    "type": "interactive",
                                    "interactive": {
                                        "button_reply": {
                                            "id": f"claim:slot:{slot.id}:cust:{cust.id}",
                                            "title": "אני רוצה את התור!",
                                        }
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    res = await client.post("/api/v1/webhooks/whatsapp", json=button_click_payload)
    assert res.status_code == 200

    # 1. Check message sent to customer
    cust_msgs = [m for m in provider.sent_messages if m.phone_number == customer_phone]
    assert len(cust_msgs) == 1
    assert "התור נקבע בהצלחה" in cust_msgs[0].body

    # 2. Check message sent to business owner
    owner_msgs = [m for m in provider.sent_messages if m.phone_number == owner_phone]
    assert len(owner_msgs) == 1
    assert "נתפס הרגע ע\"י טל שרון" in owner_msgs[0].body
    assert "עיסוי הריון" in owner_msgs[0].body
