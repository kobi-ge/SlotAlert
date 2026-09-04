from decimal import Decimal
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from src.core.security import create_business_access_token
from src.models.business import Business
from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.service import Service


@pytest.mark.asyncio
async def test_manual_customer_creation_with_preferences(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Test owner adding client with specific days/times/services via authenticated dashboard API:
    - Business owner sends POST /api/v1/business/{slug}/customers with days_of_week=[0, 2], time_slots=["MORNING"], and specific service_ids.
    - Assert customer record is created and linked CustomerPreference entries match database records.
    - Trigger preview for Sunday morning -> customer matches. Trigger for Monday afternoon -> customer does NOT match.
    """
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת בדיקה ידנית",
        phone_number=f"+97250{uid}11",
        business_type="clinic",
        slug=f"manual-cust-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc1 = Service(
        business_id=biz.id,
        name="טיפול פנים",
        duration_minutes=60,
        price=Decimal("250.00"),
    )
    svc2 = Service(
        business_id=biz.id,
        name="טיפול יופי",
        duration_minutes=45,
        price=Decimal("180.00"),
    )
    db_session.add_all([svc1, svc2])
    await db_session.commit()

    token = create_business_access_token(biz.id, biz.slug)
    headers = {"Authorization": f"Bearer {token}"}

    # Owner adds customer with days [0 (Sunday), 2 (Tuesday)], MORNING, svc1 only
    payload = {
        "full_name": "מיכל אברהם",
        "phone_number": "052-9876543",
        "service_ids": [svc1.id],
        "days_of_week": [0, 2],
        "time_slots": ["MORNING"],
    }

    res = await client.post(
        f"/api/v1/business/{biz.slug}/customers",
        json=payload,
        headers=headers,
    )
    assert res.status_code == 201, f"Expected 201 Created, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["success"] is True
    cust_id = data["customer_id"]

    # Verify Customer in DB
    cust_res = await db_session.execute(select(Customer).where(Customer.id == cust_id))
    customer = cust_res.scalar_one()
    assert customer.full_name == "מיכל אברהם"
    assert customer.phone_number == "+972529876543"

    # Verify CustomerPreference rows in DB (2 days * 1 slot * 1 service = 2 rows)
    pref_res = await db_session.execute(
        select(CustomerPreference).where(CustomerPreference.customer_id == cust_id)
    )
    prefs = list(pref_res.scalars().all())
    assert len(prefs) == 2

    pref_days = {p.day_of_week for p in prefs}
    assert pref_days == {0, 2}
    for p in prefs:
        assert p.time_slot == "MORNING"
        assert p.service_id == svc1.id

    # 1. Preview candidates for Sunday Morning (2026-09-06 10:00 is Sunday) with svc1 -> matches 1
    res_match = await client.post(
        f"/api/v1/business/{biz.slug}/preview-candidates",
        json={
            "service_id": svc1.id,
            "start_time": "2026-09-06T10:00:00",
        },
    )
    assert res_match.status_code == 200
    assert res_match.json()["matched_count"] == 1

    # 2. Preview for Monday Afternoon (2026-09-07 14:00 is Monday) -> does NOT match (0)
    res_no_match = await client.post(
        f"/api/v1/business/{biz.slug}/preview-candidates",
        json={
            "service_id": svc1.id,
            "start_time": "2026-09-07T14:00:00",
        },
    )
    assert res_no_match.status_code == 200
    assert res_no_match.json()["matched_count"] == 0
