from src.services.messaging.base import BaseMessageProvider
from src.services.messaging.factory import (
    get_configured_message_provider,
    override_provider_instance,
    reset_provider_instance,
)
from src.services.messaging.mock_provider import (
    MockMessageProvider,
    SentMessage,
    get_message_provider as get_mock_provider,
    set_message_provider,
)
from src.services.messaging.spam_guard import (
    MAX_ALERTS_PER_24H,
    can_send_notification,
    increment_customer_alert_count,
)

# Canonical messaging provider resolver: dynamically returns configured or mock provider
get_message_provider = get_configured_message_provider

__all__ = [
    "BaseMessageProvider",
    "MockMessageProvider",
    "SentMessage",
    "get_message_provider",
    "get_configured_message_provider",
    "get_mock_provider",
    "override_provider_instance",
    "reset_provider_instance",
    "set_message_provider",
    "MAX_ALERTS_PER_24H",
    "can_send_notification",
    "increment_customer_alert_count",
]
