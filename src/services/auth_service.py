import logging
import random
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_business_access_token
from src.database.connection import get_redis_client
from src.schemas.auth import PinRequestResponse, TokenResponse
from src.services.business_service import get_business_by_slug
from src.services.messaging.factory import get_configured_message_provider

logger = logging.getLogger("slotalert.auth_service")

PIN_TTL_SECONDS = 300  # 5 minutes


def mask_phone_number(phone: str) -> str:
    """Format phone number with middle digits masked for privacy display."""
    clean = phone.replace(" ", "").replace("-", "")
    if len(clean) >= 9:
        prefix = clean[:4]
        suffix = clean[-4:]
        return f"{prefix}-***-{suffix}"
    return "****"


async def request_business_pin(
    db: AsyncSession,
    slug: str,
) -> PinRequestResponse:
    """
    Generate a one-time 4-digit PIN, cache it in Redis with 5-minute expiry,
    and dispatch it via WhatsApp to the business owner.
    """
    business = await get_business_by_slug(db, slug)
    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business '{slug}' not found or inactive",
        )

    # 1. Generate 4-digit PIN
    pin = str(random.randint(1000, 9999))

    # 2. Cache in Redis
    redis = get_redis_client()
    redis_key = f"auth:pin:{business.id}"
    await redis.set(redis_key, pin, ex=PIN_TTL_SECONDS)
    logger.info(f"Generated 4-digit PIN for business {business.name} (ID {business.id})")

    # 3. Dispatch via WhatsApp
    try:
        provider = get_configured_message_provider()
        pin_message = (
            f"קוד הכניסה שלך לדשבורד של {business.name}: {pin}\n\n"
            f"הקוד בתוקף ל-5 דקות הקרובות. אין לשתף קוד זה."
        )
        await provider.send_text_message(business.phone_number, pin_message)
        logger.info(f"WhatsApp PIN message sent to {business.phone_number}")
    except Exception as exc:
        logger.error(f"Failed to dispatch PIN WhatsApp: {exc}")

    return PinRequestResponse(
        success=True,
        message="קוד כניסה נשלח לוואטסאפ של בעלת העסק",
        phone_masked=mask_phone_number(business.phone_number),
    )


async def verify_business_pin(
    db: AsyncSession,
    slug: str,
    pin: str,
) -> TokenResponse:
    """
    Verify the 4-digit PIN against Redis. If valid, issue a 30-day JWT access token.
    """
    business = await get_business_by_slug(db, slug)
    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business '{slug}' not found or inactive",
        )

    redis = get_redis_client()
    redis_key = f"auth:pin:{business.id}"
    cached_pin = await redis.get(redis_key)

    if not cached_pin or cached_pin != pin.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="קוד PIN שגוי או שפג תוקפו",
        )

    # Delete used PIN
    await redis.delete(redis_key)

    # Issue 30-day token
    token = create_business_access_token(business_id=business.id, slug=business.slug)
    logger.info(f"Business '{business.slug}' successfully authenticated via PIN.")

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in_days=30,
    )


async def request_business_login_otp(
    db: AsyncSession,
    phone_number: str,
) -> "BusinessLoginRequestResponse":
    """
    Lookup business by normalized mobile phone, generate a 6-digit OTP in Redis (5 min TTL),
    and dispatch the code via WhatsApp.
    """
    from sqlalchemy import select
    from src.models.business import Business
    from src.schemas.auth import BusinessLoginRequestResponse
    from src.schemas.customer import normalize_israeli_phone

    normalized_phone = normalize_israeli_phone(phone_number)

    stmt = select(Business).where(
        Business.phone_number == normalized_phone,
        Business.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    business = result.scalar_one_or_none()

    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="לא קיים עסק פעיל עם מספר טלפון זה",
        )

    # 1. Generate 6-digit OTP
    otp = f"{random.randint(100000, 999999)}"

    # 2. Cache in Redis (5 min TTL)
    redis = get_redis_client()
    redis_key = f"otp:login:{business.id}"
    await redis.set(redis_key, otp, ex=PIN_TTL_SECONDS)
    logger.info(f"Generated 6-digit login OTP for business '{business.name}' (ID {business.id})")

    # 3. Dispatch via WhatsApp
    try:
        provider = get_configured_message_provider()
        otp_message = f"קוד ההתחברות שלך למערכת SlotAlert הוא: {otp} (תקף ל-5 דקות)"
        await provider.send_text_message(business.phone_number, otp_message)
        logger.info(f"WhatsApp login OTP sent to {business.phone_number}")
    except Exception as exc:
        logger.error(f"Failed to dispatch login OTP WhatsApp: {exc}")

    return BusinessLoginRequestResponse(
        success=True,
        message="OTP sent successfully",
        business_name=business.name,
        slug=business.slug,
    )


async def verify_business_login_otp(
    db: AsyncSession,
    phone_number: str,
    code: str,
) -> "BusinessLoginVerifyResponse":
    """
    Verify 6-digit OTP for business owner phone and return a 30-day JWT access token.
    """
    from sqlalchemy import select
    from src.models.business import Business
    from src.schemas.auth import BusinessLoginVerifyResponse
    from src.schemas.customer import normalize_israeli_phone

    normalized_phone = normalize_israeli_phone(phone_number)

    stmt = select(Business).where(
        Business.phone_number == normalized_phone,
        Business.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    business = result.scalar_one_or_none()

    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="לא קיים עסק פעיל עם מספר טלפון זה",
        )

    redis = get_redis_client()
    redis_key = f"otp:login:{business.id}"
    cached_otp = await redis.get(redis_key)

    if not cached_otp or cached_otp.strip() != code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="קוד אימות שגוי או שפג תוקפו",
        )

    # Delete used OTP
    await redis.delete(redis_key)

    # Issue 30-day JWT token
    token = create_business_access_token(business_id=business.id, slug=business.slug)
    logger.info(f"Business '{business.slug}' authenticated successfully via login OTP.")

    return BusinessLoginVerifyResponse(
        success=True,
        access_token=token,
        token_type="bearer",
        slug=business.slug,
        dashboard_url=f"/dashboard/{business.slug}",
    )

