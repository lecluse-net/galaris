"""Authenticated REST API for Chat over canonical Messenger data."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from core.authorize import authorize, check_privilege, independent_auth
from core import websocket
from core.database import get_db
from core.i18n import current_language
from core.params import runtime_settings
from core.user import user_service
from app.agent import (
    AgentManagementScope,
    AgentDialogueAssertion,
    current_management_scope,
    current_dialogue_scope,
)

from app.browser import (
    read_cached_thumbnail,
    read_cached_page_metadata,
    schedule_public_page_thumbnail,
)
from app.messenger import (
    NativeMessengerInteraction,
    read_internal_interaction,
    answer_internal_interaction,
    ChatViewerAgent,
    MessageResourcePreview,
    chat_file_access,
    create_internal_room,
    clear_chat_identity_mapping,
    count_chat_unread,
    get_chat_room,
    get_agent_chat_room,
    fetch_chat_file_bytes,
    extract_preview_references,
    get_chat_message,
    get_internal_room,
    internal_agent_avatar,
    is_kind_enabled,
    kind_from_mime,
    list_internal_agents,
    list_chat_identity_mappings,
    list_chat_message_agent_ids,
    list_chat_viewer_agents,
    list_chat_messages,
    list_chat_rooms,
    mark_chat_room_read,
    set_chat_room_archived,
    set_chat_room_muted,
    update_chat_room_preferences,
    update_chat_room_topic,
    publish_internal_message,
    reassign_chat_message_topic,
    materialize_preview_resource,
    preview_image,
    preview_reference,
    preview_references,
    set_chat_identity_mapping,
)
from app.messenger.interface import ObservedMessengerFile
from app.conversation import (
    ConversationActivityDetail,
    ConversationActivityPage,
    ConversationDocumentList,
    ConversationDocument,
    ConversationProcessList,
    ConversationTaskTree,
    get_agent_chat_directives,
    get_room_activity_detail,
    list_room_activity,
    list_room_documents,
    create_conversation_room_document,
    list_room_processes,
    list_room_tasks,
)

from . import storage
from . import html_preview
from .document_previews import with_deleted_document_previews
from .assertions import (
    ChatRoomAccessAssertion,
    ChatScopeAssertion,
    InternalRoomAccessAssertion,
)
from .emoji_service import (
    FREQUENT_EMOJI_LIMIT,
    list_frequent_emojis,
    record_emoji_use,
)
from .thumbnail_service import schedule_html_thumbnail
from .schemas import (
    InteractionAnswer,
    ActiveCall,
    ArchiveUpdate,
    ChatCommandCatalog,
    ChatInboxSummary,
    ConversationDocumentCreate,
    ChatStatus,
    DictationResult,
    EmojiUse,
    FrequentEmojiList,
    HtmlPreviewTicket,
    IdentityMappingUpdate,
    MessageCreate,
    MessageSpeechStatus,
    MessageTopicUpdate,
    MessageTopicUpdateResult,
    MuteUpdate,
    MutationResult,
    NativeMessengerMessage,
    NativeMessengerMessagePage,
    NativeMessengerIdentityMapping,
    NativeMessengerRoom,
    NativeMessengerRoomPage,
    ReadMarker,
    PushConfiguration,
    PushSubscriptionCreate,
    PushSubscriptionDelete,
    PushSubscriptionRead,
    ReasoningEffort,
    RecipientCatalog,
    RoomCreate,
    RoomPreferencesUpdate,
    RoomTopicUpdate,
    WebRtcAnswer,
    WebRtcIceCandidate,
    WebRtcIceCandidateBatch,
    WebRtcIceServer,
    WebRtcOffer,
    VoiceCallStatus,
)
from .events import ChatRoom
from .push_service import (
    delete_push_subscription,
    push_configuration,
    upsert_push_subscription,
)
from .webrtc import (
    BrowserCallTransport,
    browser_answer_with_embedded_relay_alias,
    browser_answer_network_available,
    browser_call_network_available,
    browser_ice_servers,
    browser_rtc_configuration,
)
from app.voice import (
    VoiceSynthesisFailed,
    VoiceSynthesisUnavailable,
    VoiceTranscriptionFailed,
    VoiceTranscriptionUnavailable,
    agent_voice_call_available,
    agent_voice_synthesis_available,
    synthesize_agent_message,
    transcribe_voice_audio,
    voice_call_manager,
)
from app.topic import service as topic_service


ACCESS = "CHAT_ACCESS"
SEND = "CHAT_SEND"
MANAGE = "CHAT_MANAGE"
CALL = "CHAT_CALL"
IMPERSONATE = "CHAT_IMPERSONATE"
TOPIC_EDIT = "TOPIC_EDIT"
_MAX_DICTATION_SEGMENT_BYTES = 2_000_000
_DICTATION_MIME_TYPES = {
    "audio/mp4",
    "audio/ogg",
    "audio/webm",
}

router = APIRouter(prefix="/chat", tags=["chat"])

_HTML_PREVIEW_CSP = (
    "sandbox allow-scripts allow-forms allow-modals allow-popups "
    "allow-popups-to-escape-sandbox allow-downloads allow-presentation; "
    "default-src * data: blob: 'unsafe-inline'; "
    "script-src * data: blob: 'unsafe-inline' 'unsafe-eval'; "
    "style-src * data: blob: 'unsafe-inline'; "
    "connect-src * data: blob: ws: wss:; img-src * data: blob:; "
    "font-src * data: blob:; media-src * data: blob:; "
    "worker-src * data: blob:; frame-src * data: blob:"
    "; frame-ancestors 'self'"
)


def _room_for_scope(
    room: NativeMessengerRoom,
    scope: AgentManagementScope,
) -> NativeMessengerRoom:
    return room.model_copy(
        update={
            "writable": room.writable and scope.allows(room.agent_id),
            "members": [
                member
                for member in room.members
                if member.agent_id is None or scope.allows(member.agent_id)
            ]
        }
    )


def _message_preview_references(
    message: NativeMessengerMessage,
) -> tuple[str, ...]:
    """Allow private file providers only for content published by the agent."""

    return extract_preview_references(
        message.text,
        include_file_resources=message.direction == "outbound",
    )


def _message_preview_content_references(
    message: NativeMessengerMessage,
) -> tuple[str, ...]:
    """Limit full file responses to public HTTPS or agent-published file providers."""

    return tuple(
        uri
        for uri in _message_preview_references(message)
        if uri.partition("://")[0] == "https"
        or (
            message.direction == "outbound"
            and uri.partition("://")[0] not in {"document", "memory", "galaris"}
        )
    )


async def _user_id() -> int:
    user = await user_service.get_current_user()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user.id


def _require_enabled() -> None:
    if not is_kind_enabled("internal"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat is disabled.",
        )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")


def _attachment_error(exc: storage.AttachmentStorageError) -> HTTPException:
    """Translate expected storage rejections without exposing them as HTTP 500 errors."""

    if isinstance(exc, storage.AttachmentTooLargeError):
        return HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc))
    if isinstance(exc, storage.UnsupportedAttachmentTypeError):
        return HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))
    if isinstance(exc, storage.AttachmentStorageFullError):
        return HTTPException(status_code=507, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post("/html-previews", response_model=HtmlPreviewTicket)
@authorize(privileges=ACCESS)
async def create_standalone_html_preview(file: UploadFile = File(...)) -> HtmlPreviewTicket:
    try:
        ticket = await html_preview.store(file)
    except (html_preview.HtmlPreviewTooLargeError, storage.AttachmentStorageFullError) as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except html_preview.HtmlPreviewError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    return HtmlPreviewTicket(
        url=f"/api/chat/html-previews/{ticket.hex}",
        expires_in=html_preview.TTL_SECONDS,
    )


@router.get("/html-previews/{ticket}", response_class=FileResponse)
@independent_auth(reason="Unguessable, short-lived HTML preview capability ticket")
async def read_standalone_html_preview(ticket: UUID) -> FileResponse:
    path = await html_preview.resolve(ticket)
    if path is None:
        raise _not_found()
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": _HTML_PREVIEW_CSP,
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "SAMEORIGIN",
        },
    )


async def _validate_topic(topic_id: UUID | None) -> None:
    if topic_id is not None and await topic_service.get(topic_id) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Topic not found.")


@router.get("/status", response_model=ChatStatus)
@authorize(privileges=ACCESS)
async def read_status() -> ChatStatus:
    return ChatStatus(
        enabled=True,
        chat_enabled=is_kind_enabled("internal"),
        max_attachment_bytes=runtime_settings.messenger_content_max_bytes,
    )


@router.get("/inbox", response_model=ChatInboxSummary)
@authorize(privileges=ACCESS)
async def read_inbox() -> ChatInboxSummary:
    return ChatInboxSummary(unread_count=await count_chat_unread(await _user_id()))


@router.get("/push/configuration", response_model=PushConfiguration)
@authorize(privileges=ACCESS)
async def read_push_configuration() -> PushConfiguration:
    return push_configuration()


@router.post(
    "/push/subscriptions",
    response_model=PushSubscriptionRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=ACCESS)
async def create_push_subscription(
    data: PushSubscriptionCreate,
) -> PushSubscriptionRead:
    try:
        return await upsert_push_subscription(await _user_id(), data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/push/subscriptions", response_model=MutationResult)
@authorize(privileges=ACCESS)
async def remove_push_subscription(data: PushSubscriptionDelete) -> MutationResult:
    try:
        await delete_push_subscription(await _user_id(), data.endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MutationResult()


@router.get("/emojis/frequent", response_model=FrequentEmojiList)
@authorize(privileges=ACCESS)
async def read_frequent_emojis() -> FrequentEmojiList:
    return FrequentEmojiList(
        items=list(await list_frequent_emojis(await _user_id())),
        limit=FREQUENT_EMOJI_LIMIT,
    )


@router.post("/emojis/usage", response_model=FrequentEmojiList)
@authorize(privileges=ACCESS)
async def create_emoji_usage(data: EmojiUse) -> FrequentEmojiList:
    try:
        items = await record_emoji_use(await _user_id(), data.emoji)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FrequentEmojiList(items=list(items), limit=FREQUENT_EMOJI_LIMIT)


@router.get("/identities", response_model=list[NativeMessengerIdentityMapping])
@authorize(privileges=ACCESS)
async def read_identity_mappings() -> list[NativeMessengerIdentityMapping]:
    return await list_chat_identity_mappings(await _user_id())


@router.put(
    "/identities/{tool_id}",
    response_model=NativeMessengerIdentityMapping,
)
@authorize(privileges=ACCESS)
async def update_identity_mapping(
    tool_id: int,
    data: IdentityMappingUpdate,
) -> NativeMessengerIdentityMapping:
    try:
        mapping = await set_chat_identity_mapping(
            await _user_id(),
            tool_id,
            data.external_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if mapping is None:
        raise _not_found()
    return mapping


@router.delete("/identities/{tool_id}", response_model=MutationResult)
@authorize(privileges=ACCESS)
async def delete_identity_mapping(tool_id: int) -> MutationResult:
    await clear_chat_identity_mapping(await _user_id(), tool_id)
    return MutationResult()


@router.get("/recipients", response_model=RecipientCatalog)
@authorize(privileges=ACCESS)
async def read_recipients(
    search: str = Query(default="", max_length=200),
) -> RecipientCatalog:
    _require_enabled()
    normalized = search.strip().lower()
    scope = await current_dialogue_scope()
    agents = [
        agent
        for agent in await list_internal_agents(agent_ids=scope.agent_ids)
        if agent.active
    ]
    if normalized:
        agents = [
            agent
            for agent in agents
            if normalized in agent.display_name.lower() or normalized in agent.code.lower()
        ]
    return RecipientCatalog(agents=agents)


@router.get("/viewer-agents", response_model=list[ChatViewerAgent])
@authorize(privileges=IMPERSONATE)
async def read_viewer_agents() -> list[ChatViewerAgent]:
    scope = await current_management_scope()
    return await list_chat_viewer_agents(agent_ids=scope.agent_ids)


@router.get("/agents/{agent_id}/avatar", response_class=Response)
@authorize(privileges=ACCESS, assertion=AgentDialogueAssertion)
async def read_agent_avatar(agent_id: int) -> Response:
    content = await internal_agent_avatar(agent_id)
    if content is None:
        raise _not_found()
    media_type = "image/jpeg"
    if content.startswith(b"\x89PNG"):
        media_type = "image/png"
    elif content.startswith((b"GIF87a", b"GIF89a")):
        media_type = "image/gif"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        media_type = "image/webp"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/rooms", response_model=NativeMessengerRoomPage)
@authorize(privileges=ACCESS, assertion=ChatScopeAssertion)
async def read_rooms(
    agent_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    search: str = Query(default="", max_length=200),
    include_external: bool = Query(default=True),
    include_archived: bool = Query(default=False),
) -> NativeMessengerRoomPage:
    scope = await current_management_scope() if agent_id is not None else await current_dialogue_scope()
    result = await list_chat_rooms(
        await _user_id(),
        agent_id=agent_id,
        page=page,
        page_size=page_size,
        search=search,
        include_external=include_external,
        include_archived=include_archived,
        agent_ids=scope.agent_ids if agent_id is not None else None,
    )
    return result.model_copy(update={"items": [_room_for_scope(room, scope) for room in result.items]})


@router.post("/rooms", response_model=NativeMessengerRoom, status_code=201)
@authorize(privileges=MANAGE)
async def create_room(data: RoomCreate) -> NativeMessengerRoom:
    _require_enabled()
    scope = await current_dialogue_scope()
    if not scope.allows(data.agent_id):
        raise _not_found()
    if data.topic_id is not None:
        current_user = await user_service.get_current_user()
        if current_user is None or not await check_privilege(
            current_user,
            TOPIC_EDIT,
            get_db(),
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        await _validate_topic(data.topic_id)
    room = await create_internal_room(
        actor_user_id=await _user_id(),
        agent_id=data.agent_id,
        label=data.label,
        topic_id=data.topic_id,
        show_last_message=data.show_last_message,
    )
    if room is None:
        raise _not_found()
    return _room_for_scope(room, scope)


@router.get("/rooms/{room_id}", response_model=NativeMessengerRoom)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def read_room(
    room_id: UUID,
    agent_id: int | None = Query(default=None, ge=1),
) -> NativeMessengerRoom:
    room = (
        await get_agent_chat_room(agent_id, room_id)
        if agent_id is not None
        else await get_chat_room(await _user_id(), room_id)
    )
    if room is None:
        raise _not_found()
    scope = await current_dialogue_scope()
    return _room_for_scope(room, scope)


@router.patch("/rooms/{room_id}", response_model=NativeMessengerRoom)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def update_room_preferences(
    room_id: UUID,
    data: RoomPreferencesUpdate,
) -> NativeMessengerRoom:
    room = await update_chat_room_preferences(
        await _user_id(),
        room_id,
        label=data.label,
        show_last_message=data.show_last_message,
    )
    if room is None:
        raise _not_found()
    scope = await current_dialogue_scope()
    return _room_for_scope(room, scope)


@router.patch("/rooms/{room_id}/archive", response_model=NativeMessengerRoom)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def update_room_archive(
    room_id: UUID,
    data: ArchiveUpdate,
) -> NativeMessengerRoom:
    room = await set_chat_room_archived(
        await _user_id(),
        room_id,
        data.archived,
    )
    if room is None:
        raise _not_found()
    scope = await current_dialogue_scope()
    return _room_for_scope(room, scope)


@router.patch("/rooms/{room_id}/topic", response_model=NativeMessengerRoom)
@authorize(privileges=TOPIC_EDIT, assertion=ChatRoomAccessAssertion)
async def update_room_topic(
    room_id: UUID,
    data: RoomTopicUpdate,
) -> NativeMessengerRoom:
    await _validate_topic(data.topic_id)
    room = await update_chat_room_topic(
        await _user_id(),
        room_id,
        topic_id=data.topic_id,
    )
    if room is None:
        raise _not_found()
    await websocket.emit(
        "chat",
        "message",
        {"room_id": str(room_id), "is_new": False},
        room=ChatRoom(room_id),
    )
    scope = await current_dialogue_scope()
    return _room_for_scope(room, scope)


@router.get("/rooms/{room_id}/commands", response_model=ChatCommandCatalog)
@authorize(privileges=ACCESS, assertion=InternalRoomAccessAssertion)
async def read_room_commands(room_id: UUID) -> ChatCommandCatalog:
    """Return deterministic composer commands supported by this room's agent."""

    room = await get_internal_room(await _user_id(), room_id)
    if room is None:
        raise _not_found()
    commands = await get_agent_chat_directives(room.agent_id)
    if commands is None:
        raise _not_found()
    return ChatCommandCatalog(commands=list(commands))


