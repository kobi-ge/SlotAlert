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


@pytest.mark.asyncio
async def test_preview_and_quick_publish_candidate_parity(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Verify 100% parity between /preview-candidates and /quick-publish:
    Both must find the exact same number of matched and eligible candidates.
    """
    from src.core.security import create_business_access_token

    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת בדיקת התאמה מלאה",
        phone_number=f"+97250{uid}72",
        business_type="clinic",
        slug=f"parity-test-{uid}",
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

    # Add 1 matching customer for Monday morning
    # 2026-09-07 is Monday (day_of_week = 1)
    cust = Customer(
        business_id=biz.id,
        full_name="לקוח פריטי",
        phone_number=f"+97250{uid}99",
    )
    db_session.add(cust)
    await db_session.flush()

    pref = CustomerPreference(
        customer_id=cust.id,
        day_of_week=1,  # Monday
        time_slot="MORNING",
        service_id=svc.id,
    )
    db_session.add(pref)
    await db_session.commit()

    start_time = "2026-09-07T09:00:00"

    # 1. Preview candidates
    prev_res = await client.post(
        f"/api/v1/business/{biz.slug}/preview-candidates",
        json={"service_id": svc.id, "start_time": start_time},
    )
    assert prev_res.status_code == 200
    prev_data = prev_res.json()
    assert prev_data["matched_count"] == 1
    assert prev_data["eligible_count"] == 1
    assert prev_data["skipped_spam_guard"] == 0

    # 2. Quick publish
    token = create_business_access_token(biz.id, biz.slug)
    pub_res = await client.post(
        f"/api/v1/business/{biz.slug}/quick-publish",
        json={"service_id": svc.id, "start_time": start_time},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pub_res.status_code == 201
    pub_data = pub_res.json()
    assert pub_data["total_matched"] == 1
    assert pub_data["eligible_recipients"] == 1
    assert pub_data["skipped_spam_guard"] == 0


@pytest.mark.asyncio
async def test_candidate_preview_resyncs_stale_redis_cache(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Test scenario:
    When Redis has a stale counter (e.g. 2 alerts) from past sends, but broadcast_logs
    were deleted in PostgreSQL, SpamGuard and candidate preview must:
    1. Query PostgreSQL as the ultimate authority.
    2. Detect 0 sent logs in DB and resync Redis key.
    3. Allow candidate through (eligible_count=1, skipped_spam_guard=0).
    """
    from src.database.connection import get_redis_client

    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת רדיס ריסינק",
        phone_number=f"+97250{uid}73",
        business_type="clinic",
        slug=f"redis-resync-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.flush()

    cust = Customer(
        business_id=biz.id,
        full_name="לקוח רדיס",
        phone_number=f"+97250{uid}77",
    )
    db_session.add(cust)
    await db_session.flush()

    # 2026-09-08 is Tuesday (day_of_week = 2)
    pref = CustomerPreference(
        customer_id=cust.id,
        day_of_week=2,
        time_slot="MORNING",
        service_id=None,
    )
    db_session.add(pref)
    await db_session.commit()

    # Seed Redis with stale counter = 2
    redis = get_redis_client()
    now_utc = datetime.now(timezone.utc)
    date_str = now_utc.strftime("%Y-%m-%d")
    redis_key = f"alerts:customer:{cust.id}:{date_str}"
    await redis.set(redis_key, 2, ex=3600)

    # Verify Redis is indeed 2 before preview
    cached_val = await redis.get(redis_key)
    assert cached_val == "2"

    # Call preview-candidates
    res = await client.post(
        f"/api/v1/business/{biz.slug}/preview-candidates",
        json={"start_time": "2026-09-08T10:00:00"},
    )
    assert res.status_code == 200
    data = res.json()

    # PostgreSQL has 0 broadcast_logs, so customer is eligible!
    assert data["matched_count"] == 1
    assert data["eligible_count"] == 1
    assert data["skipped_spam_guard"] == 0

    # Verify Redis counter was resynced to 0
    updated_val = await redis.get(redis_key)
    assert updated_val == "0"

