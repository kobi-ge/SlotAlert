import os
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_current_business
from src.database.connection import get_db
from src.models.business import Business
from src.schemas.customer import (
    CustomerCreateRequest,
    CustomerOptInRequest,
    CustomerOptInResponse,
)
from src.schemas.dashboard import (
    DashboardSummaryResponse,
    ManualCustomerCreateRequest,
    QuickPublishSlotRequest,
    QuickPublishSlotResponse,
    SlotCandidatePreviewRequest,
    SlotCandidatePreviewResponse,
    WaitlistCustomerItem,
)
from src.schemas.slot import SlotResponse
from src.services.business_service import get_business_by_slug
from src.services.customer_service import (
    create_manual_customer_with_preferences,
    register_customer_optin,
)
from src.services.dashboard_service import (
    get_dashboard_summary,
    list_waitlist_customers,
    preview_candidates_for_slot,
    quick_publish_and_broadcast_slot,
)
from src.services.slot_service import cancel_slot_by_owner

router = APIRouter(tags=["Business Management"])


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
DASHBOARD_HTML_PATH = os.path.join(STATIC_DIR, "dashboard.html")


@router.get(
    "/api/v1/business/{slug}/dashboard",
    response_model=DashboardSummaryResponse,
    summary="Get business dashboard summary",
    description="Fetches aggregated business waitlist stats and recent slots activity.",
)
async def get_business_dashboard(
    slug: str,
    business: Business = Depends(get_current_business),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    """Return dashboard metrics and recent slots feed."""
    return await get_dashboard_summary(db=db, business=business)


@router.post(
    "/api/v1/business/{slug}/preview-candidates",
    response_model=SlotCandidatePreviewResponse,
    summary="Live candidate count preview",
    description="Calculates matched waitlist recipients before creating a slot.",
)
async def preview_candidates(
    slug: str,
    request_data: SlotCandidatePreviewRequest,
    db: AsyncSession = Depends(get_db),
) -> SlotCandidatePreviewResponse:
    """Preview count of eligible waitlist recipients for a given slot start time and service."""
    business = await get_business_by_slug(db=db, slug=slug)
    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business '{slug}' not found or inactive",
        )
    return await preview_candidates_for_slot(
        db=db,
        business_id=business.id,
        service_id=request_data.service_id,
        start_time=request_data.start_time,
    )


@router.post(
    "/api/v1/business/{slug}/quick-publish",
    response_model=QuickPublishSlotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Quick-publish slot & trigger broadcast",
    description="Creates an open slot and immediately dispatches WhatsApp alerts to matching candidates.",
)
async def quick_publish_slot(
    slug: str,
    publish_req: QuickPublishSlotRequest,
    business: Business = Depends(get_current_business),
    db: AsyncSession = Depends(get_db),
) -> QuickPublishSlotResponse:
    """Atomic slot publication and queue broadcast."""
    try:
        response = await quick_publish_and_broadcast_slot(
            db=db,
            business=business,
            service_id=publish_req.service_id,
            start_time=publish_req.start_time,
            duration_minutes=publish_req.duration_minutes,
            custom_service_name=publish_req.custom_service_name,
            custom_price=publish_req.custom_price,
        )
        return response
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/api/v1/business/{slug}/waitlist",
    response_model=List[WaitlistCustomerItem],
    summary="List registered waitlist customers",
    description="Returns all active customers registered for this business.",
)
async def get_waitlist_customers(
    slug: str,
    business: Business = Depends(get_current_business),
    db: AsyncSession = Depends(get_db),
) -> List[WaitlistCustomerItem]:
    """Retrieve full waitlist contact list for the business."""
    return await list_waitlist_customers(db=db, business_id=business.id)


@router.post(
    "/api/v1/business/{slug}/customers",
    response_model=CustomerOptInResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Manually add customer with preferences (customers route)",
    description="Allows business owner to manually register a client with full preference granularity.",
)
@router.post(
    "/api/v1/business/{slug}/waitlist",
    response_model=CustomerOptInResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Manually add customer to waitlist",
    description="Allows business owner to manually register a walk-in or calling customer.",
)
async def add_waitlist_customer_manual(
    slug: str,
    manual_req: CustomerCreateRequest,
    business: Business = Depends(get_current_business),
    db: AsyncSession = Depends(get_db),
) -> CustomerOptInResponse:
    """Register customer manually from the business dashboard with full preference parity."""
    return await create_manual_customer_with_preferences(
        db=db,
        business=business,
        data=manual_req,
    )


@router.delete(
    "/api/v1/business/{slug}/slots/{slot_id}",
    response_model=SlotResponse,
    summary="Cancel open slot by owner",
    description="Revokes an active appointment slot, preventing any client claims.",
)
@router.post(
    "/api/v1/business/{slug}/slots/{slot_id}/cancel",
    response_model=SlotResponse,
    summary="Cancel open slot by owner (POST alias)",
    description="Revokes an active appointment slot, preventing any client claims.",
)
async def cancel_business_slot(
    slug: str,
    slot_id: int,
    business: Business = Depends(get_current_business),
    db: AsyncSession = Depends(get_db),
) -> SlotResponse:
    """Revoke/cancel an active slot by business owner."""
    slot = await cancel_slot_by_owner(db=db, slot_id=slot_id, business_id=business.id)
    return SlotResponse.model_validate(slot)



@router.get(
    "/dashboard/{slug}",
    summary="Serve Business Mobile Dashboard",
    description="Renders the mobile-first Hebrew PWA dashboard for the business owner.",
    response_class=FileResponse,
)
async def serve_business_dashboard(slug: str):
    """Serve the business owner dashboard HTML page."""
    if not os.path.exists(DASHBOARD_HTML_PATH):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard page template not found",
        )
    return FileResponse(DASHBOARD_HTML_PATH, media_type="text/html")