@router.get("/rooms/{room_id}/messages", response_model=NativeMessengerMessagePage)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def read_messages(
    room_id: UUID,
    agent_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    history_cursor: str | None = Query(default=None, max_length=512),
) -> NativeMessengerMessagePage:
    result = await list_chat_messages(
        await _user_id(),
        room_id,
        agent_id=agent_id,
        page=page,
        page_size=page_size,
        history_cursor=history_cursor,
    )
    if result is None:
        raise _not_found()
    return result


@router.get(
    "/rooms/{room_id}/speech/status",
    response_model=MessageSpeechStatus,
)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def read_message_speech_status(
    room_id: UUID,
    agent_id: int | None = Query(default=None, ge=1),
) -> MessageSpeechStatus:
    agent_ids = await list_chat_message_agent_ids(
        await _user_id(),
        room_id,
        agent_id=agent_id,
    )
    if agent_ids is None:
        raise _not_found()
    scope = await current_dialogue_scope()
    available_agent_ids: list[int] = []
    for speaker_agent_id in agent_ids:
        if scope.allows(speaker_agent_id) and await agent_voice_synthesis_available(
            speaker_agent_id
        ):
            available_agent_ids.append(speaker_agent_id)
    return MessageSpeechStatus(available_agent_ids=available_agent_ids)


