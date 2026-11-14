"""Reserve the product name for its software-owned Tool."""

from unicodedata import normalize


def validate_custom_tool_name(value: str) -> str:
    if "galaris" in normalize("NFKC", value).casefold():
        raise ValueError("Galaris is reserved for the built-in Galaris Tool")
    return value
