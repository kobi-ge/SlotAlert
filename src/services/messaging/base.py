from abc import ABC, abstractmethod


class BaseMessageProvider(ABC):
    """Abstract interface for external WhatsApp/SMS notification providers."""

    @abstractmethod
    async def send_slot_alert(
        self,
        phone_number: str,
        customer_name: str,
        business_name: str,
        service_name: str,
        start_time_formatted: str,
        claim_url: str,
        price: object = None,
    ) -> str:
        """
        Dispatch a last-minute slot cancellation alert message to a customer.

        :param phone_number: Customer WhatsApp phone number
        :param customer_name: Full name of the customer
        :param business_name: Name of the clinic/salon
        :param service_name: Name of the service offered
        :param start_time_formatted: Human-readable appointment start time
        :param claim_url: Direct link to claim the slot (FCFS)
        :return: External message identifier (message_sid)
        """
        pass

    @abstractmethod
    async def send_text_message(self, to_phone: str, text: str) -> str:
        """
        Send a direct follow-up text notification to a phone number.

        :param to_phone: Recipient phone number
        :param text: Message body
        :return: External message identifier (message_sid)
        """
        pass
