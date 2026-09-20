from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import AsyncMock, Mock, call
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Request, UploadFile
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from app.chat import assertions
from app.chat.assertions import (
    ChatRoomAccessAssertion,
    ChatScopeAssertion,
    InternalFileAccessAssertion,
    InternalRoomAccessAssertion,
)
from app.chat import router as router_module
from app.chat.router import (
    ACCESS,
    CALL,
    IMPERSONATE,
    MANAGE,
    SEND,
    add_call_candidate,
    create_attachment_message,
    create_room_document,
    read_agent_avatar,
    read_message_preview_image,
    read_message_previews,
    read_message_speech,
    read_message_speech_status,
    read_room_commands,
    read_voice_call_status,
    router,
    start_call,
    stop_call,
    transcribe_dictation,
)
from app.chat.schemas import (
    ConversationDocumentCreate,
    MessageCreate,
    RoomCreate,
    WebRtcIceCandidate,
    WebRtcIceCandidateBatch,
    WebRtcOffer,
)
from app.agent import AgentManagementScope, AgentDialogueAssertion
from app.conversation import ConversationDocumentMetadata
from app.messenger import MessageResourcePreview
from core.authorize import AssertionContext
from core.user import UserModel as User


def test_every_route_has_the_expected_privilege_and_resource_assertion() -> None:
    expected = {
        "read_status": (ACCESS, None),
        "read_inbox": (ACCESS, None),
        "read_push_configuration": (ACCESS, None),
        "create_push_subscription": (ACCESS, None),
        "remove_push_subscription": (ACCESS, None),
        "read_frequent_emojis": (ACCESS, None),
        "create_emoji_usage": (ACCESS, None),
        "read_identity_mappings": (ACCESS, None),
        "update_identity_mapping": (ACCESS, None),
        "delete_identity_mapping": (ACCESS, None),
        "read_recipients": (ACCESS, None),
        "read_viewer_agents": (IMPERSONATE, None),
        "read_agent_avatar": (ACCESS, AgentDialogueAssertion),
        "read_rooms": (ACCESS, ChatScopeAssertion),
        "create_room": (MANAGE, None),
        "read_room": (ACCESS, ChatRoomAccessAssertion),
        "update_room_preferences": (ACCESS, ChatRoomAccessAssertion),
        "update_room_archive": (ACCESS, ChatRoomAccessAssertion),
        "update_room_topic": ("TOPIC_EDIT", ChatRoomAccessAssertion),
        "read_room_commands": (ACCESS, InternalRoomAccessAssertion),
        "read_messages": (ACCESS, ChatRoomAccessAssertion),
        "read_interaction": (ACCESS, InternalRoomAccessAssertion),
        "answer_interaction": (SEND, InternalRoomAccessAssertion),
        "read_message_speech_status": (ACCESS, ChatRoomAccessAssertion),
        "read_message_speech": (ACCESS, ChatRoomAccessAssertion),
        "update_message_topic": ("TOPIC_EDIT", ChatRoomAccessAssertion),
        "read_message_previews": (ACCESS, ChatRoomAccessAssertion),
        "read_message_preview_image": (ACCESS, ChatRoomAccessAssertion),
        "read_message_preview_content": (ACCESS, ChatRoomAccessAssertion),
        "create_standalone_html_preview": (ACCESS, None),
        "read_activity": (ACCESS, ChatRoomAccessAssertion),
        "read_activity_detail": (ACCESS, ChatRoomAccessAssertion),
        "read_room_tasks": (["TASK_ACCESS", "TASK_EDIT"], ChatRoomAccessAssertion),
        "read_room_documents": (
            ["MEMORY_ACCESS", "MEMORY_EDIT", "MEMORY_ADMIN"],
            ChatRoomAccessAssertion,
        ),
        "create_room_document": ("MEMORY_EDIT", ChatRoomAccessAssertion),
        "read_room_processes": (
            ["PROCESS_READ", "PROCESS_LAUNCH", "PROCESS_ADMIN"],
            ChatRoomAccessAssertion,
        ),
        "create_message": (SEND, InternalRoomAccessAssertion),
        "transcribe_dictation": (SEND, InternalRoomAccessAssertion),
        "create_attachment_message": (SEND, InternalRoomAccessAssertion),
        "mark_read": (ACCESS, ChatRoomAccessAssertion),
        "set_muted": (ACCESS, ChatRoomAccessAssertion),
        "download_file": (ACCESS, ChatRoomAccessAssertion),
        "read_voice_call_status": (CALL, None),
        "start_call": (CALL, None),
        "read_active_call": (CALL, None),
        "add_call_candidate": (CALL, None),
        "stop_call": (CALL, None),
    }
    routes = {
        route.endpoint.__name__: route
        for route in router.routes
        if isinstance(route, APIRoute)
    }

    standalone_route = routes.pop("read_standalone_html_preview")
    assert getattr(standalone_route.endpoint, "_independent_auth_reason") == (
        "Unguessable, short-lived HTML preview capability ticket"
    )

    assert set(routes) == set(expected)
    for name, (privilege, assertion) in expected.items():
        metadata = getattr(routes[name].endpoint, "_authorize_meta")
        expected_privileges = privilege if isinstance(privilege, list) else [privilege]
        assert metadata["privileges"] == expected_privileges
        assert metadata["assertion"] is assertion


