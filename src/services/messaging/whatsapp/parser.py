import hmac
import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("slotalert.whatsapp.parser")

OPTOUT_KEYWORDS = {"הסר", "stop", "ביטול", "הסרה", "unsubscribe"}


@dataclass
class DeliveryStatusUpdate:
    message_sid: str
    status: str
    recipient_id: str
    timestamp: Optional[str] = None


@dataclass
class IncomingUserAction:
    action_type: str  # "claim", "optout", "text"
    from_phone: str
    slot_id: Optional[int] = None
    customer_id: Optional[int] = None
    text_body: Optional[str] = None
    raw_payload: Optional[str] = None


def verify_webhook_signature(
    payload_bytes: bytes,
    signature_header: Optional[str],
    app_secret: Optional[str],
) -> bool:
    """
    Validate X-Hub-Signature-256 header using SHA256 HMAC against app secret.
    If app_secret is not set, verification is skipped.
    """
    if not app_secret or not signature_header:
        return True

    expected_prefix = "sha256="
    if not signature_header.startswith(expected_prefix):
        return False

    actual_sig = signature_header[len(expected_prefix):]
    expected_sig = hmac.new(
        app_secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(actual_sig, expected_sig)


def parse_webhook_events(payload: Dict[str, Any]) -> tuple[List[DeliveryStatusUpdate], List[IncomingUserAction]]:
    """
    Parse standard Meta WhatsApp Webhook payload into DeliveryStatusUpdate
    and IncomingUserAction domain structures.
    """
    status_updates: List[DeliveryStatusUpdate] = []
    user_actions: List[IncomingUserAction] = []

    entries = payload.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})

            # 1. Parse Status Updates (sent, delivered, read, failed)
            statuses = value.get("statuses", [])
            for st in statuses:
                status_updates.append(
                    DeliveryStatusUpdate(
                        message_sid=st.get("id", ""),
                        status=st.get("status", ""),
                        recipient_id=st.get("recipient_id", ""),
                        timestamp=st.get("timestamp"),
                    )
                )

            # 2. Parse Incoming Messages / Interactive Clicks
            messages = value.get("messages", [])
            for msg in messages:
                from_phone = msg.get("from", "")
                msg_type = msg.get("type", "")

                button_payload: Optional[str] = None

                # Interactive button reply
                if msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    button_reply = interactive.get("button_reply", {})
                    button_payload = button_reply.get("id")

                # Quick reply button
                elif msg_type == "button":
                    button = msg.get("button", {})
                    button_payload = button.get("payload")

                # Process button payload if present
                if button_payload:
                    if button_payload.startswith("claim:"):
                        try:
                            parts = button_payload.split(":")
                            if len(parts) == 3:  # claim:{slot_id}:{customer_id}
                                slot_id = int(parts[1])
                                customer_id = int(parts[2])
                            elif len(parts) >= 5 and parts[1] == "slot":  # claim:slot:{slot_id}:cust:{customer_id}
                                slot_id = int(parts[2])
                                customer_id = int(parts[4])
                            else:
                                slot_id = None
                                customer_id = None

                            if slot_id and customer_id:
                                user_actions.append(
                                    IncomingUserAction(
                                        action_type="claim",
                                        from_phone=from_phone,
                                        slot_id=slot_id,
                                        customer_id=customer_id,
                                        raw_payload=button_payload,
                                    )
                                )
                        except Exception as exc:
                            logger.error(f"Failed to parse claim payload '{button_payload}': {exc}")

                    elif button_payload.startswith("optout:"):
                        try:
                            parts = button_payload.split(":")
                            customer_id = None
                            if len(parts) == 2 and parts[1].isdigit():  # optout:{customer_id}
                                customer_id = int(parts[1])
                            elif len(parts) == 3 and parts[1] == "cust":  # optout:cust:{customer_id}
                                customer_id = int(parts[2])

                            user_actions.append(
                                IncomingUserAction(
                                    action_type="optout",
                                    from_phone=from_phone,
                                    customer_id=customer_id,
                                    raw_payload=button_payload,
                                )
                            )
                        except Exception as exc:
                            logger.error(f"Failed to parse optout payload '{button_payload}': {exc}")

                # Text Message keyword analysis ("הסר", "STOP", "ביטול")
                elif msg_type == "text":
                    text_obj = msg.get("text", {})
                    body = text_obj.get("body", "").strip()
                    clean_body = body.lower()

                    if clean_body in OPTOUT_KEYWORDS:
                        user_actions.append(
                            IncomingUserAction(
                                action_type="optout",
                                from_phone=from_phone,
                                text_body=body,
                                raw_payload=body,
                            )
                        )
                    else:
                        user_actions.append(
                            IncomingUserAction(
                                action_type="text",
                                from_phone=from_phone,
                                text_body=body,
                            )
                        )

    return status_updates, user_actions
