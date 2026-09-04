import asyncio
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from tests.conftest import TestSessionLocal
from src.models.business import Business
from src.models.customer import Customer
from src.models.service import Service
from src.models.slot import Slot, SlotStatus


@pytest.mark.asyncio
async def test_slot_concurrency_race_condition(
    client: httpx.AsyncClient,
    test_business: Business,
    test_service: Service,
):
    """
    Stress test verifying zero overbooking under high concurrent load:
    - 1 open slot is targeted by 20 distinct customers simultaneously.
    - All 20 requests fire concurrently via asyncio.gather().
    - Exactly 1 request must succeed with 200 OK (success: True).
    - Exactly 19 requests must fail with 409 Conflict (success: False).
    - Database slot state must be CLAIMED with version = 2 and assigned to the winner.
    """
    # 1. Setup: Create 1 open slot and 20 distinct customers
    async with TestSessionLocal() as setup_session:
        slot = Slot(
            business_id=test_business.id,
            service_id=test_service.id,
            start_time=datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 15, 11, 0, tzinfo=timezone.utc),
            status=SlotStatus.OPEN,
            version=1,
        )
        setup_session.add(slot)
        await setup_session.flush()

        customer_ids = []
        for i in range(1, 21):
            phone = f"+97255999{i:04d}"
            # Check if customer already exists from previous runs
            existing_cust_stmt = select(Customer).where(
                Customer.business_id == test_business.id,
                Customer.phone_number == phone,
            )
            existing_cust = (await setup_session.execute(existing_cust_stmt)).scalar_one_or_none()
            if not existing_cust:
                cust = Customer(
                    business_id=test_business.id,
                    full_name=f"מתחרה #{i}",
                    phone_number=phone,
                )
                setup_session.add(cust)
                await setup_session.flush()
                customer_ids.append(cust.id)
            else:
                customer_ids.append(existing_cust.id)

        await setup_session.commit()
        target_slot_id = slot.id

    assert len(customer_ids) == 20

    # 2. Fire 20 concurrent claim requests simultaneously
    async def make_claim(customer_id: int):
        return await client.post(
            f"/api/v1/slots/{target_slot_id}/claim",
            json={"customer_id": customer_id},
        )

    tasks = [make_claim(cid) for cid in customer_ids]
    responses = await asyncio.gather(*tasks)

    # 3. Analyze results
    success_responses = [r for r in responses if r.status_code == 200]
    conflict_responses = [r for r in responses if r.status_code == 409]

    print(f"\n[CONCURRENCY TEST RESULTS]")
    print(f"Total Concurrent Requests: {len(responses)}")
    print(f"200 OK Success Count: {len(success_responses)}")
    print(f"409 Conflict Missed Count: {len(conflict_responses)}")

    # Assertions
    assert len(success_responses) == 1, (
        f"Expected exactly 1 success, but got {len(success_responses)}"
    )
    assert len(conflict_responses) == 19, (
        f"Expected exactly 19 conflicts, but got {len(conflict_responses)}"
    )

    winner_payload = success_responses[0].json()
    assert winner_payload["success"] is True
    assert winner_payload["message"] == "Slot successfully booked!"
    winner_slot_data = winner_payload["slot"]
    winner_customer_id = winner_slot_data["claimed_by_customer_id"]

    for r in conflict_responses:
        fail_payload = r.json()
        assert fail_payload["success"] is False
        assert "already taken" in fail_payload["message"]

    # 4. Verify Database State
    async with TestSessionLocal() as verify_session:
        db_slot_stmt = select(Slot).where(Slot.id == target_slot_id)
        db_slot_res = await verify_session.execute(db_slot_stmt)
        db_slot = db_slot_res.scalar_one()

        assert db_slot.status == SlotStatus.CLAIMED
        assert db_slot.version == 2
        assert db_slot.claimed_by_customer_id == winner_customer_id
        print(f"Winner Customer ID: {winner_customer_id}")
        print(f"Database Slot Status: {db_slot.status.value}, Version: {db_slot.version}")
