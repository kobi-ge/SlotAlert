from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ==============================================================================
# Outbound WhatsApp Cloud API Payload Schemas (Graph API v20.0+)
# ==============================================================================

class WhatsAppLanguage(BaseModel):
    """Language code object for Meta templates (e.g., 'he' for Hebrew)."""
    code: str = "he"


class WhatsAppTemplateParameter(BaseModel):
    """Single parameter inside a template component (text, currency, payload, etc.)."""
    type: Literal["text", "payload", "currency", "date_time"] = "text"
    text: Optional[str] = None
    payload: Optional[str] = None


class WhatsAppTemplateComponent(BaseModel):
    """Component of a Meta template: header, body, or quick_reply button."""
    type: Literal["header", "body", "button"]
    sub_type: Optional[Literal["quick_reply", "url"]] = None
    index: Optional[int] = None
    parameters: List[WhatsAppTemplateParameter] = Field(default_factory=list)


class WhatsAppTemplateBody(BaseModel):
    """Template identifier and parameter components payload."""
    name: str
    language: WhatsAppLanguage = Field(default_factory=WhatsAppLanguage)
    components: List[WhatsAppTemplateComponent] = Field(default_factory=list)


class WhatsAppTemplateMessagePayload(BaseModel):
    """
    Top-level payload for sending pre-approved WhatsApp Templates.
    Required for initiating conversations outside the 24-hour customer care window.
    """
    messaging_product: Literal["whatsapp"] = "whatsapp"
    recipient_type: Literal["individual"] = "individual"
    to: str
    type: Literal["template"] = "template"
    template: WhatsAppTemplateBody


class WhatsAppTextBody(BaseModel):
    """Body container for direct text messages."""
    body: str
    preview_url: bool = False


class WhatsAppTextMessagePayload(BaseModel):
    """
    Top-level payload for direct text replies within the 24-hour service window.
    """
    messaging_product: Literal["whatsapp"] = "whatsapp"
    recipient_type: Literal["individual"] = "individual"
    to: str
    type: Literal["text"] = "text"
    text: WhatsAppTextBody


class WhatsAppMarkReadPayload(BaseModel):
    """Payload to mark an inbound message as read (blue ticks)."""
    messaging_product: Literal["whatsapp"] = "whatsapp"
    status: Literal["read"] = "read"
    message_id: str


# ==============================================================================
# Inbound Webhook Event Schemas (Dual-Payload: Template & Interactive)
# ==============================================================================

class MetaErrorData(BaseModel):
    """Error descriptor returned by Meta in statuses or messages."""
    code: int
    title: Optional[str] = None
    message: Optional[str] = None
    error_data: Optional[Dict[str, Any]] = None


class MetaStatusItem(BaseModel):
    """Delivery status receipt (sent, delivered, read, failed)."""
    id: str = Field(..., description="The WhatsApp message ID (wamid)")
    status: Literal["sent", "delivered", "read", "failed"]
    timestamp: str
    recipient_id: str
    errors: Optional[List[MetaErrorData]] = None


class MetaButtonReply(BaseModel):
    """Quick-reply button reply clicked on a Template message."""
    payload: str
    text: Optional[str] = None


class MetaInteractiveButtonReply(BaseModel):
    """Interactive button reply clicked on a session Interactive message."""
    id: str
    title: Optional[str] = None


class MetaInteractive(BaseModel):
    """Interactive message container."""
    type: Optional[str] = None
    button_reply: Optional[MetaInteractiveButtonReply] = None


class MetaTextMessage(BaseModel):
    """Direct text message body."""
    body: str


class MetaMessageItem(BaseModel):
    """Inbound message or interaction event from a customer."""
    id: str = Field(..., description="Inbound WhatsApp message ID (wamid)")
    from_: str = Field(..., alias="from", description="Sender phone number in E.164 digits without +")
    timestamp: str
    type: str
    text: Optional[MetaTextMessage] = None
    button: Optional[MetaButtonReply] = None
    interactive: Optional[MetaInteractive] = None
    errors: Optional[List[MetaErrorData]] = None


class MetaMetadata(BaseModel):
    """Business phone number metadata received in the webhook."""
    display_phone_number: Optional[str] = None
    phone_number_id: str


class MetaContact(BaseModel):
    """Sender profile information."""
    profile: Optional[Dict[str, str]] = None
    wa_id: str


class MetaValue(BaseModel):
    """Value payload inside webhook change entry."""
    messaging_product: str = "whatsapp"
    metadata: MetaMetadata
    contacts: Optional[List[MetaContact]] = None
    messages: Optional[List[MetaMessageItem]] = None
    statuses: Optional[List[MetaStatusItem]] = None


class MetaChange(BaseModel):
    """Individual change item."""
    field: str
    value: MetaValue


class MetaEntry(BaseModel):
    """Entry wrapper containing changes."""
    id: str
    changes: List[MetaChange]


class WhatsAppWebhookPayload(BaseModel):
    """Complete root payload delivered by Meta Graph API webhooks."""
    object: Literal["whatsapp_business_account"] = "whatsapp_business_account"
    entry: List[MetaEntry]
