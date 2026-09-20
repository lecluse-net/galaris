from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, call
from uuid import uuid4

import pytest
import bridge.matrix.messenger as matrix_messenger
from app.messenger._observations import ObservedMessengerFile as Attachment
from app.messenger.models import Capability
from bridge.matrix import SPEC
from bridge.matrix.client import MatrixMessageEvent
from bridge.matrix.messenger import MatrixMessenger, matrix_to_message


def _message(event_id: str, body: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "sender": "@alice:test",
        "type": "m.room.message",
        "origin_server_ts": 1_000,
        "content": {"msgtype": "m.text", "body": body},
    }


def _sync(next_batch: str, *events: dict[str, Any]) -> dict[str, Any]:
    return {
        "next_batch": next_batch,
        "rooms": {
            "join": {
                "!room:test": {
                    "timeline": {
                        "events": list(events),
                    }
                }
            }
        },
    }


class FakeMatrix:
    tool_id = 7
    user_id = "@bot:test"
    allowed_user_ids: frozenset[str] = frozenset()
    allowed_room_ids: frozenset[str] = frozenset()
    require_group_mention = False
    auto_join_invites = False
    media_max_bytes = 16_000_000

    def __init__(self, *responses: dict[str, Any] | BaseException) -> None:
        self.responses = list(responses)
        self.sync_calls: list[tuple[str | None, int | None]] = []
        self.history_page_calls: list[tuple[str, int, str | None]] = []
        self.join_calls: list[str] = []
        self.closed = False

    async def whoami(self) -> str:
        return self.user_id

    async def direct_room_ids(self) -> frozenset[str]:
        return frozenset()

    async def get_room_messages_page(
        self,
        room_id: str,
        *,
        limit: int,
        from_token: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        self.history_page_calls.append((room_id, limit, from_token))
        return [_message("$history", "Older message")], "next-token"

    async def room_is_encrypted(self, _room_id: str) -> bool:
        return False

    async def join_room(self, room_id: str) -> str:
        self.join_calls.append(room_id)
        return room_id

    async def sync(
        self,
        since: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        self.sync_calls.append((since, timeout_ms))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    async def aclose(self) -> None:
        self.closed = True


def _messenger(matrix: FakeMatrix, connection_id: int = 41) -> MatrixMessenger:
    return MatrixMessenger(
        matrix,  # type: ignore[arg-type]
        connection_id=connection_id,
    )


@pytest.mark.asyncio
async def test_history_page_uses_matrix_continuation_token() -> None:
    matrix = FakeMatrix()
    messenger = _messenger(matrix)

    page = await messenger.history_page(
        "!room:test",
        limit=50,
        cursor="previous-token",
    )

    assert [message.id for message in page.messages] == ["$history"]
    assert page.has_more
    assert page.next_cursor == "next-token"
    assert matrix.history_page_calls == [
        ("!room:test", 50, "previous-token")
    ]


@pytest.mark.asyncio
async def test_first_sync_is_admitted_before_its_cursor_is_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = FakeMatrix(
        _sync("fresh", _message("$first", "Premier message")),
        asyncio.CancelledError(),
    )
    dispatch = AsyncMock(return_value=True)
    update_state = AsyncMock()
    monkeypatch.setattr(
        matrix_messenger.journal,
        "listener_cursor",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        matrix_messenger.journal,
        "update_listener_state",
        update_state,
    )
    monkeypatch.setattr(matrix_messenger, "dispatch_incoming", dispatch)

    with pytest.raises(asyncio.CancelledError):
        await _messenger(matrix).listen()

    assert matrix.sync_calls == [(None, 0), ("fresh", None)]
    admitted = dispatch.await_args.args[0]
    assert admitted.id == "$first"
    assert admitted.text == "Premier message"
    assert admitted.recipient is not None
    assert admitted.recipient.connection_id == 41
    update_state.assert_awaited_once_with(
        41,
        "matrix",
        cursor="fresh",
        available=True,
        event_received=True,
    )
    assert matrix.closed


@pytest.mark.asyncio
async def test_listener_resumes_from_the_persisted_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = FakeMatrix(_sync("next"), asyncio.CancelledError())
    update_state = AsyncMock()
    monkeypatch.setattr(
        matrix_messenger.journal,
        "listener_cursor",
        AsyncMock(return_value="stored"),
    )
    monkeypatch.setattr(
        matrix_messenger.journal,
        "update_listener_state",
        update_state,
    )

    with pytest.raises(asyncio.CancelledError):
        await _messenger(matrix).listen()

    assert matrix.sync_calls == [("stored", None), ("next", None)]
    update_state.assert_awaited_once_with(
        41,
        "matrix",
        cursor="next",
        available=True,
        event_received=False,
    )
    assert matrix.closed


@pytest.mark.asyncio
async def test_failed_batch_keeps_the_old_cursor_and_replays_the_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _sync(
        "next",
        _message("$one", "Un"),
        _message("$two", "Deux"),
    )
    matrix = FakeMatrix(response, response, asyncio.CancelledError())
    dispatch = AsyncMock(
        side_effect=[
            True,
            RuntimeError("temporary dispatch failure"),
            False,
            True,
        ]
    )
    update_state = AsyncMock()
    sleep = AsyncMock()
    monkeypatch.setattr(
        matrix_messenger.journal,
        "listener_cursor",
        AsyncMock(return_value="stored"),
    )
    monkeypatch.setattr(
        matrix_messenger.journal,
        "update_listener_state",
        update_state,
    )
    monkeypatch.setattr(matrix_messenger, "dispatch_incoming", dispatch)
    monkeypatch.setattr(matrix_messenger.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await _messenger(matrix).listen()

    assert matrix.sync_calls == [
        ("stored", None),
        ("stored", None),
        ("next", None),
    ]
    assert [item.args[0].id for item in dispatch.await_args_list] == [
        "$one",
        "$two",
        "$one",
        "$two",
    ]
    assert update_state.await_args_list == [
        call(
            41,
            "matrix",
            cursor="stored",
            available=False,
            error="RuntimeError",
            reconnect=True,
        ),
        call(
            41,
            "matrix",
            cursor="next",
            available=True,
            event_received=True,
        ),
    ]
    sleep.assert_awaited_once_with(1.0)
    assert matrix.closed


@pytest.mark.asyncio
async def test_matrix_messenger_requires_a_connection_for_listening() -> None:
    matrix = FakeMatrix()
    messenger = MatrixMessenger(
        matrix,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="connection ID"):
        await messenger.listen()


@pytest.mark.asyncio
async def test_listener_closes_client_when_identity_check_fails() -> None:
    matrix = FakeMatrix()
    matrix.whoami = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("invalid token")
    )

    with pytest.raises(RuntimeError, match="invalid token"):
        await _messenger(matrix).listen()

    assert matrix.closed


def test_matrix_bridge_declares_only_per_agent_credentials() -> None:
    params = {param.name: param for param in SPEC.connection_params}

    assert set(params) == {"user_id", "token", "password"}
    assert params["user_id"].required is True
    assert params["token"].required is False
    assert params["password"].required is False
    assert [param.name for param in SPEC.tool_params] == ["homeserver"]
    assert {Capability.FILES, Capability.VOICE_NOTES} <= SPEC.capabilities


def test_matrix_message_preserves_reply_media_and_direct_room() -> None:
    event = MatrixMessageEvent.model_validate(
        {
            "event_id": "$image",
            "sender": "@alice:test",
            "type": "m.room.message",
            "origin_server_ts": 12_345,
            "content": {
                "msgtype": "m.image",
                "body": (
                    "> <@bob:test> ancien message\n"
                    "> contenu cité\n\n"
                    "La légende"
                ),
                "filename": "../photo.jpg",
                "url": "mxc://media.test/abc",
                "info": {"mimetype": "image/jpeg", "size": 42},
                "m.relates_to": {
                    "m.in_reply_to": {"event_id": "$parent"}
                },
            },
        }
    )

    message = matrix_to_message(
        event,
        "!direct:test",
        "@bot:test",
        tool_id=7,
        connection_id=41,
        room_kind="direct",
    )

    assert message.text == "La légende"
    assert message.reply_to == "$parent"
    assert message.room.kind == "direct"
    assert message.time == 12
    assert message.attachments == [
        Attachment(
            id="mxc://media.test/abc",
            name="photo.jpg",
            mime="image/jpeg",
            url="mxc://media.test/abc",
            size=42,
            kind="image",
        )
    ]


@pytest.mark.asyncio
async def test_sync_ignores_notices_edits_and_malformed_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notice = _message("$notice", "message automatique")
    notice["content"]["msgtype"] = "m.notice"
    edit = _message("$edit", "texte corrigé")
    edit["content"]["m.relates_to"] = {
        "rel_type": "m.replace",
        "event_id": "$original",
    }
    encrypted_media = _message("$encrypted", "photo.jpg")
    encrypted_media["content"] = {
        "msgtype": "m.image",
        "body": "photo.jpg",
        "file": {"url": "mxc://media.test/encrypted"},
    }
    missing_id = _message("", "sans identifiant")
    valid = _message("$valid", "Bonjour")
    dispatch = AsyncMock(return_value=True)
    monkeypatch.setattr(matrix_messenger, "dispatch_incoming", dispatch)

    received = await _messenger(FakeMatrix())._dispatch_sync(
        _sync("next", notice, edit, encrypted_media, missing_id, valid)
    )

    assert received
    dispatch.assert_awaited_once()
    assert dispatch.await_args.args[0].id == "$valid"


@pytest.mark.asyncio
async def test_sync_applies_room_user_and_group_mention_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = FakeMatrix()
    matrix.allowed_user_ids = frozenset({"@alice:test"})
    matrix.allowed_room_ids = frozenset(
        {"!group:test", "!direct:test"}
    )
    matrix.require_group_mention = True
    messenger = _messenger(matrix)
    messenger._direct_room_ids = frozenset(  # pyright: ignore[reportPrivateUsage]
        {"!direct:test"}
    )
    dispatch = AsyncMock(return_value=True)
    monkeypatch.setattr(matrix_messenger, "dispatch_incoming", dispatch)

    group_without_mention = _message("$silent", "conversation générale")
    group_with_mention = _message("$mentioned", "Question")
    group_with_mention["content"]["m.mentions"] = {
        "user_ids": ["@bot:test"]
    }
    forbidden_sender = _message("$mallory", "@bot:test ouvre")
    forbidden_sender["sender"] = "@mallory:test"
    direct = _message("$direct", "Bonjour en privé")
    forbidden_room = _message("$other-room", "@bot:test ouvre")
    data = {
        "rooms": {
            "join": {
                "!group:test": {
                    "timeline": {
                        "events": [
                            group_without_mention,
                            group_with_mention,
                            forbidden_sender,
                        ]
                    }
                },
                "!direct:test": {"timeline": {"events": [direct]}},
                "!other:test": {
                    "timeline": {"events": [forbidden_room]}
                },
            }
        }
    }

    received = await messenger._dispatch_sync(data)

    assert received
    assert [item.args[0].id for item in dispatch.await_args_list] == [
        "$mentioned",
        "$direct",
    ]
    assert dispatch.await_args_list[1].args[0].room.kind == "direct"


def _invite(
    room_id: str,
    *,
    sender: str = "@alice:test",
    encrypted: bool = False,
) -> tuple[str, dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {
            "type": "m.room.member",
            "state_key": "@bot:test",
            "sender": sender,
            "content": {"membership": "invite", "is_direct": True},
        }
    ]
    if encrypted:
        events.append(
            {
                "type": "m.room.encryption",
                "state_key": "",
                "content": {"algorithm": "m.megolm.v1.aes-sha2"},
            }
        )
    return room_id, {"invite_state": {"events": events}}


@pytest.mark.asyncio
async def test_auto_join_requires_allowlist_and_refuses_encrypted_invites() -> None:
    matrix = FakeMatrix()
    matrix.auto_join_invites = True
    messenger = _messenger(matrix)
    allowed_id, allowed = _invite("!allowed:test")
    data = {"rooms": {"invite": {allowed_id: allowed}}}

    assert not await messenger._dispatch_sync(data, process_timeline=False)
    assert matrix.join_calls == []

    matrix.allowed_user_ids = frozenset({"@alice:test"})
    matrix.allowed_room_ids = frozenset(
        {"!allowed:test", "!encrypted:test"}
    )
    encrypted_id, encrypted = _invite("!encrypted:test", encrypted=True)
    forbidden_id, forbidden = _invite(
        "!forbidden:test",
        sender="@mallory:test",
    )
    data = {
        "rooms": {
            "invite": {
                allowed_id: allowed,
                encrypted_id: encrypted,
                forbidden_id: forbidden,
            }
        }
    }

    assert await messenger._dispatch_sync(data, process_timeline=False)
    assert matrix.join_calls == ["!allowed:test"]
    assert messenger._direct_room_ids == frozenset(  # pyright: ignore[reportPrivateUsage]
        {"!allowed:test"}
    )


@pytest.mark.asyncio
async def test_text_reply_uses_matrix_relation_and_direct_room_kind() -> None:
    matrix = FakeMatrix()
    matrix.room_is_encrypted = AsyncMock(  # type: ignore[method-assign]
        return_value=False
    )
    matrix.send_message = AsyncMock(  # type: ignore[attr-defined]
        return_value={"event_id": "$sent"}
    )
    messenger = _messenger(matrix)
    messenger._direct_room_ids = frozenset(  # pyright: ignore[reportPrivateUsage]
        {"!direct:test"}
    )

    message = await messenger.send_to_room(
        "!direct:test",
        "Réponse",
        reply_to="$parent",
    )

    matrix.send_message.assert_awaited_once_with(  # type: ignore[attr-defined]
        "!direct:test",
        "Réponse",
        reply_to="$parent",
    )
    assert message.id == "$sent"
    assert message.reply_to == "$parent"
    assert message.room.kind == "direct"


@pytest.mark.asyncio
async def test_text_send_refuses_encrypted_room_before_network_send() -> None:
    matrix = FakeMatrix()
    matrix.room_is_encrypted = AsyncMock(  # type: ignore[method-assign]
        return_value=True
    )
    matrix.send_message = AsyncMock()  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="Encrypted Matrix rooms"):
        await _messenger(matrix).send_to_room("!encrypted:test", "secret")

    matrix.send_message.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_file_upload_is_bounded_metadata_and_native_matrix_media() -> None:
    matrix = FakeMatrix()
    matrix.upload_media = AsyncMock(  # type: ignore[attr-defined]
        return_value="mxc://media.test/image"
    )
    matrix.send_room_event = AsyncMock(  # type: ignore[attr-defined]
        return_value={"event_id": "$image"}
    )

    message = await _messenger(matrix).upload_file(
        "!room:test",
        b"image",
        name="../photo.png",
    )

    matrix.upload_media.assert_awaited_once_with(  # type: ignore[attr-defined]
        b"image",
        "photo.png",
        "image/png",
    )
    content = matrix.send_room_event.await_args.args[2]  # type: ignore[attr-defined]
    assert content == {
        "msgtype": "m.image",
        "body": "photo.png",
        "filename": "photo.png",
        "url": "mxc://media.test/image",
        "info": {"mimetype": "image/png", "size": 5},
    }
    assert message.attachments[0].url == "mxc://media.test/image"
    assert message.attachments[0].kind == "image"


@pytest.mark.asyncio
async def test_voice_note_uses_audio_fallback_and_voice_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    normalized = tmp_path / "voice.ogg"
    normalized.write_bytes(b"opus")

    @asynccontextmanager
    async def fake_normalized_voice_note(
        _path: Path,
        **_kwargs: object,
    ) -> Any:
        yield normalized

    monkeypatch.setattr(
        matrix_messenger,
        "normalized_voice_note",
        fake_normalized_voice_note,
    )
    matrix = FakeMatrix()
    matrix.upload_media_path = AsyncMock(  # type: ignore[attr-defined]
        return_value="mxc://media.test/voice"
    )
    matrix.send_room_event = AsyncMock(  # type: ignore[attr-defined]
        return_value={"event_id": "$voice"}
    )

    message = await _messenger(matrix).send_voice_note(
        "!room:test",
        tmp_path / "source.wav",
        caption="Écoutez",
        reply_to="$parent",
    )

    matrix.upload_media_path.assert_awaited_once_with(  # type: ignore[attr-defined]
        normalized,
        "voice.ogg",
        "audio/ogg",
    )
    content = matrix.send_room_event.await_args.args[2]  # type: ignore[attr-defined]
    assert content["msgtype"] == "m.audio"
    assert content["org.matrix.msc3245.voice"] == {}
    assert content["m.relates_to"] == {
        "m.in_reply_to": {"event_id": "$parent"}
    }
    assert message.reply_to == "$parent"
    assert message.attachments[0].kind == "audio"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "wrong_account", "altered_file", "lost_acknowledgment"])
