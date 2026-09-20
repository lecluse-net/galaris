from contextlib import asynccontextmanager
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.file_share import MaterializedResource
from app.messenger import mcp as messenger_mcp
from app.tools.mcp_loader import McpToolContext


class _FakeMessenger:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_to_room(self, room_id: str, message: str) -> None:
        self.sent.append((room_id, message))


def test_send_file_to_user_requires_a_canonical_resource_uri() -> None:
    parameters = signature(messenger_mcp.mcp_send_file_to_user).parameters
    assert list(parameters)[:3] == ["ctx", "user_id", "resource_uri"]
    assert "filename" not in parameters


@pytest.mark.asyncio
async def test_goal_referrer_user_id_bypasses_provider_user_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Messenger(_FakeMessenger):
        async def search_users(self, query: str) -> list[object]:
            raise AssertionError("A pinned Goal recipient must stay exact")

    task_data = AsyncMock(return_value={"goal_referrer_user_id": "human-42"})
    monkeypatch.setattr(messenger_mcp, "_task_data", task_data)
    task_id = uuid4()

    user_id = await messenger_mcp._resolve_task_recipient_id(
        task_id,
        Messenger(),  # type: ignore[arg-type]
        "human-42",
        "en",
    )

    assert user_id == "human-42"
    task_data.assert_awaited_once_with(task_id)


@pytest.mark.asyncio
async def test_deliver_agent_file_does_not_send_message_when_transfer_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.file_share import resource_delivery

    messenger = _FakeMessenger()

    async def materialize(*args: Any, **kwargs: Any) -> MaterializedResource:
        raise RuntimeError("missing")

    monkeypatch.setattr(resource_delivery, "materialize_resource", materialize)

    result, delivered = await messenger_mcp._deliver_agent_file_with_status(
        McpToolContext(agent_id=7, runtime="internal"),
        messenger,
        "room-1",
        "missing.pdf",
        "Response delivered.",
        "en",
    )

    assert "could not be read" in result
    assert delivered is False
    assert messenger.sent == []


@pytest.mark.asyncio
async def test_deliver_agent_file_sends_message_after_successful_transfer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.file_share import resource_delivery

    events: list[str] = []

    class Messenger(_FakeMessenger):
        tool_code = "nextcloud"

        async def send_to_room(self, room_id: str, message: str) -> None:
            events.append(f"message:{message}")
            await super().send_to_room(room_id, message)

        async def upload_file_path(
            self, room_id: str, path: Path, name: str
        ) -> object:
            assert (room_id, name, path.read_bytes()) == (
                "room-1",
                "original-report.pdf",
                b"report-bytes",
            )
            events.append("transfer")
            attachment = SimpleNamespace(id="attachment-12", name=name)
            room = SimpleNamespace(external_id="provider-room")
            return SimpleNamespace(files=[attachment], room=room)

    async def materialize(
        _ctx: object,
        uri: object,
        destination: Path,
        *,
        max_bytes: int,
    ) -> MaterializedResource:
        assert uri == "console://reports/report.pdf"
        assert max_bytes > 0
        destination.write_bytes(b"report-bytes")
        return MaterializedResource(
            uri=str(uri),
            name="original-report.pdf",
            media_type="application/pdf",
            size=12,
        )

    messenger = Messenger()
    monkeypatch.setattr(resource_delivery, "materialize_resource", materialize)

    result, delivered = await messenger_mcp._deliver_agent_file_with_status(
        McpToolContext(agent_id=7, runtime="internal"),
        messenger,
        "room-1",
        "console://reports/report.pdf",
        "Response delivered.",
        "en",
    )

    assert result == {
        "message": (
            "File 'original-report.pdf' sent (12 bytes): "
            "nextcloud://provider-room/attachment-12"
        ),
        "source_uri": "console://reports/report.pdf",
        "uri": "nextcloud://provider-room/attachment-12",
        "name": "original-report.pdf",
        "size": 12,
    }
    assert delivered is True
    assert messenger.sent == [("room-1", "Response delivered.")]
    assert events == ["transfer", "message:Response delivered."]


@pytest.mark.asyncio
async def test_deliver_agent_audio_uploads_generated_mp3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm import tts_service

    uploads: list[tuple[str, str, bytes]] = []

    class Messenger(_FakeMessenger):
        async def upload_file_path(
            self, room_id: str, path: Path, name: str
        ) -> None:
            uploads.append((room_id, name, path.read_bytes()))

    async def generate_for_agent(
        agent_id: int,
        message: str,
        options: tts_service.TTSOptions,
    ) -> tts_service.GeneratedSpeech:
        assert agent_id == 7
        assert message == "Réponse parlée"
        assert options.speed == 1.1
        assert options.stability == 0.6
        return tts_service.GeneratedSpeech(b"ID3-mp3", "ElevenLabs", "alice")

    monkeypatch.setattr(tts_service, "generate_for_agent", generate_for_agent)

    result = await messenger_mcp._deliver_agent_audio(
        7,
        Messenger(),  # type: ignore[arg-type]
        "room-1",
        "Réponse parlée",
        speed=1.1,
        stability=0.6,
    )

    assert result == ("ElevenLabs", 7, "alice")
    assert uploads == [("room-1", "message-audio.mp3", b"ID3-mp3")]


