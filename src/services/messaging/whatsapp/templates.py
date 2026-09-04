from typing import Any, Dict


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