@router.post(
    "/rooms/{room_id}/messages/{message_id}/speech",
    response_class=StreamingResponse,
)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def read_message_speech(
    room_id: UUID,
    message_id: UUID,
    agent_id: int | None = Query(default=None, ge=1),
    language: str = Query(default="", max_length=10),
) -> StreamingResponse:
    user_id = await _user_id()
    message = await get_chat_message(
        user_id,
        room_id,
        message_id,
        agent_id=agent_id,
    )
    if message is None:
        raise _not_found()
    sender = message.sender
    if sender is None or not sender.is_ai or sender.agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only messages authored by a configured agent can be synthesized.",
        )
    if not (await current_dialogue_scope()).allows(sender.agent_id):
        raise _not_found()
    text = message.text.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The message has no text to synthesize.",
        )
    if len(text) > 10_000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The message is too long for voice synthesis.",
        )
    try:
        audio = await synthesize_agent_message(
            sender.agent_id,
            text,
            language=language,
        )
    except VoiceSynthesisUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice synthesis is not configured.",
        ) from exc
    except VoiceSynthesisFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Voice synthesis failed.",
        ) from exc

    async def stream_audio() -> AsyncIterator[bytes]:
        chunk_size = 64 * 1024
        for offset in range(0, len(audio), chunk_size):
            yield audio[offset : offset + chunk_size]

    return StreamingResponse(
        stream_audio(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, no-store"},
    )


@router.patch(
    "/rooms/{room_id}/messages/{message_id}/topic",
    response_model=MessageTopicUpdateResult,
)
@authorize(privileges=TOPIC_EDIT, assertion=ChatRoomAccessAssertion)
async def update_message_topic(
    room_id: UUID,
    message_id: UUID,
    data: MessageTopicUpdate,
    agent_id: int | None = Query(default=None, ge=1),
) -> MessageTopicUpdateResult:
    del agent_id
    await _validate_topic(data.topic_id)
    updated = await reassign_chat_message_topic(
        room_id,
        message_id,
        data.topic_id,
        include_following_same_topic=data.scope == "following_same_topic",
    )
    if updated is None:
        raise _not_found()
    if updated:
        await websocket.emit(
            "chat",
            "message",
            {"room_id": str(room_id), "message_id": str(message_id), "is_new": False},
            room=ChatRoom(room_id),
        )
    return MessageTopicUpdateResult(updated_messages=updated)


@router.get(
    "/rooms/{room_id}/messages/{message_id}/previews",
    response_model=list[MessageResourcePreview],
)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def read_message_previews(
    room_id: UUID,
    message_id: UUID,
    agent_id: int | None = Query(default=None, ge=1),
) -> list[MessageResourcePreview]:
    user_id = await _user_id()
    message = await get_chat_message(
        user_id,
        room_id,
        message_id,
        agent_id=agent_id,
    )
    room = (
        await get_agent_chat_room(agent_id, room_id)
        if agent_id is not None
        else await get_chat_room(user_id, room_id)
    )
    if message is None or room is None:
        raise _not_found()
    references = _message_preview_references(message)
    previews = await preview_references(
        references,
        agent_id=room.agent_id,
    )
    previews = await with_deleted_document_previews(references, previews)
    for preview in previews:
        if preview.open_mode == "external" and preview.external_url is not None:
            metadata = await read_cached_page_metadata(reference=preview.external_url)
            if metadata is not None:
                preview.title = metadata.title or preview.title
                preview.description = preview.description or metadata.description
                preview.subtitle = metadata.site_name or preview.subtitle
            schedule_public_page_thumbnail(
                agent_id=room.agent_id,
                url=preview.external_url,
            )
        elif (
            preview.open_mode == "inline"
            and preview.download_available
            and preview.media_type.split(";", 1)[0].strip().casefold()
            in {"text/html", "application/xhtml+xml"}
        ):
            schedule_html_thumbnail(agent_id=room.agent_id, uri=preview.uri)
    return previews


@router.get(
    "/rooms/{room_id}/messages/{message_id}/previews/image",
    response_class=Response,
)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def read_message_preview_image(
    room_id: UUID,
    message_id: UUID,
    uri: str = Query(min_length=1, max_length=2_048),
    agent_id: int | None = Query(default=None, ge=1),
) -> Response:
    user_id = await _user_id()
    message = await get_chat_message(
        user_id,
        room_id,
        message_id,
        agent_id=agent_id,
    )
    room = (
        await get_agent_chat_room(agent_id, room_id)
        if agent_id is not None
        else await get_chat_room(user_id, room_id)
    )
    if (
        message is None
        or room is None
        or uri not in _message_preview_references(message)
    ):
        raise _not_found()
    preview = await preview_reference(uri, agent_id=room.agent_id)
    if preview is None:
        raise _not_found()
    image = (
        await read_cached_thumbnail(reference=preview.external_url)
        if preview.open_mode == "external" and preview.external_url is not None
        else (
            await read_cached_thumbnail(reference=uri)
            if preview.download_available
            and preview.media_type.split(";", 1)[0].strip().casefold()
            in {"text/html", "application/xhtml+xml"}
            else await preview_image(uri)
        )
    )
    if image is None:
        raise _not_found()
    content, media_type = image
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get(
    "/rooms/{room_id}/messages/{message_id}/previews/content",
    response_class=FileResponse,
)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def read_message_preview_content(
    room_id: UUID,
    message_id: UUID,
    uri: str = Query(min_length=1, max_length=2_048),
    agent_id: int | None = Query(default=None, ge=1),
) -> FileResponse:
    user_id = await _user_id()
    message = await get_chat_message(
        user_id,
        room_id,
        message_id,
        agent_id=agent_id,
    )
    room = (
        await get_agent_chat_room(agent_id, room_id)
        if agent_id is not None
        else await get_chat_room(user_id, room_id)
    )
    if (
        message is None
        or room is None
        or uri not in _message_preview_content_references(message)
    ):
        raise _not_found()
    resource = await materialize_preview_resource(uri, agent_id=room.agent_id)
    if resource is None:
        raise _not_found()
    return FileResponse(
        resource.path,
        media_type=resource.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
        background=BackgroundTask(resource.cleanup),
    )


@router.get("/rooms/{room_id}/activity", response_model=ConversationActivityPage)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def read_activity(
    room_id: UUID,
    agent_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> ConversationActivityPage:
    del agent_id
    return await list_room_activity(room_id, page=page, page_size=page_size)


@router.get(
    "/rooms/{room_id}/activity/{round_id}",
    response_model=ConversationActivityDetail,
)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def read_activity_detail(
    room_id: UUID,
    round_id: UUID,
    agent_id: int | None = Query(default=None, ge=1),
) -> ConversationActivityDetail:
    del agent_id
    detail = await get_room_activity_detail(room_id, round_id)
    if detail is None:
        raise _not_found()
    return detail


@router.get("/rooms/{room_id}/tasks", response_model=ConversationTaskTree)
@authorize(
    privileges=["TASK_ACCESS", "TASK_EDIT"],
    assertion=ChatRoomAccessAssertion,
)
async def read_room_tasks(
    room_id: UUID,
    agent_id: int | None = Query(default=None, ge=1),
    from_message_id: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=500),
) -> ConversationTaskTree:
    del agent_id
    return await list_room_tasks(
        room_id,
        from_message_id,
        page=page,
        page_size=page_size,
    )


@router.get("/rooms/{room_id}/documents", response_model=ConversationDocumentList)
@authorize(
    privileges=["MEMORY_ACCESS", "MEMORY_EDIT", "MEMORY_ADMIN"],
    assertion=ChatRoomAccessAssertion,
)
async def read_room_documents(
    room_id: UUID,
    from_message_id: UUID = Query(),
    agent_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=500),
) -> ConversationDocumentList:
    user_id = await _user_id()
    room = (
        await get_agent_chat_room(agent_id, room_id)
        if agent_id is not None
        else await get_chat_room(user_id, room_id)
    )
    if room is None:
        raise _not_found()
    return await list_room_documents(
        room_id,
        from_message_id,
        agent_id=room.agent_id,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/rooms/{room_id}/documents",
    response_model=ConversationDocument,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges="MEMORY_EDIT", assertion=ChatRoomAccessAssertion)