@pytest.mark.asyncio
async def test_resend_attachment_copies_existing_bytes_without_workspace_regeneration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.database import database

    attachment_id = uuid4()
    uploads: list[tuple[str, str, bytes]] = []

    class Messenger(_FakeMessenger):
        async def fetch_attachment_to_file(self, attachment: object, path: Path) -> int:
            assert getattr(attachment, "id") == attachment_id
            path.write_bytes(b"<html>existing</html>")
            return path.stat().st_size

        async def upload_file_path(self, room_id: str, path: Path, name: str) -> None:
            uploads.append((room_id, name, path.read_bytes()))

    messenger = Messenger()

    @asynccontextmanager
    async def get_db_session():
        yield None

    monkeypatch.setattr(database, "get_db_session", get_db_session)
    monkeypatch.setattr(messenger_mcp, "_context_language", AsyncMock(return_value="en"))
    monkeypatch.setattr(
        messenger_mcp,
        "_resolve_context_messenger",
        AsyncMock(return_value=messenger),
    )
    monkeypatch.setattr(
        messenger_mcp,
        "_recent_agent_attachments",
        AsyncMock(
            return_value={
                str(attachment_id): SimpleNamespace(
                    id=attachment_id,
                    name="village.html",
                    size_bytes=21,
                )
            }
        ),
    )

    result = await messenger_mcp.mcp_room_resend_attachment(
        McpToolContext(agent_id=7, runtime="internal"),
        "room-1",
        str(attachment_id),
    )

    assert result == "Existing file 'village.html' re-sent (21 bytes)."
    assert uploads == [("room-1", "village.html", b"<html>existing</html>")]


@pytest.mark.asyncio
async def test_send_audio_message_uses_standard_user_then_message_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.database import database

    parameters = list(signature(messenger_mcp.mcp_send_audio_message).parameters)
    assert parameters[:3] == ["ctx", "user", "message"]

    events: list[str] = []

    class Messenger(_FakeMessenger):
        connection_id = 19

        def supports(self, capability: object) -> bool:
            return True

    messenger = Messenger()

    @asynccontextmanager
    async def get_db_session():
        yield None

    async def context_language(ctx: McpToolContext) -> str:
        return "en"

    async def recent_user_room(
        agent_id: int,
        user: str,
        *,
        connection_id: int | None = None,
    ) -> object:
        assert (agent_id, user, connection_id) == (7, "Alice", None)
        events.append("journal:Alice")
        return SimpleNamespace(connection_id=19, room_id="latest-room")

    async def messenger_for_agent_connection(
        agent_id: int, connection_id: int
    ) -> Messenger:
        assert (agent_id, connection_id) == (7, 19)
        events.append("connection:19")
        return messenger

    async def deliver_agent_audio(
        agent_id: int,
        selected_messenger: object,
        room_id: str,
        message: str,
        **options: Any,
    ) -> tuple[str, int, str]:
        assert (agent_id, selected_messenger, room_id, message) == (
            7,
            messenger,
            "latest-room",
            "Bonjour Alice",
        )
        events.append("audio")
        return "ElevenLabs", 9, "alice"

    monkeypatch.setattr(database, "get_db_session", get_db_session)
    monkeypatch.setattr(messenger_mcp, "_context_language", context_language)
    monkeypatch.setattr(messenger_mcp, "_deliver_agent_audio", deliver_agent_audio)
    from app.messenger import service

    monkeypatch.setattr(service, "recent_user_room", recent_user_room)
    monkeypatch.setattr(
        service,
        "messenger_for_agent_connection",
        messenger_for_agent_connection,
    )

    result = await messenger_mcp.mcp_send_audio_message(
        McpToolContext(agent_id=7, runtime="hermes"),
        "Alice",
        "Bonjour Alice",
    )

    assert result == {
        "message": "Audio message sent via ElevenLabs, voice alice (9 bytes).",
        "destination": "latest-room",
        "connection_id": 19,
        "provider": "ElevenLabs",
        "voice": "alice",
        "size": 9,
    }
    assert events == ["journal:Alice", "connection:19", "audio"]
