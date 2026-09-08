from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.customer import normalize_israeli_phone


class RecentSlotItem(BaseModel):
    """Detailed representation of a recently created slot for the dashboard feed."""
    id: int
    start_time: datetime
    end_time: datetime
    status: str
    service_name: str
    price: Decimal
    claimed_by_name: Optional[str] = None
    claimed_by_phone: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DashboardSummaryResponse(BaseModel):
    """Aggregated business dashboard metrics and recent slots."""
    business_id: int
    business_name: str
    slug: str
    active_waitlist_count: int
    recent_slots: List[RecentSlotItem] = Field(default_factory=list)
    public_optin_url: Optional[str] = Field(
        default=None,
        description="Authoritative public HTTPS customer waitlist opt-in URL",
    )


class SlotCandidatePreviewRequest(BaseModel):
    """Request payload to preview matching waitlist candidates before publishing."""
    service_id: Optional[int] = None
    start_time: datetime


class SlotCandidatePreviewResponse(BaseModel):
    """Response containing real-time candidate count and human-friendly time labels."""
    matched_count: int = Field(default=0, ge=0, description="Total matching candidates based on availability preferences")
    eligible_count: int = Field(default=0, ge=0, description="Candidates eligible to receive notification (not rate-limited)")
    skipped_spam_guard: int = Field(default=0, ge=0, description="Candidates blocked by 24h spam prevention limits")
    day_name: str = Field(default="יום חול", description="Readable Hebrew day name")
    time_slot_label: str = Field(default="שעות כלליות", description="Readable Hebrew time window")
    time_slot: Optional[str] = Field(default=None, description="Internal time slot category name")



class QuickPublishSlotRequest(BaseModel):
    """Request payload for the atomic slot creation and broadcast trigger."""
    service_id: Optional[int] = None
    custom_service_name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional custom service or treatment name override",
    )
    custom_price: Optional[Decimal] = Field(
        default=None,
        ge=0,
        description="Optional custom price override in ILS",
    )
    start_time: datetime
    duration_minutes: Optional[int] = Field(
        default=None,
        description="Optional duration override in minutes. Defaults to service duration.",
    )

    @model_validator(mode="after")
    def validate_service_or_custom(self):
        if self.service_id is None and not (self.custom_service_name and self.custom_service_name.strip()):
            raise ValueError("Either service_id or custom_service_name must be provided.")
        return self


class QuickPublishSlotResponse(BaseModel):
    """Response returned upon creating a slot and queueing its broadcast."""
    slot_id: int
    status: str
    start_time: datetime
    broadcast_status: str
    total_matched: int
    eligible_recipients: int
    skipped_spam_guard: int


class WaitlistCustomerItem(BaseModel):
    """Registered waitlist customer summary for the business management tab."""
    id: int
    full_name: str
    phone_number: str
    created_at: datetime
    preferences_summary: List[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


from src.schemas.customer import CustomerCreateRequest, normalize_israeli_phone


class ManualCustomerCreateRequest(CustomerCreateRequest):
    """Schema for business owner to manually register a walk-in / phone client."""
    pass

