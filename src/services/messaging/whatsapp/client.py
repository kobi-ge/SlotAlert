import logging
from typing import Any, Dict, Optional
import httpx

from src.config.settings import get_settings
from src.services.messaging.base import BaseMessageProvider
from src.services.messaging.whatsapp.templates import build_slot_offer_interactive_payload

logger = logging.getLogger("slotalert.whatsapp.client")
settings = get_settings()


class WhatsAppCloudAPIClient(BaseMessageProvider):
    """Meta WhatsApp Business Cloud API Client using httpx."""

    def __init__(
        self,
        api_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        api_version: Optional[str] = None,
    ) -> None:
        self.api_token = api_token or settings.WHATSAPP_API_TOKEN
        self.phone_number_id = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
        self.api_version = api_version or settings.WHATSAPP_API_VERSION
        self.base_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    async def _post_message(self, payload: Dict[str, Any]) -> str:
        """Internal helper to post JSON payload to Graph API."""
        if not self.api_token or not self.phone_number_id:
            logger.warning("WhatsApp API credentials missing; skipping external Graph API call.")
            return "mock_wamid_missing_credentials"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self.base_url,
                json=payload,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()
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
        claim_url: str,
        price: Optional[object] = None,
    ) -> str:
        """
        Send interactive WhatsApp message offering slot with Claim & Opt-out buttons.
        """
        # Clean phone number (strip leading + or spaces if required)
        clean_phone = phone_number.replace(" ", "").replace("-", "")
        if clean_phone.startswith("+"):
            clean_phone = clean_phone[1:]

        # Extract slot_id and customer_id from claim_url if possible, or build payload
        # Standard claim_url format: http://.../api/v1/slots/{slot_id}/claim
        slot_id = 0
        customer_id = 0
        try:
            parts = claim_url.rstrip("/").split("/")
            if "slots" in parts:
                slot_id_idx = parts.index("slots") + 1
                slot_id = int(parts[slot_id_idx])
        except Exception:
            pass

        payload = build_slot_offer_interactive_payload(
            to_phone=clean_phone,
            customer_id=customer_id,
            customer_name=customer_name,
            business_name=business_name,
            service_name=service_name,
            start_time_formatted=start_time_formatted,
            slot_id=slot_id,
            claim_url=claim_url,
        )

        logger.info(f"Sending WhatsApp interactive slot alert to {clean_phone} for slot {slot_id}")
        return await self._post_message(payload)

    async def send_text_message(self, to_phone: str, text: str) -> str:
        """Send direct text message notification."""
        clean_phone = to_phone.replace(" ", "").replace("-", "")
        if clean_phone.startswith("+"):
            clean_phone = clean_phone[1:]

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {
                "body": text,
            },
        }

        logger.info(f"Sending WhatsApp text notification to {clean_phone}")
        return await self._post_message(payload)
