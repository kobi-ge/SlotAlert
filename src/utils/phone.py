import re
from typing import List, Optional


def clean_e164_whatsapp(raw_phone: str, default_country_code: str = "972") -> str:
    """
    Sanitizes raw phone numbers into Meta WhatsApp Cloud API compliant pure E.164 digits.
    - Strips spaces, dashes, parentheses, dots, and leading '+'.
    - Automatically translates domestic Israeli numbers (e.g. '050-123-4567' -> '972501234567').
    - Handles international formats (e.g. '+972-50-123-4567' -> '972501234567').
    - Validates length: between 10 and 15 digits as per ITU-T E.164.

    :param raw_phone: The raw phone number input.
    :param default_country_code: Default international country prefix without '+' (default: '972').
    :return: Pure digit E.164 string without leading '+' (e.g., '972501234567').
    :raises ValueError: If the phone number is invalid or cannot be normalized.
    """
    if not raw_phone or not isinstance(raw_phone, str):
        raise ValueError("Phone number must be a non-empty string.")

    # Remove all non-digit characters except leading plus which we will strip next
    cleaned = re.sub(r"[^\d+]", "", raw_phone.strip())
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    # Domestic Israeli number conversion (e.g. 0501234567 -> 972501234567)
    if cleaned.startswith("05") and len(cleaned) == 10:
        cleaned = f"{default_country_code}{cleaned[1:]}"
    elif cleaned.startswith("0") and len(cleaned) in (9, 10):
        cleaned = f"{default_country_code}{cleaned[1:]}"

    # Verify digits only
    if not cleaned.isdigit():
        raise ValueError(f"Phone number '{raw_phone}' contains invalid characters.")

    # E.164 length check: 10 to 15 digits
    if len(cleaned) < 10 or len(cleaned) > 15:
        raise ValueError(
            f"Phone number '{raw_phone}' normalized to '{cleaned}' ({len(cleaned)} digits) "
            f"violates ITU-T E.164 length constraints (10-15 digits)."
        )

    return cleaned


def get_phone_search_variants(phone: str) -> List[str]:
    """
    Returns defensive query variants of a phone number (e.g. '972501234567', '+972501234567', '0501234567')
    to ensure backward-compatible zero-downtime database lookups against existing records.
    """
    variants = set()
    raw = phone.strip()
    variants.add(raw)

    try:
        clean = clean_e164_whatsapp(raw)
        variants.add(clean)
        variants.add(f"+{clean}")
        if clean.startswith("972") and len(clean) == 12:
            domestic = f"0{clean[3:]}"
            variants.add(domestic)
    except ValueError:
        # If it could not be parsed as E.164, still include sanitized digits
        digits = re.sub(r"\D", "", raw)
        if digits:
            variants.add(digits)
            variants.add(f"+{digits}")

    return list(variants)


def format_display_phone(phone: str) -> str:
    """Formats phone number into human-friendly format (e.g. 050-1234567)."""
    try:
        clean = clean_e164_whatsapp(phone)
        if clean.startswith("972") and len(clean) == 12:
            # 972 50 1234567 -> 050-1234567
            return f"0{clean[3:5]}-{clean[5:]}"
    except ValueError:
        pass
    return phone
