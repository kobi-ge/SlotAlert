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


def test_quick_reply_template_payload_structure():
    """Verify template payload strictly uses pure QUICK_REPLY buttons."""
    payload = build_slot_alert_template_payload(
        to_phone="972501234567",
        customer_id=10,
        customer_name="ישראל ישראלי",
        business_name="מרפאת העיר",
        service_name="טיפול שיניים",
        start_time_formatted="יום שישי בשעה 09:00",
        slot_id=25,
        template_name="slot_cancellation_alert_v1",
        language_code="he",
    )

    assert payload["type"] == "template"
    template = payload["template"]
    assert template["name"] == "slot_cancellation_alert_v1"
    assert template["language"]["code"] == "he"

    components = template["components"]
    assert len(components) == 3

    # Body component
    body_comp = components[0]
    assert body_comp["type"] == "body"
    assert len(body_comp["parameters"]) == 4
    assert body_comp["parameters"][0]["text"] == "ישראל ישראלי"
    assert body_comp["parameters"][1]["text"] == "מרפאת העיר"
    assert body_comp["parameters"][2]["text"] == "טיפול שיניים"
    assert body_comp["parameters"][3]["text"] == "יום שישי בשעה 09:00"

    # Button 0: Quick Reply claim
    btn0 = components[1]
    assert btn0["type"] == "button"
    assert btn0["sub_type"] == "quick_reply"
    assert btn0["index"] == 0
    assert btn0["parameters"][0]["payload"] == "claim:25:10"

    # Button 1: Quick Reply optout
    btn1 = components[2]
    assert btn1["type"] == "button"
    assert btn1["sub_type"] == "quick_reply"
    assert btn1["index"] == 1
    assert btn1["parameters"][0]["payload"] == "optout:10"


@pytest.mark.asyncio
async def test_client_send_template_success():
    """Verify WhatsAppCloudAPIClient sends template and extracts wamid."""
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

    with patch.object(client._http_client, "post", new=AsyncMock(return_value=fake_response)):
        wamid = await client.send_slot_alert(
            phone_number="050-123-4567",
            customer_name="שרה לוי",
            business_name="קליניקת יופי",
            service_name="מניקור",
            start_time_formatted="היום 16:00",
            claim_url="http://localhost:8000/api/v1/slots/99/claim",
        )
        assert wamid == "wamid.HBgMOTE1MjE3MDQ1FQIAERgSRjQ1Q0IzOTg4OAA="

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