async def test_live_qualification_requires_independent_exact_reception(tmp_path, fault):
    """Only the homeserver HTTP boundary is replaced; use the real adapter both ways."""
    import json
    import httpx
    from bridge.matrix.client import Matrix
    from scripts.qualify_matrix import qualify

    events = []
    media = b""
    observer_reads = 0

    def homeserver(request):
        nonlocal media, observer_reads
        path = request.url.path
        observer = request.headers.get("Authorization") == "Bearer observer-test-token"
        if path.endswith("/account/whoami"):
            identity = "@observer:test" if observer else "@sender:test"
            if fault == "wrong_account" and observer:
                identity = "@unexpected:test"
            return httpx.Response(200, json={"user_id": identity})
        if path.endswith(("/state/m.room.encryption", "/account_data/m.direct")):
            return httpx.Response(404, json={"errcode": "M_NOT_FOUND"})
        if "/send/" in path:
            assert not observer
            event = {"event_id": f"$event-{len(events)}", "sender": "@sender:test", "type": "m.room.message",
                     "origin_server_ts": 1000, "content": json.loads(request.content)}
            events.append(event)
            if fault == "lost_acknowledgment":
                raise httpx.ReadTimeout("The server accepted the event but the response was lost")
            return httpx.Response(200, json={"event_id": event["event_id"]})
        if path.endswith("/upload"):
            media = request.content
            return httpx.Response(200, json={"content_uri": "mxc://matrix.test/file"})
        if "/download/" in path:
            assert observer
            return httpx.Response(200, content=b"altered" if fault == "altered_file" else media)
        if path.endswith("/messages"):
            assert observer
            observer_reads += 1
            return httpx.Response(200, json={"chunk": list(reversed(events))})
        pytest.fail(f"Unexpected Matrix request: {request.method} {path}")

    sender = Matrix("https://matrix.test", "@sender:test", "sender-test-token", media_max_bytes=4096)
    observer = Matrix("https://matrix.test", "@observer:test", "observer-test-token", media_max_bytes=4096)
    for client in (sender, observer):
        client._client = httpx.AsyncClient(base_url="https://matrix.test", transport=httpx.MockTransport(homeserver))
    evidence = tmp_path / "qualification.json"
    if fault:
        with pytest.raises((ValueError, httpx.ReadTimeout)):
            await qualify(sender, observer, "!test:matrix.test", evidence)
    else:
        result = await qualify(sender, observer, "!test:matrix.test", evidence)
        assert result["qualified"] and observer_reads >= 2
    saved = json.loads(evidence.read_text())
    assert saved["qualified"] == (fault is None)
    assert "sender-test-token" not in evidence.read_text()
    assert "observer-test-token" not in evidence.read_text()
    if fault == "wrong_account":
        assert not events
    elif fault == "lost_acknowledgment":
        assert len(events) == 1 and not media
        assert saved["delivery_state"] == "text_submission_started"
    else:
        assert len(events) == 2
