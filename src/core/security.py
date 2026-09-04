from datetime import datetime, timedelta, timezone
import logging
from typing import Optional
import jwt
from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.database.connection import get_db
from src.models.business import Business
from src.services.business_service import get_business_by_slug

logger = logging.getLogger("slotalert.security")
settings = get_settings()


def create_business_access_token(business_id: int, slug: str) -> str:
    """Generate a signed JWT token valid for 30 days for a business."""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(business_id),
        "business_id": business_id,
        "slug": slug,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_business_access_token(token_str: str) -> Optional[dict]:
    """Decode and validate a signed JWT token."""
    try:
        payload = jwt.decode(
            token_str,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.PyJWTError as exc:
        logger.warning(f"JWT decode failed: {exc}")
        return None


async def get_current_business(
    slug: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Business:
    """
    FastAPI security dependency protecting business owner routes.
    Supports:
    1. Authorization header: 'Bearer <token>'
    2. URL Query parameter: '?token=<token>'
    3. Master Admin Key: allows instant bypass / debug access
    """
    # 1. Resolve business by slug
    business = await get_business_by_slug(db=db, slug=slug)
    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business '{slug}' not found or inactive",
        )

    # 2. Extract candidate token
    extracted_token = None
    if authorization:
        parts = authorization.split(" ")
        if len(parts) == 2 and parts[0].lower() == "bearer":
            extracted_token = parts[1].strip()
        else:
            extracted_token = authorization.strip()
    elif token:
        extracted_token = token.strip()

    if not extracted_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token. Please login via PIN or Magic Link.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Check Master Admin Key
    if settings.MASTER_ADMIN_KEY and extracted_token == settings.MASTER_ADMIN_KEY:
        logger.info(f"Authorized access to '{slug}' via MASTER_ADMIN_KEY.")
        return business

    # 4. Decode and validate JWT
    payload = decode_business_access_token(extracted_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_business_id = payload.get("business_id")
    token_slug = payload.get("slug")

    if token_business_id != business.id and token_slug != business.slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not grant access to this business.",
        )

    return business
