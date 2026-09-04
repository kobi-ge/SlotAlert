from decimal import Decimal
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from src.config.settings import get_settings
from src.models.broadcast_log import BroadcastLog
from src.models.business import Business
from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.service import Service
from src.models.slot import Slot, SlotStatus
from src.services.messaging.mock_provider import get_message_provider

settings = get_settings()


@pytest.mark.asyncio
async def test_webhook_verification_handshake(client: httpx.AsyncClient):
    """Test Meta WhatsApp Webhook GET verification handshake."""
    # 1. Valid handshake
    valid_params = {
        "hub.mode": "subscribe",
        "hub.verify_token": settings.WHATSAPP_VERIFY_TOKEN,
        "hub.challenge": "11582012",
    }
    res_valid = await client.get("/api/v1/webhooks/whatsapp", params=valid_params)
    assert res_valid.status_code == 200
    assert res_valid.text == "11582012"

    # Also test at root route /webhooks/whatsapp
    res_root = await client.get("/webhooks/whatsapp", params=valid_params)
    assert res_root.status_code == 200
    assert res_root.text == "11582012"

    # 2. Invalid verify token
    invalid_params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong-secret-token",
        "hub.challenge": "11582012",
    }
    res_invalid = await client.get("/api/v1/webhooks/whatsapp", params=invalid_params)
    assert res_invalid.status_code == 403


