from datetime import datetime, timezone
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from src.core.security import create_business_access_token
from src.models.business import Business
from src.models.customer import Customer
from src.models.service import Service
from src.models.slot import Slot, SlotStatus


@pytest.mark.asyncio
async def test_owner_cancels_open_slot_and_claim_fails(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Test slot cancellation flow:
    1. Publish a slot in status OPEN.
    2. Owner calls DELETE /api/v1/business/{slug}/slots/{slot_id} with auth token.
    3. Assert slot status transitions to CANCELLED.
    4. A client attempts POST /api/v1/slots/{slot_id}/claim.
    5. Assert response is 409 Conflict with 'Slot already taken or no longer available.'.
    """
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת ביטול תור",
        phone_number=f"+97250{uid}22",
        business_type="clinic",
        slug=f"cancel-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="טיפול לייזר",
        duration_minutes=45,
        price=Decimal("350.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    cust = Customer(
        business_id=biz.id,
        full_name="לקוח מנסה לתפוס",
        phone_number=f"+97250{uid}99",
    )
    db_session.add(cust)
    await db_session.flush()

    # Create slot in OPEN status
    slot = Slot(
        business_id=biz.id,
        service_id=svc.id,
        start_time=datetime(2026, 9, 10, 11, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 10, 11, 45, tzinfo=timezone.utc),
        status=SlotStatus.OPEN,
        version=1,
    )
    db_session.add(slot)
    await db_session.commit()

    token = create_business_access_token(biz.id, biz.slug)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Owner cancels the slot via DELETE
    del_res = await client.delete(
        f"/api/v1/business/{biz.slug}/slots/{slot.id}",
        headers=headers,
    )
    assert del_res.status_code == 200, f"Expected 200 OK, got {del_res.status_code}: {del_res.text}"
    del_data = del_res.json()
    assert del_data["status"] == "CANCELLED"

    # Verify status in database
    await db_session.refresh(slot)
    assert slot.status == SlotStatus.CANCELLED

    # 2. Client attempts to claim the cancelled slot
    claim_res = await client.post(
        f"/api/v1/slots/{slot.id}/claim",
        json={"customer_id": cust.id},
    )
    assert claim_res.status_code == 409
    claim_data = claim_res.json()
    assert claim_data["success"] is False
    assert "Slot already taken or no longer available." in claim_data["message"]
    assert claim_data["slot"] is None


@pytest.mark.asyncio
async def test_owner_cannot_cancel_already_claimed_slot(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Assert that attempting to cancel a slot that is already CLAIMED returns 400 Bad Request.
    """
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת תור תפוס",
        phone_number=f"+97250{uid}33",
        business_type="clinic",
        slug=f"claimed-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="טיפול פדיקור",
        duration_minutes=30,
        price=Decimal("120.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    cust = Customer(
        business_id=biz.id,
        full_name="לקוח תפס כבר",
        phone_number=f"+97250{uid}77",
    )
    db_session.add(cust)
    await db_session.flush()

    # Slot is already CLAIMED
    slot = Slot(
        business_id=biz.id,
        service_id=svc.id,
        start_time=datetime(2026, 9, 12, 16, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 12, 16, 30, tzinfo=timezone.utc),
        status=SlotStatus.CLAIMED,
        claimed_by_customer_id=cust.id,
        version=2,
    )
    db_session.add(slot)
    await db_session.commit()

    token = create_business_access_token(biz.id, biz.slug)
    headers = {"Authorization": f"Bearer {token}"}

    # Attempt to cancel
    res = await client.delete(
        f"/api/v1/business/{biz.slug}/slots/{slot.id}",
        headers=headers,
    )
    assert res.status_code == 400
    assert "לא ניתן לבטל תור שכבר נתפס" in res.json()["detail"]