def test_private_file_previews_are_limited_to_agent_messages() -> None:
    document_id = uuid4()
    inbound = Mock(
        text=f"See console://private/report.html and document://{document_id}",
        direction="inbound",
    )
    outbound = Mock(
        text=f"See console://private/report.html and document://{document_id}",
        direction="outbound",
    )

    assert router_module._message_preview_references(inbound) == (
        f"document://{document_id}",
    )
    assert router_module._message_preview_references(outbound) == (
        "console://private/report.html",
        f"document://{document_id}",
    )
    assert router_module._message_preview_content_references(inbound) == ()
    assert router_module._message_preview_content_references(outbound) == (
        "console://private/report.html",
    )


@pytest.mark.asyncio
async def test_room_document_creation_uses_the_room_agent_and_returns_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    document_id = uuid4()
    created_at = datetime.now(timezone.utc)
    create = AsyncMock(
        return_value=ConversationDocumentMetadata(
            id=document_id,
            title="Chat draft",
            revision=1,
            updated_at=created_at,
        )
    )
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_chat_room",
        AsyncMock(return_value=Mock(agent_id=9)),
    )
    monkeypatch.setattr(router_module, "create_conversation_room_document", create)

    result = await create_room_document(
        room_id,
        ConversationDocumentCreate(title="Chat draft"),
    )

    create.assert_awaited_once_with(room_id, 9, "Chat draft")
    assert result.id == document_id
    assert result.uri == f"document://{document_id}"
    assert result.updated_at == created_at


@pytest.mark.asyncio
async def test_external_html_thumbnail_is_scheduled_after_preview_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    message_id = uuid4()
    url = "https://example.com/page"
    preview = MessageResourcePreview(
        uri=url,
        kind="web",
        title="Example",
        media_type="text/html",
        image_available=True,
        open_mode="external",
        external_url=url,
    )
    schedule = Mock()
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_chat_message",
        AsyncMock(return_value=Mock(text=url, direction="outbound")),
    )
    monkeypatch.setattr(
        router_module,
        "get_chat_room",
        AsyncMock(return_value=Mock(agent_id=9)),
    )
    monkeypatch.setattr(
        router_module,
        "preview_references",
        AsyncMock(return_value=[preview]),
    )
    monkeypatch.setattr(router_module, "schedule_public_page_thumbnail", schedule)
    monkeypatch.setattr(router_module, "read_cached_page_metadata", AsyncMock(return_value=Mock(title="Example", description="Shared site description", site_name="Publisher")))

    result = await read_message_previews(room_id, message_id, None)

    assert result == [preview]
    assert result[0].description == "Shared site description"
    assert result[0].subtitle == "Publisher"
    schedule.assert_called_once_with(agent_id=9, url=url)


