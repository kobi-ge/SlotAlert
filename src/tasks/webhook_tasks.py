import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.connection import AsyncSessionLocal, get_redis_client
from src.models.broadcast_log import BroadcastLog
from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.slot import Slot
from src.services.messaging.factory import get_configured_message_provider
from src.services.messaging.whatsapp.templates import (
    build_lost_race_message,
    build_optout_message,
    build_winner_message,
)
from src.services.notification_service import notify_business_owner_on_claim
from src.services.slot_service import claim_slot_atomic
from src.tasks.queue import task_queue
from src.utils.phone import clean_e164_whatsapp, get_phone_search_variants

logger = logging.getLogger("slotalert.tasks.webhook")


def parse_claim_payload(payload_str: str) -> tuple[Optional[int], Optional[int]]:
    """
    Parses claim payload supporting both formats:
    - 'claim:{slot_id}:{customer_id}'
    - 'claim:slot:{slot_id}:cust:{customer_id}'
    """
    parts = payload_str.split(":")
    try:
        if len(parts) == 3 and parts[0] == "claim":
            return int(parts[1]), int(parts[2])
        elif len(parts) >= 5 and parts[0] == "claim" and parts[1] == "slot":
            return int(parts[2]), int(parts[4])
    except Exception as exc:
        logger.warning(f"Failed parsing claim payload '{payload_str}': {exc}")
    return None, None


def parse_optout_payload(payload_str: str) -> tuple[Optional[int], Optional[str]]:
    """
    Parses optout payload supporting formats:
    - 'optout:{customer_id}'
    - 'optout:cust:{customer_id}'
    - 'optout:phone:{from_phone}'
    """
    parts = payload_str.split(":")
    try:
        if len(parts) == 2 and parts[0] == "optout" and parts[1].isdigit():
            return int(parts[1]), None
        elif len(parts) == 3 and parts[0] == "optout" and parts[1] == "cust":
            return int(parts[2]), None
        elif len(parts) >= 3 and parts[0] == "optout" and parts[1] == "phone":
            return None, parts[2]
    except Exception as exc:
        logger.warning(f"Failed parsing optout payload '{payload_str}': {exc}")
    return None, None


