import os
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_db
from src.schemas.auth import (
    BusinessLoginRequest,
    BusinessLoginRequestResponse,
    BusinessLoginVerify,
    BusinessLoginVerifyResponse,
    PinRequestResponse,
    PinVerifyRequest,
    TokenResponse,
)
from src.services.auth_service import (
    request_business_login_otp,
    request_business_pin,
    verify_business_login_otp,
    verify_business_pin,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
LOGIN_HTML_PATH = os.path.join(STATIC_DIR, "login.html")


@router.post(
    "/{slug}/request-pin",
    response_model=PinRequestResponse,
    summary="Request a 4-digit login PIN via WhatsApp",
    description="Sends a one-time 4-digit PIN to the business owner's registered WhatsApp phone number.",
)
async def request_pin(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> PinRequestResponse:
    """Trigger dispatch of 4-digit PIN via WhatsApp."""
    return await request_business_pin(db=db, slug=slug)


@router.post(
    "/business-login-request",
    response_model=BusinessLoginRequestResponse,
    summary="Request WhatsApp login OTP for business owner",
    description="Look up business by phone number, generate 6-digit OTP, and dispatch via WhatsApp.",
)
async def business_login_request(
    body: BusinessLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> BusinessLoginRequestResponse:
    """Request login OTP for business owner by mobile phone number."""
    return await request_business_login_otp(db=db, phone_number=body.phone_number)


@router.post(
    "/business-login-verify",
    response_model=BusinessLoginVerifyResponse,
    summary="Verify WhatsApp login OTP and issue JWT access token",
    description="Validates the 6-digit OTP and returns a 30-day JWT access token.",
)
async def business_login_verify(
    body: BusinessLoginVerify,
    db: AsyncSession = Depends(get_db),
) -> BusinessLoginVerifyResponse:
    """Verify login OTP and issue JWT access token."""
    return await verify_business_login_otp(db=db, phone_number=body.phone_number, code=body.code)


@router.post(
    "/{slug}/verify-pin",
    response_model=TokenResponse,
    summary="Verify PIN and get access token",
    description="Validates the 4-digit PIN and returns a 30-day JWT access token.",
)
async def verify_pin(
    slug: str,
    body: PinVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Verify PIN code and issue JWT."""
    return await verify_business_pin(db=db, slug=slug, pin=body.pin)



@router.get(
    "/login/{slug}",
    summary="Serve Business Owner Login Page",
    description="Renders the mobile-first PIN login interface.",
    response_class=FileResponse,
    include_in_schema=False,
)
async def serve_login_page(slug: str):
    """Serve the login HTML page."""
    if not os.path.exists(LOGIN_HTML_PATH):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Login page template not found",
        )
    return FileResponse(LOGIN_HTML_PATH, media_type="text/html")