@pytest.mark.asyncio
async def test_private_html_thumbnail_is_scheduled_after_preview_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    message_id = uuid4()
    uri = "console://reports/private.html"
    preview = MessageResourcePreview(
        uri=uri,
        kind="file",
        title="Private",
        media_type="text/html",
        image_available=True,
        download_available=True,
    )
    schedule = Mock()
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_chat_message",
        AsyncMock(return_value=Mock(text=uri, direction="outbound")),
    )
    monkeypatch.setattr(
        router_module,
        "get_chat_room",
        AsyncMock(return_value=Mock(agent_id=9)),
    )
    monkeypatch.setattr(
        router_module,
        "preview_references",
        AsyncMock(return_value=[preview]),
    )
    monkeypatch.setattr(router_module, "schedule_html_thumbnail", schedule)

    result = await read_message_previews(room_id, message_id, None)

    assert result == [preview]
    schedule.assert_called_once_with(agent_id=9, uri=uri)


@pytest.mark.asyncio
async def test_external_html_image_endpoint_reads_only_the_generated_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    message_id = uuid4()
    url = "https://example.com/page"
    preview = MessageResourcePreview(
        uri=url,
        kind="web",
        title="Example",
        media_type="text/html",
        image_available=True,
        open_mode="external",
        external_url=url,
    )
    cached = AsyncMock(return_value=(b"jpeg", "image/jpeg"))
    proxy = AsyncMock()
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_chat_message",
        AsyncMock(return_value=Mock(text=url, direction="outbound")),
    )
    monkeypatch.setattr(
        router_module,
        "get_chat_room",
        AsyncMock(return_value=Mock(agent_id=9)),
    )
    monkeypatch.setattr(
        router_module,
        "preview_reference",
        AsyncMock(return_value=preview),
    )
    monkeypatch.setattr(router_module, "read_cached_thumbnail", cached)
    monkeypatch.setattr(router_module, "preview_image", proxy)

    response = await read_message_preview_image(room_id, message_id, url, None)

    assert response.body == b"jpeg"
    cached.assert_awaited_once_with(reference=url)
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_avatar_is_limited_to_visible_internal_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_avatar = AsyncMock(return_value=b"\x89PNG\r\n\x1a\ncontent")
    monkeypatch.setattr(router_module, "internal_agent_avatar", get_avatar)

    response = await read_agent_avatar(7)

    assert response.media_type == "image/png"
    assert response.body.startswith(b"\x89PNG")
    get_avatar.assert_awaited_once_with(7)


def test_room_creation_rejects_participant_fields() -> None:
    with pytest.raises(ValidationError):
        RoomCreate.model_validate({"agent_id": 7, "member_user_ids": [19]})


def test_room_creation_accepts_complete_preferences_and_keeps_legacy_defaults() -> None:
    topic_id = uuid4()

    complete = RoomCreate.model_validate(
        {
            "agent_id": 7,
            "label": "  Projet confidentiel  ",
            "topic_id": str(topic_id),
            "show_last_message": False,
        }
    )
    legacy = RoomCreate.model_validate({"agent_id": 7})

    assert complete.label == "Projet confidentiel"
    assert complete.topic_id == topic_id
    assert complete.show_last_message is False
    assert legacy.label is None
    assert legacy.topic_id is None
    assert legacy.show_last_message is True


def test_room_creation_rejects_an_empty_explicit_label() -> None:
    with pytest.raises(ValidationError):
        RoomCreate.model_validate({"agent_id": 7, "label": "   "})


