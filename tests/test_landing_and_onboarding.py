from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from src.models.business import Business
from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.service import Service
from src.models.slot import Slot
from src.core.security import create_business_access_token
from src.services.matching_service import calculate_day_of_week
from src.services.messaging.mock_provider import MockMessageProvider
from src.tasks.queue import task_queue


@pytest.mark.asyncio
async def test_landing_page_served_at_root(client: httpx.AsyncClient):
    """Verify that GET / returns the public SaaS Hebrew landing page."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "ממלאים תורים שהתבטלו ברגע האחרון" in response.text
    assert "SlotAlert" in response.text
    assert "onboarding" in response.text
    assert "dir=\"rtl\"" in response.text


@pytest.mark.asyncio
async def test_self_serve_business_registration_success(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Verify self-serve business registration with multiple dynamic services."""
    uid = uuid.uuid4().hex[:6]
    phone_digits = f"52{int(uuid.uuid4().int % 9000000 + 1000000)}"
    payload = {
        "name": f"קליניקת בדיקה {uid}",
        "phone_number": f"0{phone_digits}",
        "business_type": "clinic",
        "services": [
            {"name": "טיפול פנים קלאסי", "duration_minutes": 60, "price": 250.0},
            {"name": "פילינג עמוק", "duration_minutes": 45, "price": 350.0},
            {"name": "הסרת שיער בלייזר", "duration_minutes": 30, "price": 180.0},
        ],
    }

    res = await client.post("/api/v1/public/register-business", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()

    assert data["success"] is True
    assert data["name"] == payload["name"]
    assert "slug" in data
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["dashboard_url"] == f"/dashboard/{data['slug']}?token={data['access_token']}"

    # Verify DB state
    stmt = select(Business).where(Business.id == data["business_id"])
    biz_result = await db_session.execute(stmt)
    biz = biz_result.scalar_one_or_none()
    assert biz is not None
    assert biz.phone_number == f"+972{phone_digits}"  # Normalized to E.164
    assert biz.is_active is True

    # Verify services persisted
    svc_stmt = select(Service).where(Service.business_id == biz.id)
    svc_res = await db_session.execute(svc_stmt)
    services = svc_res.scalars().all()
    assert len(services) == 3
    names = {s.name for s in services}
    assert "טיפול פנים קלאסי" in names
    assert "פילינג עמוק" in names
    assert "הסרת שיער בלייזר" in names


@pytest.mark.asyncio
async def test_registration_slug_collision_resolution(
    client: httpx.AsyncClient,
):
    """Verify that slug collisions automatically append sequential counters."""
    uid = uuid.uuid4().hex[:5]
    phone1 = f"054{int(uuid.uuid4().int % 9000000 + 1000000)}"
    phone2 = f"054{int(uuid.uuid4().int % 9000000 + 1000000)}"
    base_name = f"קליניקה מיוחדת {uid}"
    payload1 = {
        "name": base_name,
        "phone_number": phone1,
        "business_type": "clinic",
        "services": [{"name": "ייעוץ", "duration_minutes": 30, "price": 100.0}],
    }
    payload2 = {
        "name": base_name,
        "phone_number": phone2,
        "business_type": "clinic",
        "services": [{"name": "ייעוץ חוזר", "duration_minutes": 30, "price": 100.0}],
    }

    res1 = await client.post("/api/v1/public/register-business", json=payload1)
    assert res1.status_code == 201
    data1 = res1.json()

    res2 = await client.post("/api/v1/public/register-business", json=payload2)
    assert res2.status_code == 201
    data2 = res2.json()

    assert data1["slug"] != data2["slug"]
    assert data2["slug"].startswith(data1["slug"])
    assert "-2" in data2["slug"]


@pytest.mark.asyncio
async def test_registration_custom_slug_specified(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Verify business registration when owner supplies a specific custom slug."""
    uid = uuid.uuid4().hex[:6]
    phone = f"050{int(uuid.uuid4().int % 9000000 + 1000000)}"
    custom_slug = f"luxury-spa-{uid}"
    payload = {
        "name": "ספא יוקרתי",
        "phone_number": phone,
        "business_type": "massage",
        "slug": custom_slug,
        "services": [{"name": "עיסוי שוודי", "duration_minutes": 60, "price": 320.0}],
    }

    res = await client.post("/api/v1/public/register-business", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["slug"] == custom_slug


@pytest.mark.asyncio
async def test_registration_validation_errors(client: httpx.AsyncClient):
    """Verify validation errors on invalid registration inputs."""
    # 1. Empty services list
    res_no_services = await client.post(
        "/api/v1/public/register-business",
        json={
            "name": "עסק ללא שירותים",
            "phone_number": "050-1234567",
            "services": [],
        },
    )
    assert res_no_services.status_code == 422

    # 2. Invalid phone number
    res_bad_phone = await client.post(
        "/api/v1/public/register-business",
        json={
            "name": "עסק עם טלפון שגוי",
            "phone_number": "not-a-phone",
            "services": [{"name": "טיפול", "duration_minutes": 30, "price": 100.0}],
        },
    )
    assert res_bad_phone.status_code == 422


@pytest.mark.asyncio
async def test_quick_publish_custom_ad_hoc_slot_and_matching(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Verify quick-publishing a custom ad-hoc slot (service_id=None, custom_service_name, custom_price)
    matches general waitlist candidates and broadcasts with the custom title and price.
    """
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name=f"מכון בדיקה {uid}",
        phone_number=f"+97250{uid}01",
        business_type="clinic",
        slug=f"custom-slot-biz-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    # Create a customer who registered with general interest (no specific service)
    # Slot target is Sunday morning (e.g. 2026-11-01 is Sunday)
    target_start = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
    day_of_week = calculate_day_of_week(target_start)

    customer = Customer(
        business_id=biz.id,
        full_name="שרה הממתינה",
        phone_number=f"+97250{uid}99",
    )
    db_session.add(customer)
    await db_session.flush()

    # Preference: Sunday, morning (09:00 - 13:00), service_id is NULL (any service)
    pref = CustomerPreference(
        customer_id=customer.id,
        day_of_week=day_of_week,
        time_slot="MORNING",
        service_id=None,
    )
    db_session.add(pref)
    await db_session.commit()

    token = create_business_access_token(business_id=biz.id, slug=biz.slug)

    # Business publishes custom ad-hoc slot
    publish_payload = {
        "service_id": None,
        "custom_service_name": "טיפול זוהר אקספרס מיוחד",
        "custom_price": 175.0,
        "duration_minutes": 40,
        "start_time": target_start.isoformat(),
    }

    res = await client.post(
        f"/api/v1/business/{biz.slug}/quick-publish",
        headers={"Authorization": f"Bearer {token}"},
        json=publish_payload,
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["status"] in ("OPEN", "SENDING")
    assert data["total_matched"] >= 1
    assert data["broadcast_status"].lower() in ("queued", "completed")

    # Verify slot attributes in DB
    stmt = select(Slot).where(Slot.id == data["slot_id"])
    slot_res = await db_session.execute(stmt)
    db_slot = slot_res.scalar_one_or_none()
    assert db_slot is not None
    assert db_slot.service_id is None
    assert db_slot.custom_service_name == "טיפול זוהר אקספרס מיוחד"
    assert db_slot.custom_price == Decimal("175.0")
    assert db_slot.effective_service_name == "טיפול זוהר אקספרס מיוחד"
    assert db_slot.effective_price == Decimal("175.0")
