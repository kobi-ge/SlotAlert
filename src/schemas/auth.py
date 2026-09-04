from pydantic import BaseModel, Field, field_validator


class PinRequestResponse(BaseModel):
    """Response returned when a PIN code is requested for business login."""
    success: bool = True
    message: str = "קוד כניסה נשלח לוואטסאפ של בעלת העסק"
    phone_masked: str = Field(..., description="Masked WhatsApp phone number (e.g. 050-***-2233)")


class PinVerifyRequest(BaseModel):
    """Request payload to verify the 4-digit PIN."""
    pin: str = Field(..., min_length=4, max_length=6, description="One-time PIN code")


class TokenResponse(BaseModel):
    """JWT access token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in_days: int = 30


class BusinessLoginRequest(BaseModel):
    """Payload to request a WhatsApp login OTP for a business owner."""
    phone_number: str = Field(..., description="Owner Israeli mobile phone number", examples=["050-1234567"])

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        from src.schemas.customer import normalize_israeli_phone
        return normalize_israeli_phone(v)


class BusinessLoginRequestResponse(BaseModel):
    """Response after OTP is dispatched via WhatsApp."""
    success: bool = True
    message: str = "OTP sent successfully"
    business_name: str
    slug: str


class BusinessLoginVerify(BaseModel):
    """Payload to verify OTP and obtain JWT."""
    phone_number: str = Field(..., description="Owner Israeli mobile phone number", examples=["050-1234567"])
    code: str = Field(..., min_length=4, max_length=6, description="OTP code received via WhatsApp", examples=["123456"])

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        from src.schemas.customer import normalize_israeli_phone
        return normalize_israeli_phone(v)


class BusinessLoginVerifyResponse(BaseModel):
    """Response returned upon successful OTP verification."""
    success: bool = True
    access_token: str
    token_type: str = "bearer"
    slug: str
    dashboard_url: str