async def create_room_document(
    room_id: UUID,
    data: ConversationDocumentCreate,
) -> ConversationDocument:
    """Create an empty document durably attached to this Chat room."""

    room = await get_chat_room(await _user_id(), room_id)
    if room is None:
        raise _not_found()
    metadata = await create_conversation_room_document(
        room_id,
        room.agent_id,
        data.title,
    )
    return ConversationDocument(
        id=metadata.id,
        uri=f"document://{metadata.id}",
        label=metadata.title,
        revision=metadata.revision,
        updated_at=metadata.updated_at,
    )


@router.get("/rooms/{room_id}/processes", response_model=ConversationProcessList)
@authorize(
    privileges=["PROCESS_READ", "PROCESS_LAUNCH", "PROCESS_ADMIN"],
    assertion=ChatRoomAccessAssertion,
)
async def read_room_processes(
    room_id: UUID,
    from_message_id: UUID = Query(),
    agent_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=500),
) -> ConversationProcessList:
    del agent_id
    return await list_room_processes(
        room_id,
        from_message_id,
        page=page,
        page_size=page_size,
    )


@router.get("/rooms/{room_id}/interactions/{interaction_id}", response_model=NativeMessengerInteraction)
@authorize(privileges=ACCESS, assertion=InternalRoomAccessAssertion)
async def read_interaction(room_id: UUID, interaction_id: UUID) -> NativeMessengerInteraction:
    try:
        return await read_internal_interaction(await _user_id(), room_id, interaction_id)
    except LookupError as exc:
        raise _not_found() from exc


