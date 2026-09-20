"""Persistent VAPID identity, initialized once and never rotated by preferences."""

import base64
from dataclasses import dataclass, field
import hmac
import json
from typing import cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


@dataclass(frozen=True)
class VapidKeyPair:
    public_key: str
    private_key: str = field(repr=False)


_keys: VapidKeyPair | None = None


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def create_vapid_keys() -> VapidKeyPair:
    """Generate a fresh identity without consulting deployment configuration."""
    key = ec.generate_private_key(ec.SECP256R1())
    return VapidKeyPair(
        public_key=_encode(key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
        )),
        private_key=_encode(key.private_numbers().private_value.to_bytes(32, "big")),
    )


def _validate_vapid_keys(private_key: str, public_key: str) -> VapidKeyPair:
    """Validate a stored pair without ever generating a replacement."""
    private_key, public_key = private_key.strip(), public_key.strip()
    try:
        if private_key:
            raw = _decode(private_key.replace("\n", ""))
            if len(raw) == 32:
                key = ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
            else:
                parsed = serialization.load_der_private_key(raw, password=None)
                if not isinstance(parsed, ec.EllipticCurvePrivateKey) or not isinstance(parsed.curve, ec.SECP256R1):
                    raise ValueError("Invalid VAPID curve")
                key = parsed
        else:
            raise ValueError("Missing stored private key")
        public_bytes = key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
        )
        if not public_key or not hmac.compare_digest(_decode(public_key), public_bytes):
            raise ValueError("Mismatched VAPID keys")
        return VapidKeyPair(public_key=public_key, private_key=private_key)
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("The Web Push VAPID key pair is incomplete or invalid; existing keys were preserved") from None


def serialize_vapid_keys(keys: VapidKeyPair) -> str:
    return json.dumps({"public_key": keys.public_key, "private_key": keys.private_key})


def deserialize_vapid_keys(value: str) -> VapidKeyPair:
    try:
        data: object = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError("Invalid VAPID data")
        fields = cast(dict[str, object], data)
        private, public = fields.get("private_key"), fields.get("public_key")
        if not isinstance(private, str) or not private or not isinstance(public, str) or not public:
            raise ValueError("Missing persisted VAPID keys")
        return _validate_vapid_keys(private, public)
    except (ValueError, TypeError):
        raise ValueError("The stored Web Push identity is invalid; it must not be regenerated") from None


def load_web_push_keys(value: str) -> None:
    global _keys
    _keys = deserialize_vapid_keys(value)


def web_push_keys() -> VapidKeyPair | None:
    """Return the startup snapshot; only the public key is sent to subscribers."""
    return _keys
