import pytest
import httpx
from unittest.mock import AsyncMock, patch

from src.config.settings import Settings
from src.services.messaging.whatsapp.client import (
    WhatsAppAPIError,
    WhatsAppCloudAPIClient,
    WhatsAppRateLimitError,
    WhatsAppReEngagementRequiredError,
    WhatsAppSandboxRecipientRestrictionError,
    WhatsAppTokenExpiredError,
)
from src.services.messaging.whatsapp.templates import (
    build_slot_alert_template_payload,
    clean_claim_token,
)
from src.utils.phone import (
    clean_e164_whatsapp,
    format_display_phone,
    get_phone_search_variants,
)


def test_phone_sanitization_and_matching():
    """Verify clean_e164_whatsapp translates Israeli domestic numbers and international formats."""
    # Domestic Israeli numbers with hyphens/spaces
    assert clean_e164_whatsapp("050-123-4567") == "972501234567"
    assert clean_e164_whatsapp("052 999 8888") == "972529998888"
    assert clean_e164_whatsapp("0541112233") == "972541112233"

    # International formats with leading + and spaces
    assert clean_e164_whatsapp("+972-50-123-4567") == "972501234567"
    assert clean_e164_whatsapp("+972501234567") == "972501234567"
    assert clean_e164_whatsapp("972501234567") == "972501234567"

    # Formatting helper
    assert format_display_phone("972501234567") == "050-1234567"

    # Search variants for zero-downtime DB query
    variants = get_phone_search_variants("050-123-4567")
    assert "972501234567" in variants
    assert "+972501234567" in variants
    assert "0501234567" in variants

    # Invalid cases
    with pytest.raises(ValueError):
        clean_e164_whatsapp("123")  # Too short
    with pytest.raises(ValueError):
        clean_e164_whatsapp("abcdefghij")  # Non-digits


def test_url_button_template_payload_structure():
    """Verify template payload uses 4 body parameters and 1 URL CTA button."""
    payload = build_slot_alert_template_payload(
        to_phone="972501234567",
        customer_name="ישראל ישראלי",
        business_name="מרפאת העיר",
        slot_datetime_str="יום שישי בשעה 09:00",
        service_name="טיפול שיניים",
        claim_token="claim_token_abc_123",
        template_name="slot_cancellation_alert_v1",
        language_code="he",
    )

    assert payload["type"] == "template"
    template = payload["template"]
    assert template["name"] == "slot_cancellation_alert_v1"
    assert template["language"]["code"] == "he"

    components = template["components"]
    assert len(components) == 2

    # 1. Body component (strictly 4 parameters: customer, business, datetime, service)
    body_comp = components[0]
    assert body_comp["type"] == "body"
    assert len(body_comp["parameters"]) == 4
    assert body_comp["parameters"][0]["text"] == "ישראל ישראלי"
    assert body_comp["parameters"][1]["text"] == "מרפאת העיר"
    assert body_comp["parameters"][2]["text"] == "יום שישי בשעה 09:00"
    assert body_comp["parameters"][3]["text"] == "טיפול שיניים"

    # 2. Button component (sub_type: url, index: "0")
    btn0 = components[1]
    assert btn0["type"] == "button"
    assert btn0["sub_type"] == "url"
    assert btn0["index"] == "0"
    assert len(btn0["parameters"]) == 1
    assert btn0["parameters"][0]["type"] == "text"
    assert btn0["parameters"][0]["text"] == "claim_token_abc_123"


def test_clean_claim_token():
    """Verify clean_claim_token handles whitespace, leading slashes, and URL extraction."""
    # Direct token cleaning
    assert clean_claim_token("  token_123 \n ") == "token_123"
    assert clean_claim_token("/token_456") == "token_456"
    assert clean_claim_token("token with spaces") == "tokenwithspaces"

    # Extraction from claim_url
    assert clean_claim_token(claim_url="http://localhost:8000/api/v1/slots/99/claim") == "99"
    assert clean_claim_token(claim_url="https://domain.com/claim/secure_tok_789") == "secure_tok_789"
    assert clean_claim_token(claim_url="https://domain.com/claim/tok?ref=wa") == "tok?ref=wa"

    # Fallback on empty
    assert clean_claim_token("") == "claim"
    assert clean_claim_token(None, None) == "claim"


