import uuid
import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.business import Business
from src.database.connection import get_redis_client
from src.services.messaging.factory import get_configured_message_provider


@pytest.mark.asyncio
async def test_login_request_unknown_phone_returns_404(client: httpx.AsyncClient):
    """Verify unregistered phone number returns 404 with friendly Hebrew error."""
    payload = {"phone_number": "050-0000000"}
    res = await client.post("/api/v1/auth/business-login-request", json=payload)
    assert res.status_code == 404
    data = res.json()
    assert "לא קיים עסק פעיל עם מספר טלפון זה" in data.get("detail", "")


@pytest.mark.asyncio
async def test_login_request_and_verify_success(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """
    Test full 2-step login flow:
    1. Create business
    2. Request login OTP via WhatsApp
    3. Retrieve OTP from Redis
    4. Verify OTP and receive 30-day JWT token
    """
    uid = uuid.uuid4().hex[:6]
    phone_digits = f"54{int(uuid.uuid4().int % 9000000 + 1000000)}"
    local_phone = f"0{phone_digits}"
    e164_phone = f"+972{phone_digits}"

    biz = Business(
        name=f"קליניקת {uid}",
        phone_number=e164_phone,
        business_type="clinic",
        slug=f"biz-login-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.commit()

    # Step 1: Request OTP
    req_res = await client.post(
        "/api/v1/auth/business-login-request",
        json={"phone_number": local_phone},
    )
    assert req_res.status_code == 200, req_res.text
    req_data = req_res.json()
    assert req_data["success"] is True
    assert req_data["slug"] == biz.slug
    assert req_data["business_name"] == biz.name

    # Check OTP in Redis
    redis = get_redis_client()
    otp = await redis.get(f"otp:login:{biz.id}")
    assert otp is not None
    assert len(otp) == 6

    # Verify mock messaging provider received text
    provider = get_configured_message_provider()
    assert len(provider.sent_messages) > 0
    last_msg = provider.sent_messages[-1]
    assert last_msg is not None
    assert otp in last_msg.body


    # Step 2: Verify OTP
    verify_res = await client.post(
        "/api/v1/auth/business-login-verify",
        json={"phone_number": local_phone, "code": otp},
    )
    assert verify_res.status_code == 200, verify_res.text
    verify_data = verify_res.json()
    assert verify_data["success"] is True
    assert verify_data["slug"] == biz.slug
    assert verify_data["access_token"]
    assert verify_data["token_type"] == "bearer"
    assert verify_data["dashboard_url"] == f"/dashboard/{biz.slug}"

    # Verify Redis key deleted after match
    cached_after = await redis.get(f"otp:login:{biz.id}")
    assert cached_after is None


@pytest.mark.asyncio
async def test_login_verify_invalid_code_fails(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
):
    """Verify mismatched or bad code returns 400."""
    uid = uuid.uuid4().hex[:6]
    phone_digits = f"54{int(uuid.uuid4().int % 9000000 + 1000000)}"
    local_phone = f"0{phone_digits}"
    e164_phone = f"+972{phone_digits}"

    biz = Business(
        name=f"קליניקת {uid}",
        phone_number=e164_phone,
        business_type="clinic",
        slug=f"biz-fail-{uid}",
        is_active=True,
    )
    db_session.add(biz)
    await db_session.commit()

    # Request OTP
    req_res = await client.post(
        "/api/v1/auth/business-login-request",
        json={"phone_number": local_phone},
    )
    assert req_res.status_code == 200

    # Submit invalid code
    bad_res = await client.post(
        "/api/v1/auth/business-login-verify",
        json={"phone_number": local_phone, "code": "000000"},
    )
    assert bad_res.status_code == 400
    assert "קוד אימות שגוי או שפג תוקפו" in bad_res.json().get("detail", "")
