from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_db
from src.schemas.broadcast import BroadcastResponse
from src.schemas.customer import CustomerResponse
from src.schemas.slot import (
    SlotClaimRequest,
    SlotClaimResponse,
    SlotCreateRequest,
    SlotResponse,
)
from src.services.broadcast_service import BroadcastError, prepare_and_queue_broadcast
from src.services.matching_service import find_matching_customers
from src.services.notification_service import notify_business_owner_on_claim
from src.services.slot_service import (
    claim_slot_atomic,
    create_slot,
    get_slot_by_id,
)

router = APIRouter(prefix="/slots", tags=["Slots"])


@router.post(
    "",
    response_model=SlotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an open appointment slot",
    description="Business owner creates a newly opened cancellation slot available for alerts.",
)
async def create_new_slot(
    slot_in: SlotCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> SlotResponse:
    """Create a new available slot."""
    slot = await create_slot(db=db, slot_in=slot_in)
    return SlotResponse.model_validate(slot)


@router.get(
    "/{slot_id}/candidates",
    response_model=List[CustomerResponse],
    summary="Preview matching waitlisted customers",
    description="Finds and previews customers whose preferences match this slot's time, day, and service.",
)
async def get_slot_candidates(
    slot_id: int,
    db: AsyncSession = Depends(get_db),
) -> List[CustomerResponse]:
    """Retrieve all waitlisted customers matching the slot criteria."""
    slot = await get_slot_by_id(db=db, slot_id=slot_id)
    if not slot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Slot not found",
        )

    candidates = await find_matching_customers(db=db, slot_id=slot_id)
    return [CustomerResponse.model_validate(c) for c in candidates]


@router.post(
    "/{slot_id}/claim",
    response_model=SlotClaimResponse,
    summary="Claim an open slot",
    description="Atomically claims a slot on a first-come, first-served basis with race condition immunity.",
)
async def claim_slot(
    slot_id: int,
    claim_req: SlotClaimRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Atomically claim an open slot."""
    result = await claim_slot_atomic(
        db=db,
        slot_id=slot_id,
        customer_id=claim_req.customer_id,
    )

    if result.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.message,
        )

    if not result.success:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "success": False,
                "message": result.message,
                "slot": None,
            },
        )

    # Alert business owner in real-time
    await notify_business_owner_on_claim(
        db=db,
        slot_id=slot_id,
        customer_id=claim_req.customer_id,
    )

    slot_dto = SlotResponse.model_validate(result.slot).model_dump(mode="json")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "message": result.message,
            "slot": slot_dto,
        },
    )


@router.post(
    "/{slot_id}/broadcast",
    response_model=BroadcastResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Broadcast open slot to waitlisted customers",
    description="Identifies matching waitlisted customers, applies spam rate limiting, and queues background WhatsApp alerts.",
)
async def broadcast_slot(
    slot_id: int,
    db: AsyncSession = Depends(get_db),
) -> BroadcastResponse:
    """Trigger WhatsApp alert broadcast to eligible waitlist candidates."""
    try:
        response = await prepare_and_queue_broadcast(db=db, slot_id=slot_id)
        return response
    except BroadcastError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        )
