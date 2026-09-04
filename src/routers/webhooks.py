import json
import logging
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config.settings import get_settings
from src.database.connection import get_db
from src.models.broadcast_log import BroadcastLog
from src.models.customer import Customer
from src.models.preference import CustomerPreference
from src.models.slot import Slot
from src.services.messaging.factory import get_configured_message_provider
from src.services.messaging.whatsapp.parser import (
    parse_webhook_events,
    verify_webhook_signature,
)
from src.services.messaging.whatsapp.templates import (
    build_lost_race_message,
    build_optout_message,
    build_winner_message,
)
from src.services.notification_service import notify_business_owner_on_claim
from src.services.slot_service import claim_slot_atomic

logger = logging.getLogger("slotalert.webhooks")
settings = get_settings()

router = APIRouter(prefix="/webhooks/whatsapp", tags=["Webhooks"])


@router.get(
    "",
    summary="Meta Webhook Verification Handshake",
    description="Responds to Meta's GET handshake challenge to verify the webhook URL.",
)
async def verify_webhook_handshake(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    """Validate webhook verification token with Meta and return challenge string."""
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("Meta Webhook verification handshake successful.")
        return PlainTextResponse(content=hub_challenge, status_code=status.HTTP_200_OK)

    logger.warning("Meta Webhook verification handshake failed (invalid verify token).")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification token mismatch",
    )


@router.post(
    "",
    summary="Process Meta WhatsApp Webhook events",
    description="Handles delivery status updates, interactive button replies (Claim, Opt-out), and keywords.",
)
async def handle_whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Handle incoming messages, interactive clicks, and delivery receipts from WhatsApp."""
    # 1. Read raw body and verify signature if configured
    body_bytes = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256")

    if settings.WHATSAPP_APP_SECRET:
        if not verify_webhook_signature(body_bytes, signature_header, settings.WHATSAPP_APP_SECRET):
            logger.warning("Invalid X-Hub-Signature-256 signature received.")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid signature",
            )

    try:
        payload: Dict[str, Any] = json.loads(body_bytes)
    except json.JSONDecodeError:
        return JSONResponse(status_code=200, content={"status": "invalid_json_ignored"})

    # 2. Parse status updates and user actions
    status_updates, user_actions = parse_webhook_events(payload)
    provider = get_configured_message_provider()

    # 3. Process Delivery Status Updates (sent, delivered, read, failed)
    for st in status_updates:
        if st.message_sid:
            stmt = (
                update(BroadcastLog)
                .where(BroadcastLog.message_sid == st.message_sid)
                .values(delivery_status=st.status.upper())
            )
            await db.execute(stmt)
            logger.info(f"Updated delivery status: SID={st.message_sid} Status={st.status}")
    if status_updates:
        await db.commit()

    # 4. Process Incoming User Actions
    for action in user_actions:
        # A) Claim button click: claim:slot:{slot_id}:cust:{customer_id}
        if action.action_type == "claim" and action.slot_id and action.customer_id:
            logger.info(f"Processing webhook claim: slot={action.slot_id}, cust={action.customer_id}")

            # Fetch customer & slot details for notifications
            cust_stmt = (
                select(Customer)
                .options(selectinload(Customer.business))
                .where(Customer.id == action.customer_id)
            )
            cust_res = await db.execute(cust_stmt)
            customer = cust_res.scalar_one_or_none()

            slot_stmt = (
                select(Slot)
                .options(selectinload(Slot.service), selectinload(Slot.business))
                .where(Slot.id == action.slot_id)
            )
            slot_res = await db.execute(slot_stmt)
            slot = slot_res.scalar_one_or_none()

            if not customer or not slot:
                logger.warning(f"Claim event for missing entities: slot={action.slot_id}, cust={action.customer_id}")
                continue

            # Execute atomic conditional claim engine
            claim_result = await claim_slot_atomic(
                db=db,
                slot_id=action.slot_id,
                customer_id=action.customer_id,
            )

            start_formatted = slot.start_time.strftime("%d/%m/%Y בשעה %H:%M")

            if claim_result.success:
                # Dispatches immediate winner message to customer
                winner_text = build_winner_message(
                    customer_name=customer.full_name,
                    service_name=slot.service.name,
                    business_name=slot.business.name,
                    start_time_formatted=start_formatted,
                )
                await provider.send_text_message(customer.phone_number, winner_text)
                logger.info(f"Winner notification dispatched to {customer.phone_number}")

                # Dispatches immediate alert to business owner
                await notify_business_owner_on_claim(
                    db=db,
                    slot_id=action.slot_id,
                    customer_id=action.customer_id,
                )
            else:
                # Dispatches immediate lost race message
                lost_text = build_lost_race_message(customer_name=customer.full_name)
                await provider.send_text_message(customer.phone_number, lost_text)
                logger.info(f"Lost race notification dispatched to {customer.phone_number}")

        # B) Opt-out Action (Button click or text keywords 'הסר' / 'STOP' / 'ביטול')
        elif action.action_type == "optout":
            customer = None
            if action.customer_id:
                cust_stmt = (
                    select(Customer)
                    .options(selectinload(Customer.business))
                    .where(Customer.id == action.customer_id)
                )
                cust_res = await db.execute(cust_stmt)
                customer = cust_res.scalar_one_or_none()
            elif action.from_phone:
                # Find by phone number
                clean_phone = action.from_phone.replace("+", "")
                cust_stmt = (
                    select(Customer)
                    .options(selectinload(Customer.business))
                    .where(Customer.phone_number.like(f"%{clean_phone}%"))
                )
                cust_res = await db.execute(cust_stmt)
                customer = cust_res.scalar_one_or_none()

            if customer:
                # Remove all preferences for this customer
                del_stmt = delete(CustomerPreference).where(CustomerPreference.customer_id == customer.id)
                await db.execute(del_stmt)
                await db.commit()

                biz_name = customer.business.name if customer.business else "העסק"
                optout_msg = build_optout_message(biz_name)
                await provider.send_text_message(customer.phone_number, optout_msg)
                logger.info(f"Customer {customer.id} ({customer.phone_number}) successfully opted out.")

    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})