@pytest.mark.asyncio
async def test_room_creation_rejects_topic_without_topic_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Mock()
    scope.allows.return_value = True
    monkeypatch.setattr(router_module, "_require_enabled", Mock())
    monkeypatch.setattr(
        router_module,
        "current_dialogue_scope",
        AsyncMock(return_value=scope),
    )
    monkeypatch.setattr(
        router_module.user_service,
        "get_current_user",
        AsyncMock(return_value=Mock()),
    )
    monkeypatch.setattr(router_module, "get_db", Mock(return_value=Mock()))
    monkeypatch.setattr(
        router_module,
        "check_privilege",
        AsyncMock(return_value=False),
    )

    with pytest.raises(HTTPException) as exc_info:
        await router_module.create_room(
            RoomCreate(agent_id=7, label="Privée", topic_id=uuid4())
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_room_creation_forwards_all_preferences_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic_id = uuid4()
    created_room = Mock()
    scope = Mock()
    scope.allows.return_value = True
    create_internal_room = AsyncMock(return_value=created_room)
    validate_topic = AsyncMock()
    monkeypatch.setattr(router_module, "_require_enabled", Mock())
    monkeypatch.setattr(
        router_module,
        "current_dialogue_scope",
        AsyncMock(return_value=scope),
    )
    monkeypatch.setattr(
        router_module.user_service,
        "get_current_user",
        AsyncMock(return_value=Mock()),
    )
    monkeypatch.setattr(router_module, "get_db", Mock(return_value=Mock()))
    monkeypatch.setattr(
        router_module,
        "check_privilege",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(router_module, "_validate_topic", validate_topic)
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(router_module, "create_internal_room", create_internal_room)
    monkeypatch.setattr(router_module, "_room_for_scope", lambda room, _scope: room)

    result = await router_module.create_room(
        RoomCreate(
            agent_id=7,
            label="Projet privé",
            topic_id=topic_id,
            show_last_message=False,
        )
    )

    assert result is created_room
    validate_topic.assert_awaited_once_with(topic_id)
    create_internal_room.assert_awaited_once_with(
        actor_user_id=17,
        agent_id=7,
        label="Projet privé",
        topic_id=topic_id,
        show_last_message=False,
    )


def test_message_create_rejects_unknown_reasoning_effort() -> None:
    with pytest.raises(ValidationError):
        MessageCreate.model_validate(
            {
                "client_message_id": str(uuid4()),
                "text": "@task Analyse ce rapport",
                "reasoning_effort_override": "extreme",
            }
        )


@pytest.mark.parametrize(
    ("requested", "expected"),
    [("minimal", "low"), ("max", "max")],
)
def test_message_create_normalizes_supported_reasoning_effort(
    requested: str,
    expected: str,
) -> None:
    message = MessageCreate.model_validate(
        {
            "client_message_id": str(uuid4()),
            "text": "@task Analyse ce rapport",
            "reasoning_effort_override": requested,
        }
    )

    assert message.reasoning_effort_override == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("driver", "expected"),
    [
        (
            "internal",
            ["task", "exec", "plan", "standard", "high", "effort", "approve"],
        ),
        ("hermes", ["task", "standard", "high", "effort", "approve"]),
    ],
)
async def test_room_commands_follow_the_selected_agent_driver(
    monkeypatch: pytest.MonkeyPatch,
    driver: str,
    expected: list[str],
) -> None:
    room_id = uuid4()
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(return_value=Mock(agent_id=7)),
    )
    monkeypatch.setattr(
        router_module,
        "get_agent_chat_directives",
        AsyncMock(
            return_value=(
                (
                    "task",
                    "exec",
                    "plan",
                    "standard",
                    "high",
                    "effort",
                    "approve",
                )
                if driver == "internal"
                else ("task", "standard", "high", "effort", "approve")
            )
        ),
    )

    result = await read_room_commands(room_id)

    assert result.commands == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("displayed_document_id", [None, uuid4()])
