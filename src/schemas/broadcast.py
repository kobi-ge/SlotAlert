from pydantic import BaseModel, Field


class BroadcastResponse(BaseModel):
    """Response returned upon triggering a broadcast for a slot."""
    status: str = Field("queued", description="Status of the broadcast dispatch operation")
    slot_id: int = Field(..., description="ID of the slot being broadcast")
    total_matched: int = Field(..., description="Total waitlisted customers matching preference criteria")
    eligible_recipients: int = Field(..., description="Number of recipients cleared by spam guard")
    skipped_spam_guard: int = Field(..., description="Number of recipients skipped due to daily spam limit")
