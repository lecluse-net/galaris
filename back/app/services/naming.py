"""Reserve the product name for its software-owned Service."""

from unicodedata import normalize


def validate_custom_service_name(value: str) -> str:
    if "galaris" in normalize("NFKC", value).casefold():
        raise ValueError("Galaris is reserved for the built-in Galaris Service")
    return value