async def test_attachment_message_publishes_all_uploaded_files_together(
    monkeypatch: pytest.MonkeyPatch,
    displayed_document_id: UUID | None,
) -> None:
    room_id = uuid4()
    client_message_id = uuid4()
    uploads = [
        UploadFile(file=BytesIO(b"one"), filename="one.txt"),
        UploadFile(file=BytesIO(b"second"), filename="second.pdf"),
    ]
    store_upload = AsyncMock(
        side_effect=[
            (Mock(), 3, "text/plain"),
            (Mock(), 6, "application/pdf"),
        ]
    )
    publish = AsyncMock(return_value=Mock())
    monkeypatch.setattr(router_module, "_require_enabled", Mock())
    monkeypatch.setattr(router_module, "_validate_topic", AsyncMock())
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(return_value=Mock(agent_active=True)),
    )
    monkeypatch.setattr(router_module.storage, "store_upload", store_upload)
    monkeypatch.setattr(router_module, "publish_internal_message", publish)

    result = await create_attachment_message(
        room_id,
        uploads,
        client_message_id,
        "Documents",
        None,
        None,
        None,
        True,
        displayed_document_id,
        "fr",
    )

    assert result is publish.return_value
    assert publish.await_args.kwargs["language"] == "fr"
    assert store_upload.await_count == 2
    attachments = publish.await_args.kwargs["attachments"]
    assert [attachment.name for attachment in attachments] == [
        "one.txt",
        "second.pdf",
    ]
    assert [attachment.size for attachment in attachments] == [3, 6]
    assert publish.await_args.kwargs["text"] == "Documents"
    assert publish.await_args.kwargs["task_requested"] is True
    assert publish.await_args.kwargs["displayed_document_id"] == displayed_document_id


@pytest.mark.asyncio
async def test_attachment_message_discards_files_when_a_later_upload_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads = [
        UploadFile(file=BytesIO(b"one"), filename="one.txt"),
        UploadFile(file=BytesIO(b"bad"), filename="bad.svg"),
    ]
    store_upload = AsyncMock(
        side_effect=[
            (Mock(), 3, "text/plain"),
            router_module.storage.AttachmentStorageError("not accepted"),
        ]
    )
    discard = AsyncMock()
    monkeypatch.setattr(router_module, "_require_enabled", Mock())
    monkeypatch.setattr(router_module, "_validate_topic", AsyncMock())
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(return_value=Mock(agent_active=True)),
    )
    monkeypatch.setattr(router_module.storage, "store_upload", store_upload)
    monkeypatch.setattr(router_module.storage, "discard", discard)

    with pytest.raises(HTTPException) as raised:
        await create_attachment_message(
            uuid4(),
            uploads,
            uuid4(),
            "",
            None,
            None,
            None,
        )

    assert raised.value.status_code == 422
    assert raised.value.detail == "not accepted"
    first_file_id = store_upload.await_args_list[0].args[1]
    discard.assert_awaited_once_with(first_file_id)


@pytest.mark.asyncio
async def test_attachment_message_reports_oversized_upload_as_413(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limit = 16_000_000
    monkeypatch.setattr(router_module, "_require_enabled", Mock())
    monkeypatch.setattr(router_module, "_validate_topic", AsyncMock())
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(return_value=Mock(agent_active=True)),
    )
    monkeypatch.setattr(
        router_module.storage,
        "store_upload",
        AsyncMock(side_effect=router_module.storage.AttachmentTooLargeError(limit)),
    )

    with pytest.raises(HTTPException) as raised:
        await create_attachment_message(
            uuid4(),
            [UploadFile(file=BytesIO(b"video"), filename="recording.mkv")],
            uuid4(),
            "",
            None,
            None,
            None,
        )

    assert raised.value.status_code == 413
    assert str(limit) in str(raised.value.detail)


@pytest.mark.asyncio
async def test_dictation_transcribes_transient_audio_for_room_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    transcribe = AsyncMock(return_value="Bonjour tout le monde")
    monkeypatch.setattr(router_module, "_require_enabled", Mock())
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(return_value=Mock(agent_active=True, agent_id=9)),
    )
    monkeypatch.setattr(router_module, "transcribe_voice_audio", transcribe)
    upload = UploadFile(
        file=BytesIO(b"short-lived-audio"),
        filename="dictation.webm",
        headers=Headers({"content-type": "audio/webm;codecs=opus"}),
    )

    result = await transcribe_dictation(room_id, upload, "fr-FR")

    assert result.text == "Bonjour tout le monde"
    transcribe.assert_awaited_once_with(
        b"short-lived-audio",
        filename="dictation.webm",
        mime_type="audio/webm",
        language="fr-FR",
        agent_id=9,
    )