@pytest.mark.asyncio
async def test_webhook_delivery_status_updates(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Test webhook delivery status updates (delivered, read) updating broadcast_logs."""
    uid = uuid.uuid4().hex[:6]
    test_sid = f"wamid_test_{uid}"

    # Setup test entities
    biz = Business(
        name="מרפאת בדיקת סטטוס",
        phone_number=f"+97258{uid}22",
        business_type="clinic",
        slug=f"status-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="טיפול בדיקה",
        duration_minutes=60,
        price=Decimal("180.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    cust = Customer(
        business_id=biz.id,
        full_name="לקוח סטטוס",
        phone_number=f"+97250{uid}22",
    )
    db_session.add(cust)
    await db_session.flush()

    slot = Slot(
        business_id=biz.id,
        service_id=svc.id,
        start_time=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc),
        status=SlotStatus.OPEN,
        version=1,
    )
    db_session.add(slot)
    await db_session.flush()

    log = BroadcastLog(
        slot_id=slot.id,
        customer_id=cust.id,
        message_sid=test_sid,
        delivery_status="SENT",
        sent_at=datetime.now(timezone.utc),
    )
    db_session.add(log)
    await db_session.commit()

    # 1. Simulate 'delivered' status update
    payload_delivered = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": test_sid,
                                    "status": "delivered",
                                    "recipient_id": cust.phone_number,
                                    "timestamp": "1725350000",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    res1 = await client.post("/api/v1/webhooks/whatsapp", json=payload_delivered)
    assert res1.status_code == 200

    await db_session.refresh(log)
    assert log.delivery_status == "DELIVERED"

    # 2. Simulate 'read' status update
    payload_read = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": test_sid,
                                    "status": "read",
                                    "recipient_id": cust.phone_number,
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    res2 = await client.post("/api/v1/webhooks/whatsapp", json=payload_read)
    assert res2.status_code == 200

    await db_session.refresh(log)
    assert log.delivery_status == "READ"


@pytest.mark.asyncio
async def test_webhook_interactive_winning_claim_click(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Test winning interactive button click: claims slot and sends winner notification."""
    provider = get_message_provider()
    provider.clear()

    uid = uuid.uuid4().hex[:6]

    biz = Business(
        name="קליניקת זוכה",
        phone_number=f"+97258{uid}33",
        business_type="clinic",
        slug=f"winner-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="טיפול פנים זוכה",
        duration_minutes=60,
        price=Decimal("300.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    cust = Customer(
        business_id=biz.id,
        full_name="נועה הזוכה",
        phone_number=f"+97250{uid}33",
    )
    db_session.add(cust)
    await db_session.flush()

    slot = Slot(
        business_id=biz.id,
        service_id=svc.id,
        start_time=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc),
        status=SlotStatus.OPEN,
        version=1,
    )
    db_session.add(slot)
    await db_session.commit()

    # Simulate Meta interactive button reply payload
    button_click_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": cust.phone_number,
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
    assert res.json() == {"status": "ok"}

    # Verify slot was claimed
    await db_session.refresh(slot)
    assert slot.status == SlotStatus.CLAIMED
    assert slot.claimed_by_customer_id == cust.id
    assert slot.version == 2

    # Verify winner text message was sent to customer and alert sent to owner
    cust_msgs = [m for m in provider.sent_messages if m.phone_number == cust.phone_number]
    assert len(cust_msgs) == 1
    assert "התור נקבע בהצלחה" in cust_msgs[0].body
    assert "נועה הזוכה" in cust_msgs[0].body

    owner_msgs = [m for m in provider.sent_messages if m.phone_number == biz.phone_number]
    assert len(owner_msgs) == 1
    assert "נתפס הרגע ע\"י נועה הזוכה" in owner_msgs[0].body


@pytest.mark.asyncio
async def test_webhook_interactive_losing_claim_click(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Test losing interactive button click: slot is already claimed, sends rejection message."""
    provider = get_message_provider()
    provider.clear()

    uid = uuid.uuid4().hex[:6]

    biz = Business(
        name="קליניקת הפסד",
        phone_number=f"+97258{uid}44",
        business_type="clinic",
        slug=f"loser-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="עיסוי",
        duration_minutes=60,
        price=Decimal("350.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    cust_winner = Customer(
        business_id=biz.id,
        full_name="הראשון",
        phone_number=f"+97250{uid}41",
    )
    cust_loser = Customer(
        business_id=biz.id,
        full_name="המאחר",
        phone_number=f"+97250{uid}42",
    )
    db_session.add_all([cust_winner, cust_loser])
    await db_session.flush()

    # Create slot that is ALREADY CLAIMED by cust_winner
    slot = Slot(
        business_id=biz.id,
        service_id=svc.id,
        start_time=datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc),
        status=SlotStatus.CLAIMED,
        claimed_by_customer_id=cust_winner.id,
        version=2,
    )
    db_session.add(slot)
    await db_session.commit()

    # Simulate losing customer clicking the button
    losing_click_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": cust_loser.phone_number,
                                    "type": "interactive",
                                    "interactive": {
                                        "button_reply": {
                                            "id": f"claim:slot:{slot.id}:cust:{cust_loser.id}",
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

    res = await client.post("/api/v1/webhooks/whatsapp", json=losing_click_payload)
    assert res.status_code == 200

    # Verify slot remains claimed by the original winner
    await db_session.refresh(slot)
    assert slot.claimed_by_customer_id == cust_winner.id
    assert slot.version == 2

    # Verify loser received the "someone beat you" feedback message
    assert len(provider.sent_messages) == 1
    sent_msg = provider.sent_messages[0]
    assert sent_msg.phone_number == cust_loser.phone_number
    assert "מישהו הקדים אותך" in sent_msg.body


@pytest.mark.asyncio
async def test_webhook_optout_button_and_keyword(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Test opt-out via button click and text keywords ('הסר', 'STOP')."""
    provider = get_message_provider()
    provider.clear()

    uid = uuid.uuid4().hex[:6]

    biz = Business(
        name="קליניקת הסרה",
        phone_number=f"+97258{uid}55",
        business_type="clinic",
        slug=f"optout-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    # 1. Test Opt-out via Button Click
    cust_btn = Customer(
        business_id=biz.id,
        full_name="לקוח כפתור הסר",
        phone_number=f"+97250{uid}51",
    )
    db_session.add(cust_btn)
    await db_session.flush()

    pref_btn = CustomerPreference(
        customer_id=cust_btn.id,
        day_of_week=1,
        time_slot="MORNING",
        service_id=None,
    )
    db_session.add(pref_btn)
    await db_session.commit()

    # Button reply payload
    button_optout_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": cust_btn.phone_number,
                                    "type": "interactive",
                                    "interactive": {
                                        "button_reply": {
                                            "id": f"optout:cust:{cust_btn.id}",
                                            "title": "הסר אותי",
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
    res1 = await client.post("/api/v1/webhooks/whatsapp", json=button_optout_payload)
    assert res1.status_code == 200

    # Preferences should be deleted
    prefs_res = await db_session.execute(
        select(CustomerPreference).where(CustomerPreference.customer_id == cust_btn.id)
    )
    assert len(list(prefs_res.scalars().all())) == 0

    # Confirmation sent
    assert len(provider.sent_messages) == 1
    assert "הוסרת בהצלחה" in provider.sent_messages[0].body

    # 2. Test Opt-out via Text Keyword "הסר"
    cust_text = Customer(
        business_id=biz.id,
        full_name="לקוח טקסט הסר",
        phone_number=f"+97250{uid}52",
    )
    db_session.add(cust_text)
    await db_session.flush()

    pref_text = CustomerPreference(
        customer_id=cust_text.id,
        day_of_week=2,
        time_slot="EVENING",
        service_id=None,
    )
    db_session.add(pref_text)
    await db_session.commit()

    text_optout_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": cust_text.phone_number,
                                    "type": "text",
                                    "text": {
                                        "body": "הסר",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    res2 = await client.post("/api/v1/webhooks/whatsapp", json=text_optout_payload)
    assert res2.status_code == 200

    prefs_res2 = await db_session.execute(
        select(CustomerPreference).where(CustomerPreference.customer_id == cust_text.id)
    )
    assert len(list(prefs_res2.scalars().all())) == 0
    assert len(provider.sent_messages) == 2
    assert "הוסרת בהצלחה" in provider.sent_messages[1].body