@router.post("/rooms/{room_id}/interactions/{interaction_id}/answer", response_model=NativeMessengerInteraction)
@authorize(privileges=SEND, assertion=InternalRoomAccessAssertion)
async def answer_interaction(
    room_id: UUID, interaction_id: UUID, data: InteractionAnswer,
) -> NativeMessengerInteraction:
    _require_enabled()
    try:
        return await answer_internal_interaction(
            await _user_id(), room_id, interaction_id, option_id=data.option_id,
        )
    except LookupError as exc:
        raise _not_found() from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/rooms/{room_id}/messages", response_model=NativeMessengerMessage, status_code=201)
@authorize(privileges=SEND, assertion=InternalRoomAccessAssertion)
async def create_message(room_id: UUID, data: MessageCreate) -> NativeMessengerMessage:
    _require_enabled()
    await _validate_topic(data.topic_id)
    try:
        result = await publish_internal_message(
            user_id=await _user_id(),
            room_id=room_id,
            client_message_id=data.client_message_id,
            text=data.text,
            topic_id=data.topic_id,
            reply_to_message_id=data.reply_to_message_id,
            reasoning_effort_override=data.reasoning_effort_override,
            task_requested=data.task_requested,
            displayed_document_id=data.displayed_document_id,
            language=data.language or await current_language(),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise _not_found()
    return result


@router.post("/rooms/{room_id}/dictation", response_model=DictationResult)
@authorize(privileges=SEND, assertion=InternalRoomAccessAssertion)
async def transcribe_dictation(
    room_id: UUID,
    audio: UploadFile = File(...),
    language: str = Form(default="", max_length=10),
) -> DictationResult:
    """Transcribe one short-lived browser microphone segment."""

    _require_enabled()
    room = await get_internal_room(await _user_id(), room_id)
    if room is None or not room.agent_active:
        raise _not_found()
    mime_type = (audio.content_type or "").partition(";")[0].strip().lower()
    if mime_type not in _DICTATION_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported dictation audio type.",
        )
    content = await audio.read(_MAX_DICTATION_SEGMENT_BYTES + 1)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The dictation audio segment is empty.",
        )
    if len(content) > _MAX_DICTATION_SEGMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="The dictation audio segment is too large.",
        )
    try:
        transcript = await transcribe_voice_audio(
            content,
            filename=(audio.filename or f"dictation.{mime_type.rsplit('/', 1)[-1]}")[:512],
            mime_type=mime_type,
            language=language,
            agent_id=room.agent_id,
        )
    except VoiceTranscriptionUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice transcription is not configured.",
        ) from exc
    except VoiceTranscriptionFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Voice transcription failed.",
        ) from exc
    return DictationResult(text=transcript)


