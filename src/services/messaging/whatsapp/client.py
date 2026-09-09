import asyncio
import logging
import random
from typing import Any, Dict, List, Optional
import httpx

from src.config.settings import get_settings
from src.services.messaging.base import BaseMessageProvider
from src.services.messaging.whatsapp.templates import (
    build_slot_alert_template_payload,
    clean_claim_token,
)
from src.utils.phone import clean_e164_whatsapp

logger = logging.getLogger("slotalert.whatsapp.client")
settings = get_settings()


# ==============================================================================
# Structured Meta Graph API Exceptions
# ==============================================================================

class WhatsAppAPIError(Exception):
    """Base exception for WhatsApp Cloud API errors."""

    def __init__(
        self,
        message: str,
        code: Optional[int] = None,
        subcode: Optional[int] = None,
        fbtrace_id: Optional[str] = None,
        raw_error: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.subcode = subcode
        self.fbtrace_id = fbtrace_id
        self.raw_error = raw_error or {}


class WhatsAppTokenExpiredError(WhatsAppAPIError):
    """Code 190: Access token has expired, been revoked, or is invalid."""
    pass


class WhatsAppReEngagementRequiredError(WhatsAppAPIError):
    """Code 131047: 24-hour service window closed. Template message required."""
    pass


class WhatsAppSandboxRecipientRestrictionError(WhatsAppAPIError):
    """Code 131030: Recipient phone number is not allowed in developer sandbox."""
    pass


class WhatsAppRateLimitError(WhatsAppAPIError):
    """Code 130429 or HTTP 429: Cloud API rate limit exceeded."""
    pass


# ==============================================================================
# Production-Hardened Meta WhatsApp Cloud API Client
# ==============================================================================

class WhatsAppCloudAPIClient(BaseMessageProvider):
    """
    Production-grade Meta WhatsApp Cloud API Client (v20.0+).
    Features:
    - Persistent connection-pooled httpx.AsyncClient
    - Exponential backoff with jitter on transient 5xx / 429 errors
    - Granular error translation for Meta error response payloads
    - Compliant Template messaging for cancellation alerts
    - Direct session text messaging within 24-hour customer care window
    - Message read receipt marking (blue ticks)
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        api_version: Optional[str] = None,
        max_retries: Optional[int] = None,
        backoff_factor: Optional[float] = None,
    ) -> None:
        self.api_token = api_token or settings.whatsapp_access_token_value
        self.phone_number_id = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
        self.api_version = api_version or settings.WHATSAPP_API_VERSION
        self.max_retries = max_retries if max_retries is not None else settings.WHATSAPP_MAX_RETRIES
        self.backoff_factor = backoff_factor if backoff_factor is not None else settings.WHATSAPP_RETRY_BACKOFF_FACTOR

        self.base_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

        # Shared persistent connection-pooled HTTP client
        self._http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
                keepalive_expiry=30.0,
            ),
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def _parse_and_raise_meta_error(self, response: httpx.Response) -> None:
        """Parses Meta Graph API error response and raises structured domain exception."""
        try:
            body = response.json()
            err = body.get("error", {})
        except Exception:
            err = {}

        code = err.get("code")
        subcode = err.get("error_subcode")
        message = err.get("message", f"HTTP {response.status_code}: {response.text}")
        fbtrace_id = err.get("fbtrace_id")

        logger.error(
            f"Meta Graph API Error [HTTP {response.status_code}] Code: {code} "
            f"Subcode: {subcode} Msg: {message} TraceID: {fbtrace_id}"
        )

        if code == 190:
            raise WhatsAppTokenExpiredError(message, code=code, subcode=subcode, fbtrace_id=fbtrace_id, raw_error=err)
        elif code == 131047:
            raise WhatsAppReEngagementRequiredError(message, code=code, subcode=subcode, fbtrace_id=fbtrace_id, raw_error=err)
        elif code == 131030:
            raise WhatsAppSandboxRecipientRestrictionError(message, code=code, subcode=subcode, fbtrace_id=fbtrace_id, raw_error=err)
        elif code == 130429 or response.status_code == 429:
            raise WhatsAppRateLimitError(message, code=code, subcode=subcode, fbtrace_id=fbtrace_id, raw_error=err)

        raise WhatsAppAPIError(message, code=code, subcode=subcode, fbtrace_id=fbtrace_id, raw_error=err)

    async def _post_with_retry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Post payload to Meta Graph API with exponential jitter backoff on transient errors.
        """
        if not self.api_token or not self.phone_number_id:
            logger.warning("WhatsApp API credentials missing; skipping external Graph API call.")
            return {"messages": [{"id": "mock_wamid_missing_credentials"}]}

        attempt = 0
        while attempt <= self.max_retries:
            try:
                response = await self._http_client.post(
                    self.base_url,
                    json=payload,
                    headers=self._get_headers(),
                )

                # Transient server errors or rate limits -> retry
                if response.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    attempt += 1
                    sleep_time = (self.backoff_factor * (2 ** (attempt - 1))) + random.uniform(0.1, 0.5)
                    logger.warning(
                        f"Transient Meta error (HTTP {response.status_code}). Retrying in {sleep_time:.2f}s "
                        f"(attempt {attempt}/{self.max_retries})..."
                    )
                    await asyncio.sleep(sleep_time)
                    continue

                if response.status_code >= 400:
                    self._parse_and_raise_meta_error(response)

                return response.json()

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError) as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    sleep_time = (self.backoff_factor * (2 ** (attempt - 1))) + random.uniform(0.1, 0.5)
                    logger.warning(
                        f"Network error calling Meta ({type(exc).__name__}). Retrying in {sleep_time:.2f}s "
                        f"(attempt {attempt}/{self.max_retries})..."
                    )
                    await asyncio.sleep(sleep_time)
                    continue
                logger.error(f"Network error calling Meta exhausted all retries: {exc}")
                raise

        raise WhatsAppAPIError(f"Exhausted {self.max_retries} retries calling Meta Graph API.")

    async def send_template_message(
        self,
        to_phone: str,
        template_name: str,
        language_code: str = "he",
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Send a pre-approved Meta WhatsApp Template message.
        """
        clean_phone = clean_e164_whatsapp(to_phone)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components or [],
            },
        }

        logger.info(f"Dispatching Meta template '{template_name}' to {clean_phone}")
        data = await self._post_with_retry(payload)
        messages = data.get("messages", [])
        if messages:
            return messages[0].get("id", "")
        return ""

    async def send_slot_alert(
        self,
        phone_number: str,
        customer_name: str,
        business_name: str,
        service_name: str,
        start_time_formatted: str,
        claim_url: str = "",
        price: Optional[object] = None,
        claim_token: Optional[str] = None,
        slot_datetime_str: Optional[str] = None,
        template_name: Optional[str] = None,
        language_code: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Send WhatsApp cancellation alert using pre-approved template with Call-to-Action (URL) button.
        """
        clean_phone = clean_e164_whatsapp(phone_number)
        datetime_display = slot_datetime_str or start_time_formatted
        resolved_token = clean_claim_token(claim_token=claim_token, claim_url=claim_url)
        tpl_name = template_name or settings.WHATSAPP_SLOT_TEMPLATE_NAME
        tpl_lang = language_code or settings.WHATSAPP_SLOT_TEMPLATE_LANG

        payload = build_slot_alert_template_payload(
            to_phone=clean_phone,
            customer_name=customer_name,
            business_name=business_name,
            slot_datetime_str=datetime_display,
            service_name=service_name,
            claim_token=resolved_token,
            template_name=tpl_name,
            language_code=tpl_lang,
            start_time_formatted=datetime_display,
            claim_url=claim_url,
            **kwargs,
        )

        logger.info(
            f"Sending WhatsApp slot alert CTA template '{tpl_name}' to {clean_phone} "
            f"(token: {resolved_token})"
        )
        data = await self._post_with_retry(payload)
        messages = data.get("messages", [])
        if messages:
            return messages[0].get("id", "")
        return ""

    async def send_text_message(self, to_phone: str, text: str) -> str:
        """
        Send direct text message notification within the 24-hour service window.
        """
        clean_phone = clean_e164_whatsapp(to_phone)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {
                "body": text,
                "preview_url": False,
            },
        }

        logger.info(f"Sending WhatsApp session text notification to {clean_phone}")
        data = await self._post_with_retry(payload)
        messages = data.get("messages", [])
        if messages:
            return messages[0].get("id", "")
        return ""

    async def mark_as_read(self, message_id: str) -> bool:
        """
        Marks an incoming WhatsApp message as read (blue ticks).
        """
        if not message_id or message_id.startswith("mock_"):
            return True

        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }

        try:
            data = await self._post_with_retry(payload)
            return bool(data.get("success", True))
        except Exception as exc:
            logger.warning(f"Failed to mark message {message_id} as read: {exc}")
            return False

    async def close(self) -> None:
        """Close underlying httpx client connection pool."""
        await self._http_client.aclose()
