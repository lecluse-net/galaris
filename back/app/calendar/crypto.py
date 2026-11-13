"""Calendar encryption boundary; scheduling metadata alone stays indexable."""
import hashlib
from core.util import get_encryption_service


def encrypt(value: str) -> str:
    return get_encryption_service().encrypt(value)


def decrypt(value: str | None) -> str:
    if not value:
        return ""
    service = get_encryption_service()
    return service.decrypt(value) if service.is_encrypted(value) else value


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
