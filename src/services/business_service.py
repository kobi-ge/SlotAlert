import re
import uuid
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.business import Business
from src.models.service import Service
from src.schemas.business import BusinessRegisterRequest

HEBREW_TO_LATIN = {
    'א': 'a', 'ב': 'b', 'ג': 'g', 'ד': 'd', 'ה': 'h', 'ו': 'v', 'ז': 'z',
    'ח': 'ch', 'ט': 't', 'י': 'y', 'כ': 'k', 'ך': 'k', 'ל': 'l', 'מ': 'm',
    'ם': 'm', 'נ': 'n', 'ן': 'n', 'ס': 's', 'ע': 'a', 'פ': 'p', 'ף': 'p',
    'צ': 'tz', 'ץ': 'tz', 'ק': 'k', 'ר': 'r', 'ש': 'sh', 'ת': 't'
}


def slugify_name(name: str) -> str:
    """Convert Hebrew or English business name into an ASCII URL slug."""
    chars = []
    for char in name.lower():
        if char in HEBREW_TO_LATIN:
            chars.append(HEBREW_TO_LATIN[char])
        elif char.isalnum() or char in " -_":
            chars.append(char)
    transliterated = "".join(chars)
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
    if not slug:
        slug = f"biz-{uuid.uuid4().hex[:6]}"
    return slug[:40]


async def get_business_by_slug(db: AsyncSession, slug: str) -> Optional[Business]:
    """
    Retrieve active business and its offerings by unique slug.
    Preloads services eagerly.
    """
    stmt = (
        select(Business)
        .options(selectinload(Business.services))
        .where(
            Business.slug == slug,
            Business.is_active == True,  # noqa: E712
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def register_new_business(db: AsyncSession, data: BusinessRegisterRequest) -> Business:
    """
    Self-serve registration of a new business with its initial services.
    Ensures slug uniqueness via collision resolution.
    """
    # 1. Check if phone number already registered
    phone_check = await db.execute(
        select(Business.id).where(Business.phone_number == data.phone_number)
    )
    if phone_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="מספר טלפון זה כבר רשום במערכת.",
        )

    # 2. Determine base slug
    if data.slug and data.slug.strip():
        base_slug = slugify_name(data.slug.strip())
    else:
        base_slug = slugify_name(data.name.strip())

    # 3. Handle collision
    candidate = base_slug
    counter = 2
    while True:
        existing = await db.execute(
            select(Business.id).where(Business.slug == candidate)
        )
        if not existing.scalar_one_or_none():
            break
        candidate = f"{base_slug[:35]}-{counter}"
        counter += 1

    # 4. Create Business entity
    business = Business(
        name=data.name.strip(),
        phone_number=data.phone_number,
        business_type=data.business_type or "clinic",
        slug=candidate,
        is_active=True,
    )
    db.add(business)
    await db.flush()

    # 5. Create Services
    for item in data.services:
        service = Service(
            business_id=business.id,
            name=item.name.strip(),
            duration_minutes=item.duration_minutes,
            price=item.price,
        )
        db.add(service)

    await db.commit()

    # 6. Eagerly reload with services
    registered = await get_business_by_slug(db, candidate)
    return registered or business

