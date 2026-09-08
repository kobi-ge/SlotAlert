import logging
from src.config.settings import get_settings
from src.services.messaging.base import BaseMessageProvider
from src.services.messaging.mock_provider import get_message_provider as get_mock_provider
from src.services.messaging.whatsapp.client import WhatsAppCloudAPIClient

logger = logging.getLogger("slotalert.messaging.factory")
settings = get_settings()

_active_provider: BaseMessageProvider | None = None


def get_configured_message_provider() -> BaseMessageProvider:
    """
    Factory function returning WhatsAppCloudAPIClient if WHATSAPP_PROVIDER == 'meta'
    and credentials are set, otherwise returning MockMessageProvider for testing and local dev.
    """
    global _active_provider
    if _active_provider is not None:
        return _active_provider

    if (
        settings.WHATSAPP_PROVIDER == "meta"
        and settings.whatsapp_access_token_value
        and settings.WHATSAPP_PHONE_NUMBER_ID
    ):
        logger.info("Initializing WhatsAppCloudAPIClient with Meta Cloud API credentials.")
        _active_provider = WhatsAppCloudAPIClient(
            api_token=settings.whatsapp_access_token_value,
            phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID,
            api_version=settings.WHATSAPP_API_VERSION,
        )
    else:
        logger.info(f"Using MockMessageProvider (WHATSAPP_PROVIDER='{settings.WHATSAPP_PROVIDER}').")
        _active_provider = get_mock_provider()

    return _active_provider


def override_provider_instance(provider: BaseMessageProvider | None) -> None:
    """Explicitly set active provider for testing or custom runtime overrides."""
    global _active_provider
    _active_provider = provider
