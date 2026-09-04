import re
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_israeli_phone(val: str) -> str:
    """
    Standardize Israeli mobile numbers to E.164 format (+9725XXXXXXXX).
    Accepts:
    - 050-1234567, 050 123 4567, 0501234567 -> +972501234567
    - 972501234567, +972501234567 -> +972501234567
    """
    if not val:
        raise ValueError("Phone number is required.")

    # Remove all formatting characters (spaces, dashes, parentheses)
    digits = re.sub(r"[^\d+]", "", val.strip())

    if digits.startswith("+"):
        digits = digits[1:]

    # Israeli international format: 9725XXXXXXXX (12 digits)
    if digits.startswith("972") and len(digits) == 12:
        normalized = f"+{digits}"
    # Local format with leading zero: 05XXXXXXXX (10 digits)
    elif digits.startswith("05") and len(digits) == 10:
        normalized = f"+972{digits[1:]}"
    # Local format without leading zero: 5XXXXXXXX (9 digits)
    elif digits.startswith("5") and len(digits) == 9:
        normalized = f"+972{digits}"
    else:
        raise ValueError(
            f"Invalid Israeli mobile phone number '{val}'. "
            "Must be a valid 10-digit mobile number (e.g. 050-1234567)."
        )

    # Validate that the mobile prefix is valid (050-059)
    if not re.match(r"^\+9725[0-9]\d{7}$", normalized):
        raise ValueError(f"Invalid Israeli mobile prefix in '{val}'.")

    return normalized


class CustomerBase(BaseModel):
    """Base schema for customer information."""
    full_name: str = Field(..., min_length=2, max_length=100, description="Full name of customer")
    phone_number: str = Field(..., description="WhatsApp/phone number")


class CustomerCreate(CustomerBase):
    """Schema for creating a customer under a business."""
    business_id: int

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return normalize_israeli_phone(v)


class CustomerResponse(CustomerBase):
    """Customer response DTO."""
    id: int
    business_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomerPreferenceResponse(BaseModel):
    """Customer preference response DTO."""
    id: int
    customer_id: int
    day_of_week: int
    time_slot: str
    service_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class CustomerOptInRequest(BaseModel):
    """Payload for customer waitlist registration on the public landing page."""
    full_name: str = Field(..., min_length=2, max_length=100, description="Full name")
    phone_number: str = Field(..., description="Israeli mobile phone number")
    service_ids: List[int] = Field(
        default_factory=list,
        description="Services requested. Empty or omitted indicates any service is acceptable.",
    )
    days_of_week: List[int] = Field(
        ...,
        min_length=1,
        description="List of preferred days of the week (0=Sunday ... 5=Friday, 6=Saturday)",
    )
    time_slots: List[str] = Field(
        ...,
        min_length=1,
        description="List of preferred time slots ('MORNING', 'AFTERNOON', 'EVENING')",
    )

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return normalize_israeli_phone(v)

    @field_validator("time_slots")
    @classmethod
    def validate_time_slots(cls, slots: List[str]) -> List[str]:
        valid = {"MORNING", "AFTERNOON", "EVENING"}
        for s in slots:
            if s.upper() not in valid:
                raise ValueError(f"Invalid time slot '{s}'. Must be one of {valid}")
        return [s.upper() for s in slots]

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, days: List[int]) -> List[int]:
        for d in days:
            if not (0 <= d <= 6):
                raise ValueError(f"Day of week {d} must be between 0 (Sunday) and 6 (Saturday).")
        return list(set(days))


class CustomerOptInResponse(BaseModel):
    """Confirmation response upon successful waitlist registration."""
    success: bool = True
    customer_id: int
    id: Optional[int] = None
    message: str = "נרשמת בהצלחה לרשימת ההמתנה!"

    model_config = ConfigDict(from_attributes=True)

    def model_post_init(self, __context) -> None:
        if self.id is None:
            self.id = self.customer_id


class CustomerCreateRequest(BaseModel):
    """Payload for manual customer creation by business owner with full preference parity."""
    full_name: str = Field(..., min_length=2, max_length=100, description="Full name")
    phone_number: str = Field(..., description="Israeli mobile phone number")
    service_ids: Optional[List[int]] = Field(
        default_factory=list,
        description="Services requested. Empty or omitted indicates any service is acceptable.",
    )
    days_of_week: Optional[List[int]] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4, 5],
        description="List of preferred days of the week (0=Sunday ... 5=Friday, 6=Saturday)",
    )
    time_slots: Optional[List[str]] = Field(
        default_factory=lambda: ["MORNING", "AFTERNOON", "EVENING"],
        description="List of preferred time slots ('MORNING', 'AFTERNOON', 'EVENING')",
    )

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return normalize_israeli_phone(v)

    @field_validator("time_slots")
    @classmethod
    def validate_time_slots(cls, slots: Optional[List[str]]) -> List[str]:
        if slots is None or len(slots) == 0:
            return ["MORNING", "AFTERNOON", "EVENING"]
        valid = {"MORNING", "AFTERNOON", "EVENING"}
        for s in slots:
            if s.upper() not in valid:
                raise ValueError(f"Invalid time slot '{s}'. Must be one of {valid}")
        return [s.upper() for s in slots]

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, days: Optional[List[int]]) -> List[int]:
        if days is None or len(days) == 0:
            return [0, 1, 2, 3, 4, 5]
        for d in days:
            if not (0 <= d <= 6):
                raise ValueError(f"Day of week {d} must be between 0 (Sunday) and 6 (Saturday).")
        return list(set(days))

