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
    Factory function returning WhatsAppCloudAPIClient if effective provider is 'meta'
    and credentials are set, otherwise returning MockMessageProvider for testing and local dev.
    """
    global _active_provider
    if _active_provider is not None:
        return _active_provider

    effective_prov = settings.effective_whatsapp_provider
    token = settings.whatsapp_access_token_value
    phone_id = settings.whatsapp_phone_number_id_value

    if (
        effective_prov == "meta"
        and token
        and phone_id
    ):
        logger.info(
            f"Initializing live WhatsAppCloudAPIClient (phone_number_id={phone_id}, "
            f"api_version={settings.WHATSAPP_API_VERSION})."
        )
        _active_provider = WhatsAppCloudAPIClient(
            api_token=token,
            phone_number_id=phone_id,
            api_version=settings.WHATSAPP_API_VERSION,
        )
    else:
        logger.info(
            f"Using MockMessageProvider (effective_provider='{effective_prov}', "
            f"WHATSAPP_PROVIDER='{settings.WHATSAPP_PROVIDER}', is_production={settings.is_production})."
        )
        _active_provider = get_mock_provider()

    return _active_provider


def override_provider_instance(provider: BaseMessageProvider | None) -> None:
    """Explicitly set active provider for testing or custom runtime overrides."""
    global _active_provider
    _active_provider = provider


def reset_provider_instance() -> None:
    """Reset the cached provider singleton so it can be dynamically re-evaluated."""
    global _active_provider
    _active_provider = None
