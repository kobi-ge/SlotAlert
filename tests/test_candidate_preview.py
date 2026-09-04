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


@pytest.mark.asyncio
async def test_preview_candidates_16_00_boundary_regression(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Regression Test for Prompt 11:
    Ensure POST /api/v1/business/{slug}/preview-candidates at exactly 16:00:
    1. Returns 200 OK (no 500 Internal Server Error).
    2. Correctly categorizes 16:00 as EVENING.
    3. Matches customers registered for EVENING.
    4. Populates a non-empty Hebrew time_slot_label without Pydantic validation error.
    """
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת בדיקת גבולות",
        phone_number=f"+97250{uid}70",
        business_type="clinic",
        slug=f"boundary-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    svc = Service(
        business_id=biz.id,
        name="טיפול ערב מיוחד",
        duration_minutes=60,
        price=Decimal("300.00"),
    )
    db_session.add(svc)
    await db_session.flush()

    # 2026-09-04 is a Friday (day_of_week = 5)
    # Register customer with Friday EVENING preference
    cust = Customer(
        business_id=biz.id,
        full_name="לקוח ערב",
        phone_number=f"+97252{uid}88",
    )
    db_session.add(cust)
    await db_session.flush()

    pref = CustomerPreference(
        customer_id=cust.id,
        day_of_week=5,  # Friday
        time_slot="EVENING",
        service_id=svc.id,
    )
    db_session.add(pref)
    await db_session.commit()

    # Exact 16:00 test payload
    payload_16_00 = {
        "service_id": svc.id,
        "start_time": "2026-09-04T16:00:00",
    }

    res = await client.post(
        f"/api/v1/business/{biz.slug}/preview-candidates",
        json=payload_16_00,
    )

    assert res.status_code == 200, f"Expected 200 OK, got {res.status_code}: {res.text}"
    data = res.json()

    assert data["matched_count"] == 1
    assert data["day_name"] == "שישי"
    assert "ערב" in data["time_slot_label"]
    assert len(data["time_slot_label"]) > 0


@pytest.mark.asyncio
async def test_preview_candidates_all_boundaries(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Test preview endpoint with various boundary times:
    08:00 (MORNING), 12:00 (AFTERNOON), 16:00 (EVENING), 22:00 (EVENING), 23:30 (Off-peak fallback).
    Verifies that all return 200 OK and valid string labels.
    """
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת גבולות מרובים",
        phone_number=f"+97250{uid}71",
        business_type="clinic",
        slug=f"multi-boundary-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.commit()

    test_times = [
        ("2026-09-06T08:00:00", "בוקר"),
        ("2026-09-06T11:59:00", "בוקר"),
        ("2026-09-06T12:00:00", "צהריים"),
        ("2026-09-06T15:59:00", "צהריים"),
        ("2026-09-06T16:00:00", "ערב"),
        ("2026-09-06T21:59:00", "ערב"),
        ("2026-09-06T22:00:00", "ערב"),
        ("2026-09-06T23:30:00", "ערב"),
    ]

    for time_str, expected_label_part in test_times:
        res = await client.post(
            f"/api/v1/business/{biz.slug}/preview-candidates",
            json={"start_time": time_str},
        )
        assert res.status_code == 200, f"Failed for start_time={time_str}: {res.text}"
        data = res.json()
        assert data["matched_count"] >= 0
        assert isinstance(data["time_slot_label"], str)
        assert expected_label_part in data["time_slot_label"], f"Expected '{expected_label_part}' in '{data['time_slot_label']}' for {time_str}"