@router.post("/rooms/{room_id}/attachments", response_model=NativeMessengerMessage, status_code=201)
@authorize(privileges=SEND, assertion=InternalRoomAccessAssertion)
async def create_attachment_message(
    room_id: UUID,
    files: list[UploadFile] = File(..., min_length=1, max_length=20),
    client_message_id: UUID = Form(...),
    text: str = Form(default="", max_length=100_000),
    topic_id: UUID | None = Form(default=None),
    reply_to_message_id: UUID | None = Form(default=None),
    reasoning_effort_override: ReasoningEffort | None = Form(default=None),
    task_requested: bool = Form(default=False),
    displayed_document_id: UUID | None = Form(default=None),
    language: str = Form(default="", max_length=10),
) -> NativeMessengerMessage:
    _require_enabled()
    await _validate_topic(topic_id)
    room = await get_internal_room(await _user_id(), room_id)
    if room is None or not room.agent_active:
        raise _not_found()
    observations: list[ObservedMessengerFile] = []
    stored_file_ids: list[UUID] = []
    try:
        for file in files:
            file_id = uuid4()
            _path, size, mime_type = await storage.store_upload(file, file_id)
            stored_file_ids.append(file_id)
            observations.append(
                ObservedMessengerFile(
                    id=str(file_id),
                    local_id=file_id,
                    name=(file.filename or str(file_id))[:512],
                    mime=mime_type,
                    size=size,
                    kind=kind_from_mime(mime_type),
                )
            )
    except storage.AttachmentStorageError as exc:
        for file_id in stored_file_ids:
            await storage.discard(file_id)
        raise _attachment_error(exc) from exc
    except BaseException:
        for file_id in stored_file_ids:
            await storage.discard(file_id)
        raise
    try:
        result = await publish_internal_message(
            user_id=await _user_id(),
            room_id=room_id,
            client_message_id=client_message_id,
            text=text,
            topic_id=topic_id,
            reply_to_message_id=reply_to_message_id,
            attachments=observations,
            reasoning_effort_override=reasoning_effort_override,
            task_requested=task_requested,
            displayed_document_id=displayed_document_id,
            language=language or await current_language(),
        )
    except BaseException:
        # Admission may fail after the canonical message/file row was committed. The
        # reconciler removes a truly orphaned blob after its grace period; deleting here
        # would corrupt a durable failed-admission message.
        raise
    if result is None:
        for file_id in stored_file_ids:
            await storage.discard(file_id)
        raise _not_found()
    return result