@pytest.mark.asyncio
async def test_message_speech_status_lists_only_message_authors_with_a_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    available = AsyncMock(side_effect=[True, False])
    authors = AsyncMock(return_value=[9, 12])
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "current_dialogue_scope",
        AsyncMock(return_value=AgentManagementScope(17, frozenset({9, 12}))),
    )
    monkeypatch.setattr(
        router_module,
        "list_chat_message_agent_ids",
        authors,
    )
    monkeypatch.setattr(router_module, "agent_voice_synthesis_available", available)

    result = await read_message_speech_status(room_id, None)

    assert result.available_agent_ids == [9]
    authors.assert_awaited_once_with(17, room_id, agent_id=None)
    assert available.await_args_list == [call(9), call(12)]


@pytest.mark.asyncio
async def test_voice_call_status_uses_the_room_agent_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    capability = AsyncMock(return_value=True)
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(return_value=Mock(agent_active=True, agent_id=9)),
    )
    monkeypatch.setattr(router_module, "browser_call_network_available", Mock(return_value=True))
    monkeypatch.setattr(
        router_module,
        "browser_ice_servers",
        Mock(
            return_value=(
                Mock(
                    urls=("turn:turn.example.test:3478",),
                    username="1600:galaris:user:17",
                    credential="credential",
                ),
            )
        ),
    )
    monkeypatch.setattr(router_module, "agent_voice_call_available", capability)

    result = await read_voice_call_status(room_id)

    assert result.available is True
    assert result.ice_servers[0].urls == ["turn:turn.example.test:3478"]
    assert result.ice_servers[0].username == "1600:galaris:user:17"
    capability.assert_awaited_once_with(9)


@pytest.mark.asyncio
async def test_start_call_rejects_an_agent_without_a_complete_voice_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = Mock()
    monkeypatch.setattr(router_module, "_require_enabled", Mock())
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(return_value=Mock(agent_active=True, agent_id=9)),
    )
    monkeypatch.setattr(
        router_module,
        "agent_voice_call_available",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(router_module, "BrowserCallTransport", transport)

    with pytest.raises(HTTPException) as raised:
        await start_call(uuid4(), WebRtcOffer(sdp="offer", language="fr"))

    assert raised.value.status_code == 503
    assert raised.value.detail == "Agent voice calling is not configured."
    transport.assert_not_called()


@pytest.mark.asyncio
async def test_start_call_rejects_an_answer_without_a_production_relay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    room = Mock(
        id=room_id,
        agent_active=True,
        agent_id=9,
        connection_id=12,
        external_id="chat:direct:17:9",
    )
    transport = Mock()
    transport.accept_offer = AsyncMock(
        return_value=(
            "v=0\r\na=candidate:1 1 UDP 1 172.20.0.2 5000 typ host\r\n",
            "answer",
        )
    )
    transport.leave = AsyncMock()
    transport_factory = Mock(return_value=transport)
    manager = Mock()
    monkeypatch.setattr(router_module, "_require_enabled", Mock())
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(return_value=room),
    )
    monkeypatch.setattr(
        router_module,
        "browser_call_network_available",
        Mock(return_value=True),
    )
    monkeypatch.setattr(
        router_module,
        "browser_answer_network_available",
        Mock(return_value=False),
    )
    monkeypatch.setattr(
        router_module,
        "browser_rtc_configuration",
        Mock(return_value=Mock()),
    )
    monkeypatch.setattr(
        router_module,
        "agent_voice_call_available",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(router_module, "BrowserCallTransport", transport_factory)
    monkeypatch.setattr(router_module, "voice_call_manager", manager)

    with pytest.raises(HTTPException) as raised:
        await start_call(room_id, WebRtcOffer(sdp="offer", language="fr"))

    assert raised.value.status_code == 503
    assert raised.value.detail == "The voice relay is temporarily unavailable."
    transport.leave.assert_awaited_once_with(transport)
    manager.start_agent_call.assert_not_called()


@pytest.mark.asyncio
async def test_stop_call_is_idempotent_after_the_peer_closed_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    manager = Mock()
    manager.active_calls.return_value = []
    manager.request_stop_call = AsyncMock()
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(
            return_value=Mock(
                agent_id=9,
                connection_id=12,
                external_id="chat:direct:17:9",
            )
        ),
    )
    monkeypatch.setattr(router_module, "voice_call_manager", manager)

    result = await stop_call(room_id, "voice-9-12-closed")

    assert result.ok is True
    manager.request_stop_call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("batched", [False, True])
