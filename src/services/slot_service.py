from dataclasses import dataclass
from typing import Optional
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_redis_client
from src.models.customer import Customer
from src.models.slot import Slot, SlotStatus
from src.schemas.slot import SlotCreateRequest


@dataclass
class ClaimResult:
    """Result of an atomic slot claim operation."""
    success: bool
    message: str
    slot: Optional[Slot] = None
    status_code: int = 200


async def create_slot(db: AsyncSession, slot_in: SlotCreateRequest) -> Slot:
    """Create a new available appointment slot."""
    slot = Slot(
        business_id=slot_in.business_id,
        service_id=slot_in.service_id,
        custom_service_name=slot_in.custom_service_name,
        custom_price=slot_in.custom_price,
        start_time=slot_in.start_time,
        end_time=slot_in.end_time,
        status=SlotStatus.OPEN,
        version=1,
    )
    db.add(slot)
    await db.commit()
    await db.refresh(slot)
    return slot


async def get_slot_by_id(db: AsyncSession, slot_id: int) -> Optional[Slot]:
    """Retrieve slot by its primary key ID."""
    stmt = select(Slot).where(Slot.id == slot_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def claim_slot_atomic(
    db: AsyncSession,
    slot_id: int,
    customer_id: int,
) -> ClaimResult:
    """
    Atomically claims an OPEN appointment slot for a specific customer.
    Guarantees strict zero-overbooking using:
    1. Redis distributed lock (TTL 3s) for burst throttle and serialization.
    2. Atomic conditional SQL UPDATE ... WHERE id = :slot_id AND status = 'OPEN'
       RETURNING ... at the database row level.
    """
    # 1. Verify customer exists
    customer_stmt = select(Customer).where(Customer.id == customer_id)
    cust_res = await db.execute(customer_stmt)
    if not cust_res.scalar_one_or_none():
        return ClaimResult(
            success=False,
            message=f"Customer with ID {customer_id} does not exist.",
            status_code=404,
        )

    # 2. Redis Distributed Lock Layer (Defense-in-depth)
    lock_key = f"lock:slot:{slot_id}"
    lock_acquired = False
    lock = None

    try:
        redis = get_redis_client()
        lock = redis.lock(
            lock_key,
            timeout=3.0,
            blocking=True,
            blocking_timeout=2.0,
        )
        lock_acquired = await lock.acquire()
    except Exception:
        # Fall back directly to ACID database conditional update if Redis encounters any issue
        lock_acquired = False

    try:
        # 3. Database Atomic Conditional UPDATE Query
        claim_stmt = text("""
            UPDATE slots 
            SET status = 'CLAIMED', 
                claimed_by_customer_id = :customer_id, 
                version = version + 1
            WHERE id = :slot_id AND status = 'OPEN'
            RETURNING id, business_id, service_id, start_time, end_time, status, claimed_by_customer_id, version, created_at;
        """)

        result = await db.execute(
            claim_stmt,
            {"slot_id": slot_id, "customer_id": customer_id},
        )
        row = result.mappings().fetchone()

        if row is not None:
            # Atomic claim succeeded
            await db.commit()

            # Retrieve updated model instance
            slot_stmt = select(Slot).where(Slot.id == slot_id)
            slot_res = await db.execute(slot_stmt)
            updated_slot = slot_res.scalar_one()

            return ClaimResult(
                success=True,
                message="Slot successfully booked!",
                slot=updated_slot,
                status_code=200,
            )

        # If no row was returned (rows affected = 0), inspect slot status
        check_stmt = select(Slot).where(Slot.id == slot_id)
        check_res = await db.execute(check_stmt)
        existing_slot = check_res.scalar_one_or_none()

        if existing_slot is None:
            return ClaimResult(
                success=False,
                message="Slot not found.",
                slot=None,
                status_code=404,
            )

        return ClaimResult(
            success=False,
            message="Slot already taken or no longer available.",
            slot=existing_slot,
            status_code=409,
        )

    finally:
        # Release Redis lock safely
        if lock_acquired and lock:
            try:
                await lock.release()
            except Exception:
                pass


async def cancel_slot_by_owner(
    db: AsyncSession,
    slot_id: int,
    business_id: int,
) -> Slot:
    """
    Cancel an active slot on behalf of the business owner.
    - Ensures slot belongs to the business.
    - Ensures slot is not already CLAIMED.
    - Transitions status to CANCELLED.
    """
    from fastapi import HTTPException, status as http_status

    slot = await get_slot_by_id(db=db, slot_id=slot_id)
    if not slot or slot.business_id != business_id:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Slot not found",
        )

    if slot.status == SlotStatus.CLAIMED:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="לא ניתן לבטל תור שכבר נתפס",
        )

    slot.status = SlotStatus.CANCELLED
    await db.commit()
    await db.refresh(slot)
    return slot

