from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.messenger import journal
from bridge.whatsapp.messenger import WhatsAppMessenger, WhatsAppServiceWindowError
from bridge.whatsapp.schemas import WhatsAppConnectionConfig


def _messenger(*, template: str = "") -> tuple[WhatsAppMessenger, SimpleNamespace]:
    client = SimpleNamespace(
        send_text=AsyncMock(
            return_value={"messages": [{"id": "wamid.text", "message_status": "accepted"}]}
        ),
        send_template=AsyncMock(
            return_value={
                "messages": [{"id": "wamid.template", "message_status": "accepted"}]
            }
        ),
    )
    config = WhatsAppConnectionConfig(
        access_token="token",
        phone_number_id="phone-id",
        allowed_phone_numbers="33612345678",
        template_name=template,
        template_language="fr",
    )
    return (
        WhatsAppMessenger(
            client=client,  # type: ignore[arg-type]
            config=config,
            tool_id=3,
            connection_id=7,
        ),
        client,
    )


@pytest.mark.asyncio
async def test_free_text_is_used_inside_service_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messenger, client = _messenger()
    monkeypatch.setattr(
        journal,
        "latest_inbound_at",
        AsyncMock(return_value=datetime.now(timezone.utc)),
    )
    persisted = AsyncMock(return_value=True)
    monkeypatch.setattr(journal, "persist_outbound", persisted)

    result = await messenger.send_to_room("+33 6 12 34 56 78", "Bonjour")

    assert result.id == "wamid.text"
    client.send_text.assert_awaited_once_with("33612345678", "Bonjour", reply_to=None)
    client.send_template.assert_not_awaited()
    persisted.assert_awaited_once()


@pytest.mark.asyncio
async def test_approved_template_is_used_outside_service_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messenger, client = _messenger(template="proactive_message")
    monkeypatch.setattr(journal, "latest_inbound_at", AsyncMock(return_value=None))
    monkeypatch.setattr(journal, "persist_outbound", AsyncMock(return_value=True))

    result = await messenger.send_to_room("33612345678", "Rappel")

    assert result.id == "wamid.template"
    client.send_template.assert_awaited_once_with(
        "33612345678",
        name="proactive_message",
        language="fr",
        text_parameter="Rappel",
    )


@pytest.mark.asyncio
async def test_missing_template_fails_explicitly_outside_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messenger, _client = _messenger()
    monkeypatch.setattr(journal, "latest_inbound_at", AsyncMock(return_value=None))

    with pytest.raises(WhatsAppServiceWindowError, match="24 hours"):
        await messenger.send_to_room("33612345678", "Rappel")


@pytest.mark.asyncio
async def test_outbound_number_must_be_allowlisted() -> None:
    messenger, _client = _messenger()
    with pytest.raises(ValueError, match="allow"):
        await messenger.send_to_room("12025550100", "Nope")