async def test_call_candidate_is_applied_only_to_the_matching_internal_call(
    monkeypatch: pytest.MonkeyPatch,
    batched: bool,
) -> None:
    room_id = uuid4()
    room = Mock(
        agent_id=9,
        connection_id=12,
        external_id="chat:direct:17:9",
    )
    info = Mock(
        call_id="voice-9-12-mobile",
        connection_id=12,
        room_id="chat:direct:17:9",
    )
    transport = Mock(spec=router_module.BrowserCallTransport)
    transport.add_remote_candidate = AsyncMock()
    manager = Mock()
    manager.active_calls.return_value = [info]
    manager.active_transport.return_value = transport
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(return_value=room),
    )
    monkeypatch.setattr(router_module, "voice_call_manager", manager)

    candidate = WebRtcIceCandidate(
        candidate="candidate:1 1 udp 1 192.0.2.10 50000 typ host",
        sdp_mid="0",
        sdp_m_line_index=0,
    )
    result = await add_call_candidate(
        room_id,
        "voice-9-12-mobile",
        WebRtcIceCandidateBatch(candidates=[candidate, WebRtcIceCandidate()]) if batched else candidate,
    )

    assert result.ok is True
    expected = [call(candidate.candidate, sdp_mid="0", sdp_m_line_index=0)]
    if batched:
        expected.append(call(None, sdp_mid=None, sdp_m_line_index=None))
    assert transport.add_remote_candidate.await_args_list == expected

    info.room_id = "another-room"
    with pytest.raises(HTTPException) as raised:
        await add_call_candidate(
            room_id, "voice-9-12-mobile",
            WebRtcIceCandidateBatch(candidates=[candidate]) if batched else candidate,
        )
    assert raised.value.status_code == 404
    assert transport.add_remote_candidate.await_args_list == expected


@pytest.mark.parametrize("size", [0, 51])
def test_call_candidate_batches_are_bounded(size: int) -> None:
    with pytest.raises(ValidationError):
        WebRtcIceCandidateBatch(candidates=[WebRtcIceCandidate()] * size)


@pytest.mark.asyncio
async def test_message_speech_streams_prepared_audio_for_the_author_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    message_id = uuid4()
    synthesize = AsyncMock(return_value=b"ID3-generated-audio")
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "current_dialogue_scope",
        AsyncMock(return_value=AgentManagementScope(17, frozenset({12}))),
    )
    monkeypatch.setattr(
        router_module,
        "get_chat_message",
        AsyncMock(
            return_value=Mock(
                text="  Bonjour **Nicolas** 😀  ",
                sender=Mock(is_ai=True, agent_id=12),
            )
        ),
    )
    monkeypatch.setattr(router_module, "synthesize_agent_message", synthesize)

    response = await read_message_speech(room_id, message_id, None, "fr-FR")
    chunks = [chunk async for chunk in response.body_iterator]

    assert response.media_type == "audio/mpeg"
    assert b"".join(chunks) == b"ID3-generated-audio"
    assert response.headers["cache-control"] == "private, no-store"
    synthesize.assert_awaited_once_with(12, "Bonjour **Nicolas** 😀", language="fr-FR")