@router.post("/rooms/{room_id}/read", response_model=MutationResult)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def mark_read(room_id: UUID, data: ReadMarker) -> MutationResult:
    if not await mark_chat_room_read(await _user_id(), room_id, data.message_id):
        raise _not_found()
    return MutationResult()


@router.post("/rooms/{room_id}/mute", response_model=MutationResult)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def set_muted(room_id: UUID, data: MuteUpdate) -> MutationResult:
    if not await set_chat_room_muted(await _user_id(), room_id, data.muted):
        raise _not_found()
    return MutationResult()


@router.get("/rooms/{room_id}/files/{file_id}", response_class=Response)
@authorize(privileges=ACCESS, assertion=ChatRoomAccessAssertion)
async def download_file(
    room_id: UUID,
    file_id: UUID,
    agent_id: int | None = Query(default=None, ge=1),
) -> Response:
    user_id = await _user_id()
    access = await chat_file_access(
        user_id,
        room_id,
        file_id,
        agent_id=agent_id,
    )
    if access is None:
        raise _not_found()
    room = (
        await get_agent_chat_room(agent_id, room_id)
        if agent_id is not None
        else await get_chat_room(user_id, room_id)
    )
    if room is None:
        raise _not_found()
    if room.source is None:
        path = storage.attachment_path(file_id)
        if not path.is_file() or path.is_symlink():
            raise _not_found()
        return FileResponse(Path(path), media_type=access.mime_type, filename=access.name)
    fetched = await fetch_chat_file_bytes(
        user_id,
        room_id,
        file_id,
        agent_id=agent_id,
    )
    if fetched is None:
        raise _not_found()
    _metadata, content = fetched
    return Response(
        content=content,
        media_type=access.mime_type or "application/octet-stream",
    )


