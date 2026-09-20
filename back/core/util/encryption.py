"""
Encryption service for sensitive values.
Use symmetric Fernet encryption for sensitive values.
"""

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
from collections.abc import Mapping
from typing import Optional

from core import settings


SECRET_MASK = "********"


class EncryptionService:
    """Encrypt sensitive values such as passwords."""

    _instance: Optional["EncryptionService"] = None
    _fernet: Optional[Fernet] = None

    def __new__(cls) -> "EncryptionService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._fernet is None:
            self._init_fernet()

    def _init_fernet(self) -> None:
        """Initialize Fernet with the master key."""
        master_key = getattr(settings, "ENCRYPTION_MASTER_KEY", None)

        if not master_key:
            raise ValueError(
                "ENCRYPTION_MASTER_KEY is not configured. Generate it with: "
                "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )

        # Use an existing base64 Fernet key directly; otherwise derive one.
        try:
            # Decode a base64 Fernet key (32 bytes plus padding, 44 characters).
            key_bytes = master_key.encode()
            # Validate the Fernet key.
            self._fernet = Fernet(key_bytes)
        except Exception:
            # Derive a deterministic Fernet key from an arbitrary secret.
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"genial_encryption_salt_v1",  # Fixed salt for deterministic derivation.
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
            self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        """
        Encrypt a sensitive value.

        Args:
            value: Value to encrypt.

        Returns:
            The base64-encrypted value.
        """
        if not value:
            return value
        assert self._fernet is not None  # Guaranteed by _init_fernet, which otherwise raises.
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, encrypted_value: str) -> str:
        """
        Decrypt an encrypted value.

        Args:
            encrypted_value: Base64-encrypted value.

        Returns:
            The decrypted value.
        """
        if not encrypted_value:
            return encrypted_value
        assert self._fernet is not None  # Guaranteed by _init_fernet, which otherwise raises.
        return self._fernet.decrypt(encrypted_value.encode()).decode()

    def is_encrypted(self, value: str) -> bool:
        """
        Check whether a value is an authenticated token for the current key.

        Args:
            value: Value to inspect.

        Returns:
            Whether the value can be decrypted with the configured key.
        """
        if not value:
            return False
        assert self._fernet is not None  # Guaranteed by _init_fernet, which otherwise raises.
        try:
            self._fernet.decrypt(value.encode())
            return True
        except (InvalidToken, ValueError, TypeError):
            return False


def get_encryption_service() -> EncryptionService:
    """Return the shared encryption service."""
    return EncryptionService()


def encrypt_value(value: str) -> str:
    """Encrypt a value with the shared encryption service."""
    return get_encryption_service().encrypt(value)


def decrypt_value(encrypted_value: str) -> str:
    """Decrypt a value with the shared encryption service."""
    return get_encryption_service().decrypt(encrypted_value)


def encrypt_mapping_values(values: Mapping[str, str]) -> dict[str, str]:
    """Encrypt every non-empty mapping value while preserving encrypted rows.

    String maps back both tool environment variables and Hermes ``data/.env``
    overrides. Encrypting every value avoids relying on secret-looking key names.
    """
    encryption = get_encryption_service()
    return {
        str(key): (
            value
            if not value or encryption.is_encrypted(value)
            else encryption.encrypt(value)
        )
        for key, value in values.items()
    }


def decrypt_mapping_values(values: Mapping[str, str]) -> dict[str, str]:
    """Decrypt encrypted mapping values and preserve legacy plaintext values."""
    encryption = get_encryption_service()
    return {
        str(key): (
            encryption.decrypt(value)
            if value and encryption.is_encrypted(value)
            else value
        )
        for key, value in values.items()
    }


def mask_mapping_values(values: Mapping[str, str]) -> dict[str, str]:
    """Expose configured keys without returning any associated value."""
    return {str(key): SECRET_MASK for key in values}
