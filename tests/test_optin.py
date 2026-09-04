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
from src.schemas.customer import normalize_israeli_phone
from src.services.messaging.mock_provider import get_message_provider


def test_israeli_phone_normalization():
    """Verify normalization of various Israeli phone formats to E.164."""
    # Standard 10-digit with leading 0
    assert normalize_israeli_phone("0501234567") == "+972501234567"
    assert normalize_israeli_phone("052-1234567") == "+972521234567"
    assert normalize_israeli_phone("054-123-4567") == "+972541234567"
    assert normalize_israeli_phone("053 987 6543") == "+972539876543"

    # With country code 972 / +972
    assert normalize_israeli_phone("972501234567") == "+972501234567"
    assert normalize_israeli_phone("+972501234567") == "+972501234567"
    assert normalize_israeli_phone("+972-50-123-4567") == "+972501234567"

    # 9-digit without leading 0
    assert normalize_israeli_phone("501234567") == "+972501234567"

    # Invalid formats should raise ValueError
    with pytest.raises(ValueError):
        normalize_israeli_phone("031234567")  # Landline

    with pytest.raises(ValueError):
        normalize_israeli_phone("12345")  # Too short

    with pytest.raises(ValueError):
        normalize_israeli_phone("050123456789")  # Too long


@pytest.mark.asyncio
async def test_get_public_business_profile(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Verify GET /api/v1/public/b/{slug} returns profile and services."""
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת בדיקה ציבורית",
        phone_number=f"+97250{uid}77",
        business_type="aesthetics",
        slug=f"public-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc1 = Service(
        business_id=biz.id,
        name="טיפול לייזר",
        duration_minutes=45,
        price=Decimal("450.00"),
    )
    svc2 = Service(
        business_id=biz.id,
        name="פילינג עמוק",
        duration_minutes=60,
        price=Decimal("500.00"),
    )
    db_session.add_all([svc1, svc2])
    await db_session.commit()

    # 1. Existing business query
    res = await client.get(f"/api/v1/public/b/{biz.slug}")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "קליניקת בדיקה ציבורית"
    assert data["slug"] == biz.slug
    assert len(data["services"]) == 2
    service_names = [s["name"] for s in data["services"]]
    assert "טיפול לייזר" in service_names
    assert "פילינג עמוק" in service_names

    # 2. Non-existent slug returns 404
    res_404 = await client.get("/api/v1/public/b/non-existent-clinic-slug")
    assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_customer_optin_registration_and_idempotency(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Test customer registration flow:
    - Creates customer and preference records
    - Dispatches WhatsApp welcome message
    - Idempotent re-registration updates customer name and replaces preferences cleanly
    """
    provider = get_message_provider()
    provider.clear()

    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת הרשמה",
        phone_number=f"+97250{uid}88",
        business_type="clinic",
        slug=f"reg-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="טיפול פנים",
        duration_minutes=60,
        price=Decimal("350.00"),
    )
    db_session.add(svc)
    await db_session.commit()

    phone_input = "052-765-4321"

    # 1. First registration
    payload1 = {
        "full_name": "שירה כהן",
        "phone_number": phone_input,
        "service_ids": [svc.id],
        "days_of_week": [0, 2],  # Sunday, Tuesday
        "time_slots": ["MORNING", "EVENING"],
    }

    res1 = await client.post(f"/api/v1/public/b/{biz.slug}/register", json=payload1)
    assert res1.status_code == 201
    data1 = res1.json()
    assert data1["success"] is True
    customer_id = data1["customer_id"]

    # Verify customer in DB
    cust_res = await db_session.execute(
        select(Customer).where(Customer.id == customer_id)
    )
    customer = cust_res.scalar_one()
    assert customer.full_name == "שירה כהן"
    assert customer.phone_number == "+972527654321"

    # Verify preferences count: 2 days * 2 time slots * 1 service = 4 preferences
    prefs_res = await db_session.execute(
        select(CustomerPreference).where(CustomerPreference.customer_id == customer_id)
    )
    prefs1 = list(prefs_res.scalars().all())
    assert len(prefs1) == 4

    # Verify automated welcome WhatsApp was dispatched
    assert len(provider.sent_messages) == 1
    welcome_msg = provider.sent_messages[0]
    assert welcome_msg.phone_number == "+972527654321"
    assert "שירה כהן" in welcome_msg.body
    assert "קליניקת הרשמה" in welcome_msg.body

    # 2. Idempotent re-registration: same phone, new name, new preferences
    payload2 = {
        "full_name": "שירה לוי-כהן",  # Updated name
        "phone_number": "0527654321",  # Same phone, different formatting
        "service_ids": [],  # Any service
        "days_of_week": [4],  # Only Thursday
        "time_slots": ["AFTERNOON"],
    }

    res2 = await client.post(f"/api/v1/public/b/{biz.slug}/register", json=payload2)
    assert res2.status_code == 201
    data2 = res2.json()
    assert data2["success"] is True
    assert data2["customer_id"] == customer_id  # Same customer ID!

    # Verify customer updated in DB without duplicate key error
    await db_session.refresh(customer)
    assert customer.full_name == "שירה לוי-כהן"

    # Verify previous preferences were replaced: 1 day * 1 time slot * 1 (None) = 1 preference
    prefs_res2 = await db_session.execute(
        select(CustomerPreference).where(CustomerPreference.customer_id == customer_id)
    )
    prefs2 = list(prefs_res2.scalars().all())
    assert len(prefs2) == 1
    assert prefs2[0].day_of_week == 4
    assert prefs2[0].time_slot == "AFTERNOON"
    assert prefs2[0].service_id is None


@pytest.mark.asyncio
async def test_serve_optin_landing_page(client: httpx.AsyncClient):
    """Test GET /b/{slug} serves HTML landing page."""
    res = await client.get("/b/shiran-clinic")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "SlotAlert" in res.text
    assert "הצטרף לרשימת ההמתנה" in res.text


@pytest.mark.asyncio
async def test_customer_optin_requires_at_least_one_day_and_slot(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Verify customer opt-in endpoint rejects payloads with empty days or empty time_slots
    with 422 Unprocessable Entity.
    """
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת ולידציה",
        phone_number=f"+97250{uid}99",
        business_type="clinic",
        slug=f"val-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.commit()

    base_payload = {
        "full_name": "ישראל ישראלי",
        "phone_number": "0501234567",
        "service_ids": [],
    }

    # 1. Reject empty days_of_week
    res_no_days = await client.post(
        f"/api/v1/public/b/{biz.slug}/register",
        json={**base_payload, "days_of_week": [], "time_slots": ["MORNING"]},
    )
    assert res_no_days.status_code in (422, 400)

    # 2. Reject empty time_slots
    res_no_slots = await client.post(
        f"/api/v1/public/b/{biz.slug}/register",
        json={**base_payload, "days_of_week": [0], "time_slots": []},
    )
    assert res_no_slots.status_code in (422, 400)

    # 3. Reject both empty
    res_both_empty = await client.post(
        f"/api/v1/public/b/{biz.slug}/register",
        json={**base_payload, "days_of_week": [], "time_slots": []},
    )
    assert res_both_empty.status_code in (422, 400)

