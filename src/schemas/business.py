from decimal import Decimal
from typing import List
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PublicServiceResponse(BaseModel):
    """Public service details for waitlist opt-in form."""
    id: int
    name: str = Field(..., description="Name of the service (e.g., טיפול פנים)")
    duration_minutes: int = Field(..., description="Duration in minutes")
    price: Decimal = Field(..., description="Price in ILS")

    model_config = ConfigDict(from_attributes=True)


class PublicBusinessProfileResponse(BaseModel):
    """Public business profile for landing page."""
    id: int
    name: str = Field(..., description="Business name")
    slug: str = Field(..., description="Unique URL slug")
    business_type: str = Field(..., description="Business category")
    phone_number: str = Field(..., description="Public contact number")
    services: List[PublicServiceResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ServiceCreateItem(BaseModel):
    """Service item provided during business onboarding."""
    name: str = Field(..., min_length=1, max_length=100, description="Service name", examples=["טיפול פנים קלאסי"])
    duration_minutes: int = Field(default=60, ge=5, le=480, description="Duration in minutes", examples=[60])
    price: Decimal = Field(..., ge=0, description="Price in ILS", examples=[250.0])


class BusinessRegisterRequest(BaseModel):
    """Payload for self-serve business registration on the landing page."""
    name: str = Field(..., min_length=2, max_length=100, description="Business name", examples=["קליניקת שירן"])
    phone_number: str = Field(..., description="Owner contact Israeli mobile phone", examples=["050-1234567"])
    business_type: str = Field(default="clinic", description="Business category", examples=["clinic"])
    slug: str | None = Field(default=None, max_length=60, description="Custom URL slug (optional)", examples=["shiran-clinic"])
    services: List[ServiceCreateItem] = Field(
        ...,
        min_length=1,
        description="List of services (at least 1)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "קליניקת שירן לאסתטיקה",
                "phone_number": "050-1234567",
                "business_type": "clinic",
                "slug": "shiran-clinic",
                "services": [
                    {
                        "name": "טיפול פנים קלאסי",
                        "duration_minutes": 60,
                        "price": 250.0,
                    }
                ],
            }
        }
    )

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        from src.schemas.customer import normalize_israeli_phone
        return normalize_israeli_phone(v)



class BusinessRegisterResponse(BaseModel):
    """Response returned upon successful business registration."""
    success: bool = True
    business_id: int
    name: str
    slug: str
    access_token: str
    token_type: str = "bearer"
    dashboard_url: str