@pytest.mark.asyncio
async def test_client_send_template_success():
    """Verify WhatsAppCloudAPIClient sends URL button template and extracts wamid."""
    client = WhatsAppCloudAPIClient(
        api_token="test_token",
        phone_number_id="123456789",
        api_version="v20.0",
        max_retries=1,
    )

    fake_response = httpx.Response(
        status_code=200,
        json={"messages": [{"id": "wamid.HBgMOTE1MjE3MDQ1FQIAERgSRjQ1Q0IzOTg4OAA="}]},
        request=httpx.Request("POST", client.base_url),
    )

    with patch.object(client._http_client, "post", new=AsyncMock(return_value=fake_response)) as mock_post:
        wamid = await client.send_slot_alert(
            phone_number="050-123-4567",
            customer_name="שרה לוי",
            business_name="קליניקת יופי",
            service_name="מניקור",
            start_time_formatted="היום 16:00",
            claim_url="http://localhost:8000/api/v1/slots/99/claim",
        )
        assert wamid == "wamid.HBgMOTE1MjE3MDQ1FQIAERgSRjQ1Q0IzOTg4OAA="

        # Verify dispatched payload structure conforms to URL CTA button requirements
        mock_post.assert_called_once()
        sent_payload = mock_post.call_args.kwargs["json"]
        assert sent_payload["messaging_product"] == "whatsapp"
        assert sent_payload["to"] == "972501234567"
        assert sent_payload["type"] == "template"

        tpl = sent_payload["template"]
        assert tpl["name"] == "slot_cancellation_alert_v1"
        assert tpl["language"]["code"] == "he"

        components = tpl["components"]
        assert len(components) == 2

        # 4 body parameters
        body = components[0]
        assert body["type"] == "body"
        assert len(body["parameters"]) == 4
        assert body["parameters"][0]["text"] == "שרה לוי"
        assert body["parameters"][1]["text"] == "קליניקת יופי"
        assert body["parameters"][2]["text"] == "היום 16:00"
        assert body["parameters"][3]["text"] == "מניקור"

        # URL CTA button component
        btn = components[1]
        assert btn["type"] == "button"
        assert btn["sub_type"] == "url"
        assert btn["index"] == "0"
        assert btn["parameters"][0]["text"] == "99"

    await client.close()


@pytest.mark.asyncio
async def test_client_error_parsing_and_exceptions():
    """Verify client translates Meta Graph API error codes into domain exceptions."""
    client = WhatsAppCloudAPIClient(
        api_token="test_token",
        phone_number_id="123456789",
        max_retries=0,
    )

    # 1. Token Expired (Code 190)
    token_err_resp = httpx.Response(
        status_code=401,
        json={"error": {"message": "Error validating access token: Session has expired.", "code": 190, "fbtrace_id": "trace123"}},
        request=httpx.Request("POST", client.base_url),
    )
    with patch.object(client._http_client, "post", new=AsyncMock(return_value=token_err_resp)):
        with pytest.raises(WhatsAppTokenExpiredError) as exc_info:
            await client.send_text_message("0501112233", "Hello")
        assert exc_info.value.code == 190
        assert exc_info.value.fbtrace_id == "trace123"

    # 2. 24h Window Closed (Code 131047)
    window_err_resp = httpx.Response(
        status_code=400,
        json={"error": {"message": "Re-engagement message", "code": 131047}},
        request=httpx.Request("POST", client.base_url),
    )
    with patch.object(client._http_client, "post", new=AsyncMock(return_value=window_err_resp)):
        with pytest.raises(WhatsAppReEngagementRequiredError) as exc_info:
            await client.send_text_message("0501112233", "Hello outside window")
        assert exc_info.value.code == 131047

    # 3. Sandbox Restriction (Code 131030)
    sandbox_err_resp = httpx.Response(
        status_code=400,
        json={"error": {"message": "Recipient phone number not in allowed list", "code": 131030}},
        request=httpx.Request("POST", client.base_url),
    )
    with patch.object(client._http_client, "post", new=AsyncMock(return_value=sandbox_err_resp)):
        with pytest.raises(WhatsAppSandboxRecipientRestrictionError) as exc_info:
            await client.send_text_message("0501112233", "Hello sandbox")
        assert exc_info.value.code == 131030

    # 4. Rate Limit (HTTP 429 / Code 130429)
    rate_err_resp = httpx.Response(
        status_code=429,
        json={"error": {"message": "Rate limit hit", "code": 130429}},
        request=httpx.Request("POST", client.base_url),
    )
    with patch.object(client._http_client, "post", new=AsyncMock(return_value=rate_err_resp)):
        with pytest.raises(WhatsAppRateLimitError) as exc_info:
            await client.send_text_message("0501112233", "Hello rate")
        assert exc_info.value.code == 130429

    await client.close()


