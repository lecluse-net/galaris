from __future__ import annotations

import hashlib
import hmac

from bridge.whatsapp.messenger import whatsapp_to_message
from bridge.whatsapp.router import verify_signature
from bridge.whatsapp.schemas import WhatsAppConnectionConfig, normalize_phone


def test_signature_is_verified_over_raw_body() -> None:
    raw = b'{"object":"whatsapp_business_account"}'
    secret = "app-secret"
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    assert verify_signature(raw, signature, secret)
    assert not verify_signature(raw + b" ", signature, secret)
    assert not verify_signature(raw, "", secret)


def test_cloud_audio_maps_to_lazy_canonical_attachment() -> None:
    message = whatsapp_to_message(
        {
            "id": "wamid.1",
            "from": "+33 6 12 34 56 78",
            "timestamp": "123",
            "type": "audio",
            "audio": {"id": "media-1", "mime_type": "audio/ogg", "voice": True},
            "context": {"id": "wamid.parent"},
        },
        contacts={"33612345678": "Alice"},
        phone_number_id="phone-id",
        tool_id=4,
        connection_id=9,
    )

    assert message is not None
    assert message.id == "wamid.1"
    assert message.room is not None and message.room.id == "33612345678"
    assert message.attachments[0].kind == "audio"
    assert message.reply_to == "wamid.parent"
    assert message.recipient is not None and message.recipient.connection_id == 9


def test_phone_allowlist_is_restrictive_by_default() -> None:
    empty = WhatsAppConnectionConfig(access_token="token", phone_number_id="id")
    allowed = WhatsAppConnectionConfig(
        access_token="token",
        phone_number_id="id",
        allowed_phone_numbers="+33 612345678, +1-202-555-0100",
    )
    assert not empty.allowed_phones
    assert normalize_phone("+33 612 345 678") in allowed.allowed_phones
