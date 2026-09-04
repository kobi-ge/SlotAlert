import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from src.config.settings import get_settings
from src.database.connection import get_redis_client
from src.models.business import Business
from src.services.messaging.mock_provider import get_message_provider

settings = get_settings()


@pytest.mark.asyncio
async def test_auth_protected_routes_require_token(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Accessing protected business routes without token must return 401 Unauthorized."""
    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת אבטחה",
        phone_number=f"+97250{uid}99",
        business_type="clinic",
        slug=f"sec-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.commit()

    # 1. Dashboard without auth
    res1 = await client.get(f"/api/v1/business/{biz.slug}/dashboard")
    assert res1.status_code == 401

    # 2. Waitlist without auth
    res2 = await client.get(f"/api/v1/business/{biz.slug}/waitlist")
    assert res2.status_code == 401

    # 3. Quick-publish without auth
    res3 = await client.post(
        f"/api/v1/business/{biz.slug}/quick-publish",
        json={"service_id": 1, "start_time": "2026-10-01T10:00:00Z"},
    )
    assert res3.status_code == 401


@pytest.mark.asyncio
async def test_request_and_verify_pin_flow(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Test full frictionless authentication:
    - Request PIN sends WhatsApp alert
    - Wrong PIN rejected (400)
    - Correct PIN issues valid 30-day token
    - Token unlocks protected dashboard
    """
    provider = get_message_provider()
    provider.clear()

    uid = uuid.uuid4().hex[:6]
    biz = Business(
        name="קליניקת פין",
        phone_number=f"+97250{uid}88",
        business_type="clinic",
        slug=f"pin-test-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.commit()

    # 1. Request PIN
    res_req = await client.post(f"/api/v1/auth/{biz.slug}/request-pin")
    assert res_req.status_code == 200
    data_req = res_req.json()
    assert data_req["success"] is True
    assert "***" in data_req["phone_masked"]

    # Verify message sent to MockMessageProvider
    assert len(provider.sent_messages) == 1
    pin_msg = provider.sent_messages[0]
    assert pin_msg.phone_number == biz.phone_number
    assert "קוד הכניסה שלך" in pin_msg.body

    # Get PIN from Redis
    redis = get_redis_client()
    cached_pin = await redis.get(f"auth:pin:{biz.id}")
    assert cached_pin is not None

    # 2. Verify with incorrect PIN
    res_wrong = await client.post(
        f"/api/v1/auth/{biz.slug}/verify-pin",
        json={"pin": "0000"},
    )
    assert res_wrong.status_code == 400

    # 3. Verify with correct PIN
    res_correct = await client.post(
        f"/api/v1/auth/{biz.slug}/verify-pin",
        json={"pin": cached_pin},
    )
    assert res_correct.status_code == 200
    token_data = res_correct.json()
    assert "access_token" in token_data
    access_token = token_data["access_token"]

    # Verify PIN was consumed from Redis
    assert await redis.get(f"auth:pin:{biz.id}") is None

    # 4. Access protected dashboard using Bearer token
    headers = {"Authorization": f"Bearer {access_token}"}
    res_dash = await client.get(f"/api/v1/business/{biz.slug}/dashboard", headers=headers)
    assert res_dash.status_code == 200
    assert res_dash.json()["business_name"] == "קליניקת פין"

    # 5. Access using URL query param ?token=
    res_query = await client.get(f"/api/v1/business/{biz.slug}/dashboard?token={access_token}")
    assert res_query.status_code == 200


@pytest.mark.asyncio
async def test_master_admin_key_and_tenant_isolation(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Test MASTER_ADMIN_KEY bypass and token cross-tenant prevention."""
    uid1 = uuid.uuid4().hex[:6]
    uid2 = uuid.uuid4().hex[:6]

    biz1 = Business(
        name="קליניקה א",
        phone_number=f"+97250{uid1}01",
        business_type="clinic",
        slug=f"biz-a-{uid1}",
        is_active=True,
    )
    biz2 = Business(
        name="קליניקה ב",
        phone_number=f"+97250{uid2}02",
        business_type="clinic",
        slug=f"biz-b-{uid2}",
        is_active=True,
    )
    db_session.add_all([biz1, biz2])
    await db_session.commit()

    # 1. Master admin key grants access
    headers_master = {"Authorization": f"Bearer {settings.MASTER_ADMIN_KEY}"}
    res_master = await client.get(f"/api/v1/business/{biz1.slug}/dashboard", headers=headers_master)
    assert res_master.status_code == 200

    # 2. Token for Biz1 cannot access Biz2
    from src.core.security import create_business_access_token
    token_biz1 = create_business_access_token(business_id=biz1.id, slug=biz1.slug)

    headers_biz1 = {"Authorization": f"Bearer {token_biz1}"}
    res_cross = await client.get(f"/api/v1/business/{biz2.slug}/dashboard", headers=headers_biz1)
    assert res_cross.status_code == 403