@pytest.mark.asyncio
async def test_client_retry_on_transient_failure():
    """Verify client retries with backoff on transient HTTP 500 error then succeeds."""
    client = WhatsAppCloudAPIClient(
        api_token="test_token",
        phone_number_id="123456789",
        max_retries=2,
        backoff_factor=0.01,
    )

    fail_resp = httpx.Response(
        status_code=500,
        json={"error": {"message": "Temporary internal Meta error"}},
        request=httpx.Request("POST", client.base_url),
    )
    success_resp = httpx.Response(
        status_code=200,
        json={"messages": [{"id": "wamid.success_retry"}]},
        request=httpx.Request("POST", client.base_url),
    )

    mock_post = AsyncMock(side_effect=[fail_resp, success_resp])
    with patch.object(client._http_client, "post", new=mock_post):
        wamid = await client.send_text_message("0501112233", "Retry message")
        assert wamid == "wamid.success_retry"
        assert mock_post.call_count == 2

    await client.close()


@pytest.mark.asyncio
async def test_mark_as_read_payload():
    """Verify mark_as_read sends status='read' payload to Meta."""
    client = WhatsAppCloudAPIClient(
        api_token="test_token",
        phone_number_id="123456789",
        max_retries=0,
    )

    success_resp = httpx.Response(
        status_code=200,
        json={"success": True},
        request=httpx.Request("POST", client.base_url),
    )

    with patch.object(client._http_client, "post", new=AsyncMock(return_value=success_resp)) as mock_call:
        res = await client.mark_as_read("wamid.12345")
        assert res is True
        # Check payload
        called_payload = mock_call.call_args.kwargs["json"]
        assert called_payload["status"] == "read"
        assert called_payload["message_id"] == "wamid.12345"

    await client.close()


def test_factory_provider_resolution(monkeypatch):
    """Verify factory properly resolves to WhatsAppCloudAPIClient or MockMessageProvider."""
    from pydantic import SecretStr
    from src.config.settings import get_settings
    from src.services.messaging.factory import (
        get_configured_message_provider,
        reset_provider_instance,
    )
    from src.services.messaging.mock_provider import MockMessageProvider

    settings = get_settings()

    # 1. Default in testing -> MockMessageProvider
    reset_provider_instance()
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "mock")
    prov_mock = get_configured_message_provider()
    assert isinstance(prov_mock, MockMessageProvider)

    # 2. In production with credentials -> automatically resolves to WhatsAppCloudAPIClient
    reset_provider_instance()
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", None)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", SecretStr("test_token_123"))
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "987654321")
    prov_meta = get_configured_message_provider()
    assert isinstance(prov_meta, WhatsAppCloudAPIClient)

    # 3. Explicit WHATSAPP_PROVIDER=meta -> resolves to WhatsAppCloudAPIClient
    reset_provider_instance()
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "meta")
    prov_explicit_meta = get_configured_message_provider()
    assert isinstance(prov_explicit_meta, WhatsAppCloudAPIClient)

    # Cleanup
    reset_provider_instance()


def test_database_url_normalization():
    """Verify DATABASE_URL automatically normalizes postgresql:// to postgresql+asyncpg://."""
    from src.config.settings import Settings

    s1 = Settings(DATABASE_URL="postgresql://user:pass@host:5432/db")
    assert s1.DATABASE_URL == "postgresql+asyncpg://user:pass@host:5432/db"

    s2 = Settings(DATABASE_URL="postgres://user:pass@host:5432/db")
    assert s2.DATABASE_URL == "postgresql+asyncpg://user:pass@host:5432/db"

    s3 = Settings(DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db")
    assert s3.DATABASE_URL == "postgresql+asyncpg://user:pass@host:5432/db"

