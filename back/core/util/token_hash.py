"""
SHA-256 hashing helpers for user tokens.

The hash allows database token lookup without storing the clear-text value.
"""

import hashlib
from typing import Optional


def hash_token(token_value: str) -> str:
    """
    Compute the SHA-256 hash of a token.

    Args:
        token_value: Clear-text token value.

    Returns:
        The 64-character hexadecimal SHA-256 hash.
    """
    return hashlib.sha256(token_value.encode()).hexdigest()


def hash_token_or_none(token_value: Optional[str]) -> Optional[str]:
    """
    Hash a token when provided, otherwise return ``None``.
    """
    if not token_value:
        return None
    return hash_token(token_value)
