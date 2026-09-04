from datetime import datetime, timezone
from decimal import Decimal
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from src.models.business import Business
from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.service import Service
from src.core.security import create_business_access_token
from src.models.slot import Slot, SlotStatus
from src.tasks.queue import task_queue


@pytest.mark.asyncio
async def test_business_dashboard_summary(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Test GET /api/v1/business/{slug}/dashboard returns active customer count and recent slots."""
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת בדיקת דשבורד",
        phone_number=f"+97250{uid}01",
        business_type="clinic",
        slug=f"dash-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="מניקור",
        duration_minutes=45,
        price=Decimal("120.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    cust1 = Customer(
        business_id=biz.id,
        full_name="לקוח 1",
        phone_number=f"+97250{uid}11",
    )
    cust2 = Customer(
        business_id=biz.id,
        full_name="לקוח 2",
        phone_number=f"+97250{uid}12",
    )
    db_session.add_all([cust1, cust2])
    await db_session.flush()

    slot = Slot(
        business_id=biz.id,
        service_id=svc.id,
        start_time=datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc),
        status=SlotStatus.CLAIMED,
        claimed_by_customer_id=cust1.id,
        version=2,
    )
    db_session.add(slot)
    await db_session.commit()

    token = create_business_access_token(biz.id, biz.slug)
    res = await client.get(
        f"/api/v1/business/{biz.slug}/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()

    assert data["business_name"] == "קליניקת בדיקת דשבורד"
    assert data["slug"] == biz.slug
    assert data["active_waitlist_count"] == 2
    assert len(data["recent_slots"]) >= 1

    recent = data["recent_slots"][0]
    assert recent["service_name"] == "מניקור"
    assert recent["status"] == "CLAIMED"
    assert recent["claimed_by_name"] == "לקוח 1"
    assert recent["claimed_by_phone"] == cust1.phone_number


@pytest.mark.asyncio
async def test_preview_candidates(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Test POST /api/v1/business/{slug}/preview-candidates calculates correct count without creating a slot."""
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת תצוגה מקדימה",
        phone_number=f"+97250{uid}02",
        business_type="clinic",
        slug=f"preview-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="פדיקור",
        duration_minutes=60,
        price=Decimal("150.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    # Create 2 matching customers for Sunday (day 0) Morning (09:00)
    for i in range(2):
        c = Customer(
            business_id=biz.id,
            full_name=f"ממתין {i}",
            phone_number=f"+97250{uid}2{i}",
        )
        db_session.add(c)
        await db_session.flush()
        pref = CustomerPreference(
            customer_id=c.id,
            day_of_week=0,  # Sunday
            time_slot="MORNING",
            service_id=svc.id,
        )
        db_session.add(pref)

    await db_session.commit()

    # Sunday morning test: 2026-09-06 is a Sunday, 09:30 UTC is MORNING
    sunday_morning = "2026-09-06T09:30:00Z"
    payload = {
        "service_id": svc.id,
        "start_time": sunday_morning,
    }

    res = await client.get(f"/b/{biz.slug}")  # verify landing page route
    assert res.status_code == 200

    res_prev = await client.post(
        f"/api/v1/business/{biz.slug}/preview-candidates",
        json=payload,
    )
    assert res_prev.status_code == 200
    data = res_prev.json()
    assert data["matched_count"] == 2
    assert "ראשון" in data["day_name"]
    assert "בוקר" in data["time_slot_label"]


@pytest.mark.asyncio
async def test_quick_publish_slot_and_broadcast(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Test POST /api/v1/business/{slug}/quick-publish creates slot and queues broadcast job atomically."""
    from src.database.connection import get_redis_client
    redis = get_redis_client()
    await redis.delete(task_queue.queue_key)

    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת פרסום מהיר",
        phone_number=f"+97250{uid}03",
        business_type="clinic",
        slug=f"quick-pub-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="עיסוי שוודי",
        duration_minutes=60,
        price=Decimal("280.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    # Add 1 matching customer
    c = Customer(
        business_id=biz.id,
        full_name="אורח מהיר",
        phone_number=f"+97250{uid}31",
    )
    db_session.add(c)
    await db_session.flush()
    pref = CustomerPreference(
        customer_id=c.id,
        day_of_week=0,  # Sunday
        time_slot="MORNING",
        service_id=None,
    )
    db_session.add(pref)
    await db_session.commit()

    # Quick publish for Sunday morning
    quick_payload = {
        "service_id": svc.id,
        "start_time": "2026-09-06T10:00:00Z",
    }

    token = create_business_access_token(biz.id, biz.slug)
    res = await client.post(
        f"/api/v1/business/{biz.slug}/quick-publish",
        json=quick_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201
    data = res.json()

    assert data["broadcast_status"] == "queued"
    assert data["total_matched"] == 1
    assert data["eligible_recipients"] == 1
    assert data["skipped_spam_guard"] == 0

    # Verify task was placed in Redis queue
    job_processed = await task_queue.process_one_job(timeout=1)
    assert job_processed is True


@pytest.mark.asyncio
async def test_waitlist_management_manual_add(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Test manual customer addition and listing in waitlist."""
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת רשימה ידנית",
        phone_number=f"+97250{uid}04",
        business_type="clinic",
        slug=f"manual-cust-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.commit()

    token = create_business_access_token(biz.id, biz.slug)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Add customer manually
    add_payload = {
        "full_name": "יוסי כהן ידני",
        "phone_number": "054-987-6543",
        "days_of_week": [0, 1],
        "time_slots": ["MORNING"],
    }
    res_add = await client.post(
        f"/api/v1/business/{biz.slug}/waitlist",
        json=add_payload,
        headers=headers,
    )
    assert res_add.status_code == 201
    assert res_add.json()["success"] is True

    # 2. List customers
    res_list = await client.get(
        f"/api/v1/business/{biz.slug}/waitlist",
        headers=headers,
    )
    assert res_list.status_code == 200
    custs = res_list.json()
    assert len(custs) >= 1
    assert custs[0]["full_name"] == "יוסי כהן ידני"
    assert custs[0]["phone_number"] == "+972549876543"

    # 3. Verify serving dashboard HTML
    res_dash_html = await client.get(f"/dashboard/{biz.slug}")
    assert res_dash_html.status_code == 200
    assert "text/html" in res_dash_html.headers.get("content-type", "")
    assert "פרסם תור שהתבטל" in res_dash_html.text