async def process_whatsapp_webhook_event(raw_payload: Dict[str, Any]) -> None:
    """
    Asynchronous worker task handling Meta WhatsApp Webhook events.
    1. Idempotency check on wamid using Redis 24-hour TTL
    2. Dual-payload parsing (Quick-Reply template buttons vs interactive session replies)
    3. Atomic slot claiming and winner / loser feedback dispatch
    4. Delivery status receipts (SENT -> DELIVERED -> READ -> FAILED)
    5. Mark-as-read receipt dispatch
    """
    provider = get_configured_message_provider()
    redis = get_redis_client()

    entries = raw_payload.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})

            # ------------------------------------------------------------------
            # 1. Process Delivery Status Receipts (statuses)
            # ------------------------------------------------------------------
            statuses = value.get("statuses", [])
            if statuses:
                async with AsyncSessionLocal() as session:
                    for st in statuses:
                        wamid = st.get("id", "")
                        status_str = st.get("status", "").upper()
                        if not wamid:
                            continue

                        update_values: Dict[str, Any] = {"delivery_status": status_str}
                        now_utc = datetime.now(timezone.utc)

                        if status_str == "DELIVERED":
                            update_values["delivered_at"] = now_utc
                        elif status_str == "READ":
                            update_values["read_at"] = now_utc
                        elif status_str == "FAILED":
                            errors = st.get("errors", [])
                            if errors:
                                err_obj = errors[0]
                                update_values["meta_error_code"] = err_obj.get("code")
                                update_values["failure_reason"] = (
                                    err_obj.get("message") or err_obj.get("title") or "Delivery Failed"
                                )[:255]

                        # Match on wamid or legacy message_sid
                        stmt = (
                            update(BroadcastLog)
                            .where(
                                (BroadcastLog.wamid == wamid) | (BroadcastLog.message_sid == wamid)
                            )
                            .values(**update_values)
                        )
                        result = await session.execute(stmt)
                        logger.info(
                            f"Delivery status update: wamid={wamid} status={status_str} "
                            f"rows_affected={result.rowcount}"
                        )
                    await session.commit()

            # ------------------------------------------------------------------
            # 2. Process Incoming Messages & Quick-Reply / Interactive Clicks
            # ------------------------------------------------------------------
            messages = value.get("messages", [])
            for msg in messages:
                wamid = msg.get("id", "")
                from_phone = msg.get("from", "")

                # Idempotency Guard via Redis (24h TTL)
                if wamid:
                    dedup_key = f"webhook:msg:{wamid}"
                    # set with nx=True returns True if set, None if already existed
                    is_new = await redis.set(dedup_key, "1", ex=86400, nx=True)
                    if not is_new:
                        logger.info(f"Duplicate webhook message event ignored: wamid={wamid}")
                        continue

                # Dismiss blue ticks (mark as read)
                if wamid and hasattr(provider, "mark_as_read"):
                    try:
                        await provider.mark_as_read(wamid)
                    except Exception as exc:
                        logger.debug(f"mark_as_read notice for {wamid}: {exc}")

                # Unified Action Extraction: Dual-Payload Parsing
                action_payload: Optional[str] = None
                btn = msg.get("button")
                interactive = msg.get("interactive")
                text_obj = msg.get("text")

                if btn and btn.get("payload"):
                    # Template Quick-Reply Button Reply
                    action_payload = btn.get("payload")
                elif interactive and interactive.get("button_reply"):
                    # Session Interactive Button Reply
                    action_payload = interactive["button_reply"].get("id")
                elif text_obj and text_obj.get("body"):
                    text_clean = text_obj.get("body", "").strip().lower()
                    if text_clean in ["הסר", "stop", "בטל", "הסרה", "unsubscribe"]:
                        action_payload = f"optout:phone:{from_phone}"

                if not action_payload:
                    logger.debug(f"Unhandled message type or no action payload in message {wamid}")
                    continue

                logger.info(f"Processing webhook action payload: '{action_payload}' from {from_phone}")

                # A) Handle Slot Claiming Action
                if action_payload.startswith("claim:"):
                    slot_id, customer_id = parse_claim_payload(action_payload)
                    if not slot_id or not customer_id:
                        logger.warning(f"Invalid claim payload components: '{action_payload}'")
                        continue

                    async with AsyncSessionLocal() as session:
                        # Load entities for notifications
                        cust_stmt = (
                            select(Customer)
                            .options(selectinload(Customer.business))
                            .where(Customer.id == customer_id)
                        )
                        cust_res = await session.execute(cust_stmt)
                        customer = cust_res.scalar_one_or_none()

                        slot_stmt = (
                            select(Slot)
                            .options(selectinload(Slot.service), selectinload(Slot.business))
                            .where(Slot.id == slot_id)
                        )
                        slot_res = await session.execute(slot_stmt)
                        slot = slot_res.scalar_one_or_none()

                        if not customer or not slot:
                            logger.warning(
                                f"Claim references non-existent entities: slot={slot_id}, cust={customer_id}"
                            )
                            continue

                        # Execute atomic conditional claim engine
                        claim_result = await claim_slot_atomic(
                            db=session,
                            slot_id=slot_id,
                            customer_id=customer_id,
                        )

                        start_formatted = slot.start_time.strftime("%d/%m/%Y בשעה %H:%M")

                        if claim_result.success:
                            # Send winner feedback within open 24h window
                            winner_text = build_winner_message(
                                customer_name=customer.full_name,
                                service_name=slot.service.name if slot.service else slot.effective_service_name,
                                business_name=slot.business.name,
                                start_time_formatted=start_formatted,
                            )
                            await provider.send_text_message(customer.phone_number, winner_text)
                            logger.info(f"Winner notification dispatched to {customer.phone_number}")

                            # Notify business owner
                            await notify_business_owner_on_claim(
                                db=session,
                                slot_id=slot_id,
                                customer_id=customer_id,
                            )
                        else:
                            # Send lost race feedback
                            lost_text = build_lost_race_message(customer_name=customer.full_name)
                            await provider.send_text_message(customer.phone_number, lost_text)
                            logger.info(f"Lost race notification dispatched to {customer.phone_number}")

                # B) Handle Opt-Out Action
                elif action_payload.startswith("optout:"):
                    customer_id, phone_str = parse_optout_payload(action_payload)
                    async with AsyncSessionLocal() as session:
                        customer = None
                        if customer_id:
                            cust_stmt = (
                                select(Customer)
                                .options(selectinload(Customer.business))
                                .where(Customer.id == customer_id)
                            )
                            cust_res = await session.execute(cust_stmt)
                            customer = cust_res.scalar_one_or_none()
                        elif phone_str or from_phone:
                            target_phone = phone_str or from_phone
                            variants = get_phone_search_variants(target_phone)
                            cust_stmt = (
                                select(Customer)
                                .options(selectinload(Customer.business))
                                .where(Customer.phone_number.in_(variants))
                            )
                            cust_res = await session.execute(cust_stmt)
                            customer = cust_res.scalar_one_or_none()

                        if customer:
                            del_stmt = delete(CustomerPreference).where(
                                CustomerPreference.customer_id == customer.id
                            )
                            await session.execute(del_stmt)
                            await session.commit()

                            biz_name = customer.business.name if customer.business else "העסק"
                            optout_msg = build_optout_message(biz_name)
                            await provider.send_text_message(customer.phone_number, optout_msg)
                            logger.info(
                                f"Customer {customer.id} ({customer.phone_number}) successfully opted out."
                            )


# Register task with global queue
task_queue.register_task("process_whatsapp_webhook_event", process_whatsapp_webhook_event)
