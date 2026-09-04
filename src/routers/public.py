import os
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_business_access_token
from src.database.connection import get_db
from src.schemas.business import (
    BusinessRegisterRequest,
    BusinessRegisterResponse,
    PublicBusinessProfileResponse,
    PublicServiceResponse,
)
from src.schemas.customer import CustomerOptInRequest, CustomerOptInResponse
from src.services.business_service import get_business_by_slug, register_new_business
from src.services.customer_service import (
    CustomerServiceError,
    register_customer_optin,
)

router = APIRouter(tags=["Public Opt-in"])

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
OPTIN_HTML_PATH = os.path.join(STATIC_DIR, "optin.html")


@router.get(
    "/api/v1/public/b/{slug}",
    response_model=PublicBusinessProfileResponse,
    summary="Get public business profile and service list",
    description="Returns public details for the opt-in registration page by slug.",
)
async def get_public_business_profile(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> PublicBusinessProfileResponse:
    """Fetch public business details and active services."""
    business = await get_business_by_slug(db=db, slug=slug)
    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business '{slug}' not found or inactive",
        )

    services_dto = [
        PublicServiceResponse(
            id=s.id,
            name=s.name,
            duration_minutes=s.duration_minutes,
            price=s.price,
        )
        for s in business.services
    ]

    return PublicBusinessProfileResponse(
        id=business.id,
        name=business.name,
        slug=business.slug,
        business_type=business.business_type,
        phone_number=business.phone_number,
        services=services_dto,
    )


@router.post(
    "/api/v1/public/b/{slug}/register",
    response_model=CustomerOptInResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register customer to waitlist",
    description="Registers customer preferences, handles idempotency, and dispatches automated welcome WhatsApp.",
)
async def register_public_customer(
    slug: str,
    optin_req: CustomerOptInRequest,
    db: AsyncSession = Depends(get_db),
) -> CustomerOptInResponse:
    """Process customer waitlist opt-in."""
    try:
        response = await register_customer_optin(
            db=db,
            slug=slug,
            data=optin_req,
        )
        return response
    except CustomerServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        )


@router.post(
    "/api/v1/public/register-business",
    response_model=BusinessRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Self-serve business registration",
    description="Registers a new business and its catalog services, returning an instant 30-day JWT token.",
)
async def register_business_endpoint(
    data: BusinessRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> BusinessRegisterResponse:
    """Self-serve business onboarding endpoint."""
    business = await register_new_business(db=db, data=data)
    token = create_business_access_token(business_id=business.id, slug=business.slug)
    dashboard_url = f"/dashboard/{business.slug}?token={token}"

    return BusinessRegisterResponse(
        success=True,
        business_id=business.id,
        name=business.name,
        slug=business.slug,
        access_token=token,
        token_type="bearer",
        dashboard_url=dashboard_url,
    )


@router.get(
    "/b/{slug}",
    summary="Serve Customer Opt-in Registration Page",
    description="Renders the mobile-first Hebrew PWA registration page for a business.",
    response_class=FileResponse,
)
async def serve_optin_page(slug: str):
    """Serve the opt-in HTML landing page."""
    if not os.path.exists(OPTIN_HTML_PATH):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Landing page template not found",
        )
    return FileResponse(OPTIN_HTML_PATH, media_type="text/html")