@pytest.mark.asyncio
async def test_message_speech_rejects_a_human_authored_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_chat_message",
        AsyncMock(
            return_value=Mock(
                text="Message humain",
                sender=Mock(is_ai=False, agent_id=None),
            )
        ),
    )
    synthesize = AsyncMock()
    monkeypatch.setattr(router_module, "synthesize_agent_message", synthesize)

    with pytest.raises(HTTPException) as raised:
        await read_message_speech(uuid4(), uuid4(), None, "fr")

    assert raised.value.status_code == 422
    assert raised.value.detail == (
        "Only messages authored by a configured agent can be synthesized."
    )
    synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_dictation_reports_missing_transcription_profile_as_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(router_module, "_require_enabled", Mock())
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(return_value=Mock(agent_active=True, agent_id=9)),
    )
    monkeypatch.setattr(
        router_module,
        "transcribe_voice_audio",
        AsyncMock(side_effect=router_module.VoiceTranscriptionUnavailable()),
    )
    upload = UploadFile(
        file=BytesIO(b"audio"),
        filename="dictation.ogg",
        headers=Headers({"content-type": "audio/ogg"}),
    )

    with pytest.raises(HTTPException) as raised:
        await transcribe_dictation(uuid4(), upload, "fr")

    assert raised.value.status_code == 503
    assert raised.value.detail == "Voice transcription is not configured."


@pytest.mark.asyncio
async def test_dictation_rejects_unsupported_audio_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(router_module, "_require_enabled", Mock())
    monkeypatch.setattr(router_module, "_user_id", AsyncMock(return_value=17))
    monkeypatch.setattr(
        router_module,
        "get_internal_room",
        AsyncMock(return_value=Mock(agent_active=True, agent_id=9)),
    )
    upload = UploadFile(
        file=BytesIO(b"not-audio"),
        filename="dictation.txt",
        headers=Headers({"content-type": "text/plain"}),
    )

    with pytest.raises(HTTPException) as raised:
        await transcribe_dictation(uuid4(), upload, "fr")

    assert raised.value.status_code == 415


def _context(*, room_id: object, file_id: object | None = None) -> AssertionContext:
    path_params = {"room_id": room_id}
    if file_id is not None:
        path_params["file_id"] = file_id
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "path_params": path_params,
        }
    )
    user = User(
        email="member@example.test",
        display_name="Member",
        hashed_password="unused",
        is_active=True,
    )
    user.id = 17
    return AssertionContext(
        user=user,
        request=request,
        db=Mock(spec=AsyncSession),
    )


@pytest.mark.asyncio
async def test_room_access_assertion_uses_authenticated_user_and_path_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    policy = AsyncMock(return_value=True)
    monkeypatch.setattr(assertions, "has_room_access", policy)
    monkeypatch.setattr(
        assertions,
        "get_internal_room",
        AsyncMock(return_value=Mock(agent_id=9)),
    )
    monkeypatch.setattr(
        assertions,
        "dialogue_scope_for",
        AsyncMock(return_value=AgentManagementScope(17, frozenset({9}))),
    )

    assert await InternalRoomAccessAssertion().assert_(
        _context(room_id=str(room_id))
    )
    policy.assert_awaited_once_with(17, room_id)


@pytest.mark.asyncio
async def test_chat_room_access_uses_linked_authenticated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    policy = AsyncMock(return_value=True)
    monkeypatch.setattr(assertions, "has_chat_room_access", policy)
    monkeypatch.setattr(
        assertions,
        "get_chat_room",
        AsyncMock(return_value=Mock(agent_id=9)),
    )
    monkeypatch.setattr(
        assertions,
        "management_scope_for",
        AsyncMock(return_value=AgentManagementScope(17, frozenset({9}))),
    )

    assert await ChatRoomAccessAssertion().assert_(_context(room_id=str(room_id)))
    policy.assert_awaited_once_with(17, room_id)


@pytest.mark.asyncio
async def test_file_assertion_checks_exact_room_file_and_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    file_id = uuid4()
    policy = AsyncMock(return_value=object())
    monkeypatch.setattr(assertions, "internal_file_access", policy)
    monkeypatch.setattr(
        assertions,
        "get_internal_room",
        AsyncMock(return_value=Mock(agent_id=9)),
    )
    monkeypatch.setattr(
        assertions,
        "dialogue_scope_for",
        AsyncMock(return_value=AgentManagementScope(17, frozenset({9}))),
    )

    assert await InternalFileAccessAssertion().assert_(
        _context(room_id=str(room_id), file_id=str(file_id))
    )
    policy.assert_awaited_once_with(
        user_id=17,
        room_id=room_id,
        file_id=file_id,
    )
