"""Shared offline comparison keys for observed and manually entered coordinates."""

import re
import unicodedata

from email_validator import validate_email
import phonenumbers


def normalize_contact_coordinate(kind: str, value: str, *, country: str | None = None,
                                 platform: str | None = None) -> str:
    if kind == "email":
        return validate_email(value.strip(), check_deliverability=False).normalized.casefold()
    if kind == "phone":
        try:
            number = phonenumbers.parse(value, country if country in phonenumbers.SUPPORTED_REGIONS else None)
        except phonenumbers.NumberParseException as exc:
            raise ValueError("Not a telephone number.") from exc
        if not phonenumbers.is_possible_number(number):
            raise ValueError("Not a possible telephone number.")
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164) + (
            f";ext={number.extension}" if number.extension else "")
    if kind == "postal_address":
        return " ".join(re.sub(r"[,;\n]+", " ", unicodedata.normalize("NFKC", value).casefold()).split()).rstrip(".")
    if kind == "instant_messaging":
        if platform == "telegram":
            return value.lstrip("@").casefold()
        if platform in {"whatsapp", "signal"} and re.fullmatch(r"\+?\d[\d ().\-]*\d", value):
            return normalize_contact_coordinate("phone", value if value.startswith(("+", "0")) else "+" + value,
                country=country)
        return value
    raise ValueError("Unsupported contact coordinate type.")