@router.get("/rooms/{room_id}/calls/status", response_model=VoiceCallStatus)
@authorize(privileges=CALL)
async def read_voice_call_status(room_id: UUID) -> VoiceCallStatus:
    user_id = await _user_id()
    room = await get_internal_room(user_id, room_id)
    if room is None:
        raise _not_found()
    network_available = browser_call_network_available()
    available = (
        room.agent_active
        and network_available
        and await agent_voice_call_available(room.agent_id)
    )
    ice_servers = browser_ice_servers(f"user:{user_id}") if network_available else ()
    return VoiceCallStatus(
        available=available,
        ice_servers=[
            WebRtcIceServer(
                urls=list(server.urls),
                username=server.username,
                credential=server.credential,
            )
            for server in ice_servers
        ],
    )


@router.post("/rooms/{room_id}/calls", response_model=WebRtcAnswer, status_code=201)
@authorize(privileges=CALL)
async def start_call(room_id: UUID, data: WebRtcOffer) -> WebRtcAnswer:
    _require_enabled()
    user_id = await _user_id()
    room = await get_internal_room(user_id, room_id)
    if room is None or not room.agent_active:
        raise _not_found()
    if (
        not browser_call_network_available()
        or not await agent_voice_call_available(room.agent_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent voice calling is not configured.",
        )
    remote_user_id = f"user:{user_id}"
    transport = BrowserCallTransport(
        remote_user_id,
        configuration=browser_rtc_configuration(remote_user_id),
        user_id=user_id,
    )
    try:
        answer_sdp, answer_type = await transport.accept_offer(data.sdp, data.type)
        answer_sdp = browser_answer_with_embedded_relay_alias(answer_sdp)
        if not browser_answer_network_available(answer_sdp):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The voice relay is temporarily unavailable.",
            )
        info, created = voice_call_manager.start_agent_call(
            agent_id=room.agent_id,
            connection_id=room.connection_id,
            room_id=room.external_id,
            transport=transport,
            language=data.language,
            remote_user_ids=(remote_user_id,),
            conversation_room_id=room.id,
        )
    except BaseException:
        await transport.leave(transport)
        raise
    if not created:
        await transport.leave(transport)
        raise HTTPException(status_code=409, detail="A voice call is already active.")
    await websocket.emit(
        "chat",
        "call",
        {"room_id": str(room_id), "call_id": info.call_id, "status": "active"},
        room=ChatRoom(room_id),
    )
    return WebRtcAnswer(
        call_id=info.call_id,
        sdp=answer_sdp,
        type=answer_type,
        created=created,
    )


@router.get("/rooms/{room_id}/calls/active", response_model=ActiveCall | None)
@authorize(privileges=CALL)
async def read_active_call(room_id: UUID) -> ActiveCall | None:
    room = await get_internal_room(await _user_id(), room_id)
    if room is None:
        raise _not_found()
    active = next(
        (
            item
            for item in voice_call_manager.active_calls(agent_id=room.agent_id)
            if item.connection_id == room.connection_id and item.room_id == room.external_id
        ),
        None,
    )
    return (
        ActiveCall(call_id=active.call_id, started_at=active.started_at)
        if active is not None
        else None
    )


@router.post(
    "/rooms/{room_id}/calls/{call_id}/candidates",
    response_model=MutationResult,
)
@authorize(privileges=CALL)
async def add_call_candidate(
    room_id: UUID,
    call_id: str,
    data: WebRtcIceCandidate | WebRtcIceCandidateBatch,
) -> MutationResult:
    """Trickle a bounded batch of ICE routes; keep older single-route clients."""

    room = await get_internal_room(await _user_id(), room_id)
    if room is None:
        raise _not_found()
    active = next(
        (
            item
            for item in voice_call_manager.active_calls(agent_id=room.agent_id)
            if item.call_id == call_id
            and item.connection_id == room.connection_id
            and item.room_id == room.external_id
        ),
        None,
    )
    transport = voice_call_manager.active_transport(call_id)
    if active is None or not isinstance(transport, BrowserCallTransport):
        raise _not_found()
    candidates = data.candidates if isinstance(data, WebRtcIceCandidateBatch) else [data]
    for candidate in candidates:
        await transport.add_remote_candidate(
            candidate.candidate,
            sdp_mid=candidate.sdp_mid,
            sdp_m_line_index=candidate.sdp_m_line_index,
        )
    return MutationResult()


@router.delete("/rooms/{room_id}/calls/{call_id}", response_model=MutationResult)
@authorize(privileges=CALL)
async def stop_call(room_id: UUID, call_id: str) -> MutationResult:
    room = await get_internal_room(await _user_id(), room_id)
    if room is None:
        raise _not_found()
    active = next(
        (
            item
            for item in voice_call_manager.active_calls(agent_id=room.agent_id)
            if item.call_id == call_id
            and item.connection_id == room.connection_id
            and item.room_id == room.external_id
        ),
        None,
    )
    # Closing the local RTCPeerConnection is deliberately immediate on mobile.
    # It can therefore win the race against this request and remove the runtime
    # call first; treating that state as success makes hangup idempotent.
    if active is None:
        return MutationResult()
    if not await voice_call_manager.request_stop_call(call_id):
        return MutationResult()
    await websocket.emit(
        "chat",
        "call",
        {"room_id": str(room_id), "call_id": call_id, "status": "stopping"},
        room=ChatRoom(room_id),
    )
    return MutationResult()
