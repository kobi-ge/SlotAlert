from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from src.models.slot import SlotStatus


class SlotCreateRequest(BaseModel):
    """Payload to create a newly available appointment slot."""
    business_id: int = Field(..., description="ID of the business offering the slot")
    service_id: Optional[int] = Field(default=None, description="ID of the catalog service (if any)")
    custom_service_name: Optional[str] = Field(default=None, max_length=100, description="Custom ad-hoc service name")
    custom_price: Optional[Decimal] = Field(default=None, ge=0, description="Custom ad-hoc price")
    start_time: datetime = Field(..., description="Start timestamp of the appointment")
    end_time: datetime = Field(..., description="End timestamp of the appointment")


class SlotResponse(BaseModel):
    """Detailed slot representation."""
    id: int
    business_id: int
    service_id: Optional[int] = None
    custom_service_name: Optional[str] = None
    custom_price: Optional[Decimal] = None
    start_time: datetime
    end_time: datetime
    status: SlotStatus
    claimed_by_customer_id: Optional[int] = None
    version: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SlotClaimRequest(BaseModel):
    """Payload to claim an open slot on first-come, first-served basis."""
    customer_id: int = Field(..., description="ID of the customer claiming this slot")


class SlotClaimResponse(BaseModel):
    """Response returned upon attempting to claim a slot."""
    success: bool
    message: str
    slot: Optional[SlotResponse] = None
