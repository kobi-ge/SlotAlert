from datetime import datetime, timezone
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from src.models.business import Business
from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.service import Service
from src.models.slot import Slot, SlotStatus
from src.services.matching_service import (
    calculate_day_of_week,
    determine_time_slot,
    find_matching_customers,
)


def test_time_slot_and_day_calculation():
    """Verify conversion of datetime to day_of_week and time_slot category."""
    # 2026-09-06 is Sunday (Python weekday=6 -> calculated 0)
    sunday_morning = datetime(2026, 9, 6, 9, 30, tzinfo=timezone.utc)
    assert calculate_day_of_week(sunday_morning) == 0
    assert determine_time_slot(sunday_morning) == "MORNING"

    # 2026-09-08 is Tuesday (Python weekday=1 -> calculated 2)
    tuesday_afternoon = datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)
    assert calculate_day_of_week(tuesday_afternoon) == 2
    assert determine_time_slot(tuesday_afternoon) == "AFTERNOON"

    # 2026-09-10 is Thursday (Python weekday=3 -> calculated 4)
    thursday_evening = datetime(2026, 9, 10, 19, 0, tzinfo=timezone.utc)
    assert calculate_day_of_week(thursday_evening) == 4
    assert determine_time_slot(thursday_evening) == "EVENING"


@pytest.mark.asyncio
async def test_find_matching_customers(
    db_session: AsyncSession,
    test_business: Business,
    test_service: Service,
):
    """Test matching customers based on day, time slot, and service preference."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    # Create distinct customer A: matches Sunday Morning, test_service
    cust_a = Customer(
        business_id=test_business.id,
        full_name="לקוח התאמה א",
        phone_number=f"+97250{uid}01",
    )
    # Create customer B: matches Sunday Morning, service=None (accepts any service)
    cust_b = Customer(
        business_id=test_business.id,
        full_name="לקוח התאמה ב",
        phone_number=f"+97250{uid}02",
    )
    # Create customer C: matches Monday Afternoon (different day & time)
    cust_c = Customer(
        business_id=test_business.id,
        full_name="לקוח לא מתאים",
        phone_number=f"+97250{uid}03",
    )
    db_session.add_all([cust_a, cust_b, cust_c])
    await db_session.flush()

    pref_a = CustomerPreference(
        customer_id=cust_a.id,
        day_of_week=0,  # Sunday
        time_slot="MORNING",
        service_id=test_service.id,
    )
    pref_b = CustomerPreference(
        customer_id=cust_b.id,
        day_of_week=0,  # Sunday
        time_slot="MORNING",
        service_id=None,  # Any service
    )
    pref_c = CustomerPreference(
        customer_id=cust_c.id,
        day_of_week=1,  # Monday
        time_slot="AFTERNOON",
        service_id=test_service.id,
    )
    db_session.add_all([pref_a, pref_b, pref_c])
    await db_session.flush()

    # Create slot for Sunday at 10:00 (Sunday=0, MORNING)
    slot_sunday = Slot(
        business_id=test_business.id,
        service_id=test_service.id,
        start_time=datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 6, 11, 0, tzinfo=timezone.utc),
        status=SlotStatus.OPEN,
        version=1,
    )
    db_session.add(slot_sunday)
    await db_session.commit()
    await db_session.refresh(slot_sunday)

    matched = await find_matching_customers(db_session, slot_sunday.id)
    matched_ids = [c.id for c in matched]

    # Must contain cust_a and cust_b, must NOT contain cust_c
    assert cust_a.id in matched_ids
    assert cust_b.id in matched_ids
    assert cust_c.id not in matched_ids


@pytest.mark.asyncio
async def test_candidates_endpoint(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_business: Business,
    test_service: Service,
):
    """Test GET /api/v1/slots/{slot_id}/candidates API endpoint."""
    # Create slot
    slot = Slot(
        business_id=test_business.id,
        service_id=test_service.id,
        start_time=datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 6, 11, 0, tzinfo=timezone.utc),
        status=SlotStatus.OPEN,
        version=1,
    )
    db_session.add(slot)
    await db_session.commit()
    await db_session.refresh(slot)

    # Valid candidates query
    res = await client.get(f"/api/v1/slots/{slot.id}/candidates")
    assert res.status_code == 200
    candidates = res.json()
    assert isinstance(candidates, list)

    # 404 for non-existent slot
    res_404 = await client.get("/api/v1/slots/99999999/candidates")
    assert res_404.status_code == 404
