import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from src.config.settings import get_settings


def clean_claim_token(claim_token: Optional[str] = None, claim_url: Optional[str] = None) -> str:
    """
    Sanitize and extract claim token or dynamic URL suffix for Meta WhatsApp CTA URL buttons.

    - Strips leading/trailing whitespace and line breaks.
    - Strips leading/trailing slashes to prevent malformed double slashes in template concatenation.
    - Extracts token from claim_url if claim_token is not directly provided.
    - Removes internal whitespace that would cause Meta Graph API parameter rejection.
    """
    token = ""
    if claim_token is not None:
        token = str(claim_token).strip()

    if not token and claim_url is not None:
        url_str = str(claim_url).strip()
        if "://" in url_str:
            try:
                parsed = urlparse(url_str)
                path = parsed.path.rstrip("/")
                if "/claim/" in path:
                    token = path.split("/claim/")[-1]
                elif "/slots/" in path and path.endswith("/claim"):
                    parts = [p for p in path.split("/") if p]
                    slot_idx = parts.index("slots")
                    if slot_idx + 1 < len(parts):
                        token = parts[slot_idx + 1]
                elif parsed.path:
                    token = parsed.path.lstrip("/")

                if parsed.query and token:
                    token = f"{token}?{parsed.query}"
            except Exception:
                token = url_str
        else:
            token = url_str

    # Clean whitespace and leading/trailing slashes
    token = token.strip().strip("/")
    token = re.sub(r"\s+", "", token)

    return token or "claim"


def build_slot_alert_template_payload(
    to_phone: str,
    customer_name: str = "",
    business_name: str = "",
    slot_datetime_str: str = "",
    service_name: str = "",
    claim_token: str = "",
    template_name: Optional[str] = None,
    language_code: Optional[str] = None,
    *,
    customer_id: Optional[int] = None,
    slot_id: Optional[int] = None,
    start_time_formatted: Optional[str] = None,
    claim_url: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Build official Meta WhatsApp Cloud API pre-approved Template payload using CTA URL Button.

    Components:
    - Body variables (4 parameters):
      {{1}}: Customer full name
      {{2}}: Business name
      {{3}}: Formatted slot date & time
      {{4}}: Service name
    - Button 0: URL CTA button (index: "0", sub_type: "url")
      {{1}}: Dynamic claim token / path suffix appended to template base URL
    """
    settings = get_settings()

    # Backward compatibility for legacy positional signature:
    # (to_phone, customer_id, customer_name, business_name, service_name, start_time_formatted, slot_id, ...)
    if isinstance(customer_name, int):
        actual_customer_name = str(business_name)
        actual_business_name = str(slot_datetime_str)
        actual_service_name = str(service_name)
        actual_datetime = str(claim_token)
        actual_slot_id = template_name if isinstance(template_name, int) else slot_id
        actual_tpl_name = (
            language_code
            if isinstance(language_code, str) and language_code not in ("he", "en")
            else None
        )

        customer_name = actual_customer_name
        business_name = actual_business_name
        slot_datetime_str = actual_datetime
        service_name = actual_service_name
        slot_id = actual_slot_id
        template_name = actual_tpl_name

    tpl_name = template_name or settings.WHATSAPP_SLOT_TEMPLATE_NAME
    tpl_lang = language_code or settings.WHATSAPP_SLOT_TEMPLATE_LANG

    datetime_display = slot_datetime_str or start_time_formatted or ""
    resolved_token = clean_claim_token(
        claim_token=claim_token or (str(slot_id) if slot_id else None),
        claim_url=claim_url,
    )

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": tpl_name,
            "language": {
                "code": tpl_lang,
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": customer_name},
                        {"type": "text", "text": business_name},
                        {"type": "text", "text": datetime_display},
                        {"type": "text", "text": service_name},
                    ],
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [
                        {
                            "type": "text",
                            "text": resolved_token,
                        }
                    ],
                },
            ],
        },
    }


def build_slot_offer_interactive_payload(
    to_phone: str,
    customer_id: int,
    customer_name: str,
    business_name: str,
    service_name: str,
    start_time_formatted: str,
    slot_id: int,
    claim_url: str,
) -> Dict[str, Any]:
    """
    Build Meta WhatsApp Cloud API JSON payload for an interactive button message:
    Button 1: 'אני רוצה את התור!' (claim:slot:{slot_id}:cust:{customer_id})
    Button 2: 'הסר אותי' (optout:cust:{customer_id})
    """
    body_text = (
        f"שלום {customer_name}! התפנה תור ברגע האחרון ב-{business_name} 🌟\n\n"
        f"💅 שירות: {service_name}\n"
        f"📅 מועד: {start_time_formatted}\n\n"
        f"התור פנוי על בסיס כל הקודם זוכה. לחצו על הכפתור מטה כדי לתפוס אותו מיד:"
    )

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": body_text
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"claim:slot:{slot_id}:cust:{customer_id}",
                            "title": "אני רוצה את התור! 🎉",
                        },
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"optout:cust:{customer_id}",
                            "title": "הסר אותי",
                        },
                    },
                ]
            },
        },
    }


def build_winner_message(
    customer_name: str,
    service_name: str,
    business_name: str,
    start_time_formatted: str,
) -> str:
    """Feedback message sent immediately when customer wins the slot."""
    return f"מצוין {customer_name}! התור נקבע בהצלחה ל-{service_name} ב-{business_name} בתאריך {start_time_formatted}. נתראה!"


def build_lost_race_message(customer_name: str) -> str:
    """Feedback message sent immediately when customer clicks but slot is already taken."""
    return f"אופס {customer_name}, מישהו הקדים אותך בכמה שניות והתור נתפס. נעדכן אותך מיד בביטול הבא!"


def build_optout_message(business_name: str = "העסק") -> str:
    """Confirmation message sent when customer unsubscribes from waitlist alerts."""
    return f"הוסרת בהצלחה מרשימת ההמתנה של {business_name}. לא יישלחו אליך התראות נוספות."
