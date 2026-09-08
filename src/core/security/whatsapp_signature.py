import hashlib
import hmac
import logging
from typing import Optional
from fastapi import Header, HTTPException, Request, status

from src.config.settings import get_settings

logger = logging.getLogger("slotalert.security.whatsapp")
settings = get_settings()


async def verify_whatsapp_signature(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
) -> bytes:
    """
    FastAPI security dependency to validate Meta X-Hub-Signature-256.
    Reads request raw body bytes, caches on request.state.raw_body, and verifies HMAC-SHA256.
    If in development and secret is not configured, safely bypasses verification.
    Raises HTTP 403 Forbidden on invalid or missing signature when secret is configured.
    Returns the raw body bytes.
    """
    body_bytes = await request.body()
    request.state.raw_body = body_bytes

    app_secret = settings.whatsapp_app_secret_value

    # Safe bypass for local development without credentials configured
    if not app_secret:
        if settings.APP_ENV in ("development", "test"):
            logger.debug("WhatsApp signature verification skipped (no secret in development/test).")
            return body_bytes
        logger.error("WHATSAPP_APP_SECRET is not configured in non-development environment!")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server security configuration error",
        )

    if not x_hub_signature_256:
        logger.warning("Missing X-Hub-Signature-256 header on WhatsApp webhook request.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing signature header",
        )

    expected_prefix = "sha256="
    if not x_hub_signature_256.startswith(expected_prefix):
        logger.warning(f"Malformed X-Hub-Signature-256 header: '{x_hub_signature_256}'")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Malformed signature header",
        )

    actual_sig = x_hub_signature_256[len(expected_prefix):]
    expected_sig = hmac.new(
        app_secret.encode("utf-8"),
        msg=body_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(actual_sig, expected_sig):
        logger.warning("Invalid X-Hub-Signature-256 signature received from Meta.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature",
        )

    return body_bytes
