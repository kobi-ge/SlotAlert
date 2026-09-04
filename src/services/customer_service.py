import logging
from typing import Optional
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.business import Business
from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.schemas.customer import (
    CustomerCreateRequest,
    CustomerOptInRequest,
    CustomerOptInResponse,
)
from src.services.business_service import get_business_by_slug
from src.services.messaging.factory import get_configured_message_provider

logger = logging.getLogger("slotalert.customer_service")


class CustomerServiceError(Exception):
    """Domain exception for customer service operations."""
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def register_customer_optin(
    db: AsyncSession,
    slug: str,
    data: CustomerOptInRequest,
) -> CustomerOptInResponse:
    """
    Register a customer into the waitlist for a specific business:
    - Resolves active business.
    - Upserts customer idempotently (updating full_name if existing).
    - Replaces previous customer preferences with the new matrix.
    - Dispatches an automated WhatsApp welcome message.
    """
    # 1. Resolve business
    business = await get_business_by_slug(db, slug)
    if not business:
        raise CustomerServiceError(f"Business '{slug}' not found or inactive", status_code=404)

    # 2. Check if customer already exists for this business
    cust_stmt = select(Customer).where(
        Customer.business_id == business.id,
        Customer.phone_number == data.phone_number,
    )
    cust_res = await db.execute(cust_stmt)
    customer = cust_res.scalar_one_or_none()

    if customer:
        # Update existing customer name
        customer.full_name = data.full_name
        logger.info(f"Updating existing customer ID {customer.id} for business {business.name}")
        # Clear existing preferences
        del_stmt = delete(CustomerPreference).where(CustomerPreference.customer_id == customer.id)
        await db.execute(del_stmt)
    else:
        # Create new customer
        customer = Customer(
            business_id=business.id,
            full_name=data.full_name,
            phone_number=data.phone_number,
        )
        db.add(customer)
        await db.flush()  # populate customer.id
        logger.info(f"Created new customer ID {customer.id} for business {business.name}")

    # 3. Insert preference matrix
    # If service_ids is empty, client accepts any service (service_id=None)
    services_to_insert = data.service_ids if data.service_ids else [None]

    new_prefs = []
    for day in data.days_of_week:
        for slot_time in data.time_slots:
            for s_id in services_to_insert:
                pref = CustomerPreference(
                    customer_id=customer.id,
                    day_of_week=day,
                    time_slot=slot_time,
                    service_id=s_id,
                )
                new_prefs.append(pref)

    db.add_all(new_prefs)
    await db.commit()
    await db.refresh(customer)

    # 4. Trigger automated welcome WhatsApp message
    try:
        provider = get_configured_message_provider()
        welcome_text = (
            f"היי {customer.full_name}, נרשמת לרשימת ההמתנה של {business.name} 🎉\n"
            "כשייתפנה תור מתאים להעדפותיך נעדכן אותך כאן מיד על בסיס כל הקודם זוכה!"
        )
        await provider.send_text_message(customer.phone_number, welcome_text)
        logger.info(f"Welcome WhatsApp sent to {customer.phone_number}")
    except Exception as exc:
        logger.warning(f"Failed to dispatch welcome WhatsApp: {exc}")

    return CustomerOptInResponse(
        success=True,
        customer_id=customer.id,
        id=customer.id,
        message=f"נרשמת בהצלחה לרשימת ההמתנה של {business.name}!",
    )


async def create_manual_customer_with_preferences(
    db: AsyncSession,
    business: Business,
    data: "CustomerCreateRequest",
) -> CustomerOptInResponse:
    """
    Manually register a customer with full preference parity from business owner dashboard.
    Populates Customer record and corresponding CustomerPreference rows in the same transaction.
    """
    optin_dto = CustomerOptInRequest(
        full_name=data.full_name,
        phone_number=data.phone_number,
        service_ids=data.service_ids or [],
        days_of_week=data.days_of_week or [0, 1, 2, 3, 4, 5],
        time_slots=data.time_slots or ["MORNING", "AFTERNOON", "EVENING"],
    )
    return await register_customer_optin(db=db, slug=business.slug, data=optin_dto)

