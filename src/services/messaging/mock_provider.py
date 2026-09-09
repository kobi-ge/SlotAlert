import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.services.messaging.base import BaseMessageProvider

logger = logging.getLogger("slotalert.messaging.mock")


@dataclass
class SentMessage:
    """Structure recording a dispatched message."""
    message_sid: str
    phone_number: str
    customer_name: str
    business_name: str
    service_name: str
    start_time_formatted: str
    claim_url: str
    body: str
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MockMessageProvider(BaseMessageProvider):
    """In-memory mock message provider for local development, simulation, and tests."""

    def __init__(self) -> None:
        self.sent_messages: List[SentMessage] = []
        self._by_sid: Dict[str, SentMessage] = {}

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
        **kwargs: Any,
    ) -> str:
        """Simulate sending a WhatsApp slot alert message."""
        message_sid = f"mock_msg_{uuid.uuid4().hex[:12]}"
        price_str = f"\nמחיר: ₪{price}" if price is not None else ""
        body = (
            f"שלום {customer_name}, התפנה תור ברגע האחרון ב-{business_name}!\n"
            f"שירות: {service_name}{price_str}\n"
            f"מועד: {start_time_formatted}\n"
            f"לתפיסת התור (כל הקודם זוכה): {claim_url}"
        )

        record = SentMessage(
            message_sid=message_sid,
            phone_number=phone_number,
            customer_name=customer_name,
            business_name=business_name,
            service_name=service_name,
            start_time_formatted=start_time_formatted,
            claim_url=claim_url,
            body=body,
        )

        self.sent_messages.append(record)
        self._by_sid[message_sid] = record

        logger.info(
            f"[WhatsApp Alert Sent] SID={message_sid} To={phone_number} Customer={customer_name} "
            f"Link={claim_url}"
        )

        return message_sid

    async def send_text_message(self, to_phone: str, text: str) -> str:
        """Simulate sending a direct text message."""
        message_sid = f"mock_txt_{uuid.uuid4().hex[:12]}"
        record = SentMessage(
            message_sid=message_sid,
            phone_number=to_phone,
            customer_name="",
            business_name="",
            service_name="",
            start_time_formatted="",
            claim_url="",
            body=text,
        )
        self.sent_messages.append(record)
        self._by_sid[message_sid] = record

        logger.info(f"[WhatsApp Text Sent] SID={message_sid} To={to_phone} Body={text[:40]}...")
        return message_sid

    def clear(self) -> None:
        """Clear recorded messages (used between test runs)."""
        self.sent_messages.clear()
        self._by_sid.clear()


# Global default instance
_default_provider: Optional[BaseMessageProvider] = None


def get_message_provider() -> BaseMessageProvider:
    """Get the active message provider instance (defaults to MockMessageProvider)."""
    global _default_provider
    if _default_provider is None:
        _default_provider = MockMessageProvider()
    return _default_provider


def set_message_provider(provider: BaseMessageProvider) -> None:
    """Override the active message provider (useful for tests or custom integrations)."""
    global _default_provider
    _default_provider = provider
