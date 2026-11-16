"""Private autosave snapshots with optimistic concurrency and durable file references."""
from uuid import UUID

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from core.database import get_db
from core.user import current_web_session_family
from core.storage import StoredFile, register_file, retire_file_reference
from app.messenger.interface import ObservedMessengerFile
from app.messenger import kind_from_mime
from .models import ChatDraft, ChatDraftFile
from . import storage


class DraftFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: UUID
    name: str = Field(max_length=512)
    size: int = Field(ge=0)
    mime: str = Field(max_length=255)
    uploaded: bool = False


class DraftResource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uri: str = Field(max_length=8192)
    name: str = Field(max_length=512)


class DraftContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_message_id: UUID
    text: str = Field(default="", max_length=100_000)
    files: list[DraftFile] = Field(default_factory=list[DraftFile], max_length=20)
    resources: list[DraftResource] = Field(default_factory=list[DraftResource], max_length=20)
    effort: int = Field(default=2, ge=0, le=5)
    topic_id: UUID | None = None
    reply_to_message_id: UUID | None = None


class DraftSnapshot(BaseModel):
    revision: int
    content: DraftContent | None = None


class DraftWrite(BaseModel):
    expected_revision: int = Field(ge=0)
    mutation_key: UUID
    content: DraftContent | None


class DraftConflict(ValueError):
    pass


class DraftFileUnavailable(DraftConflict):
    pass


def _alias(user_id: int, room_id: UUID, key: UUID) -> str:
    return f"chat-draft://{user_id}/{room_id}/{key}"


def _scope() -> str:
    return current_web_session_family() or ""


async def _draft_row(user_id: int, room_id: UUID, *, lock: bool = False) -> ChatDraft | None:
    db = get_db()
    query = select(ChatDraft).where(ChatDraft.user_id == user_id, ChatDraft.room_id == room_id,
        ChatDraft.session_key == _scope()).execution_options(populate_existing=True)
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None and _scope():
        # The first authenticated session claims the pre-upgrade draft atomically.
        # Its bytes and cursor survive; other sessions start with their own draft.
        row = await db.scalar(select(ChatDraft).where(ChatDraft.user_id == user_id,
            ChatDraft.room_id == room_id, ChatDraft.session_key == "").with_for_update()
            .execution_options(populate_existing=True))
        if row is not None:
            row.session_key = _scope()
        moved = await db.scalar(update(ChatDraftFile).where(ChatDraftFile.user_id == user_id,
            ChatDraftFile.room_id == room_id, ChatDraftFile.session_key == "").values(session_key=_scope())
            .returning(ChatDraftFile.id))
        if row is not None or moved is not None:
            await db.commit()
            if lock:
                row = await db.scalar(query.with_for_update())
        if row is None:
            row = await db.scalar(query.with_for_update() if lock else query)
    return row


async def read_draft(user_id: int, room_id: UUID) -> DraftSnapshot:
    row = await _draft_row(user_id, room_id)
    return DraftSnapshot(revision=row.revision if row else 0,
        content=DraftContent.model_validate_json(row.payload) if row and row.payload != "{}" else None)


async def write_draft(user_id: int, room_id: UUID, data: DraftWrite) -> DraftSnapshot:
    db = get_db()
    await _draft_row(user_id, room_id)
    await db.execute(insert(ChatDraft).values(user_id=user_id, room_id=room_id, session_key=_scope(), revision=0, payload="{}")
        .on_conflict_do_nothing(constraint="uq_chat_draft_user_room_session"))
    row = await _draft_row(user_id, room_id, lock=True)
    assert row is not None
    if row.mutation_key == data.mutation_key:
        return await read_draft(user_id, room_id)
    if row.revision != data.expected_revision:
        raise DraftConflict("Draft changed in another session; the local draft was preserved.")
    old = DraftContent.model_validate_json(row.payload) if row.payload != "{}" else None
    retained = {item.key for item in data.content.files} if data.content else set[UUID]()
    for item in old.files if old else []:
        if item.key not in retained:
            await _retire_upload(user_id, room_id, item.key)
    row.payload = data.content.model_dump_json() if data.content else "{}"
    row.revision += 1
    row.mutation_key = data.mutation_key
    await db.commit()
    return await read_draft(user_id, room_id)


async def upload_draft_file(user_id: int, room_id: UUID, key: UUID, upload: UploadFile) -> DraftFile:
    db = get_db()
    await _draft_row(user_id, room_id)
    # Serialize duplicate uploads of the same client key without blocking typing saves.
    from sqlalchemy import func
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"draft-files:{user_id}:{room_id}"))))
    row = await db.get(ChatDraftFile, key)
    if row is not None:
        if (row.user_id, row.room_id, row.session_key) != (user_id, room_id, _scope()):
            raise PermissionError("Attachment unavailable")
        record = await db.get(StoredFile, row.file_id)
        assert record is not None
    else:
        count = await db.scalar(select(func.count()).select_from(ChatDraftFile).where(
            ChatDraftFile.user_id == user_id, ChatDraftFile.room_id == room_id, ChatDraftFile.session_key == _scope()))
        if count is not None and count >= 20:
            raise storage.AttachmentStorageError("A draft accepts at most 20 attachments")
        from uuid import uuid4
        file_id = uuid4()
        _, _, mime = await storage.store_upload(upload, file_id)
        record = await register_file(file_id, name=upload.filename or str(key), media_type=mime,
            alias=_alias(user_id, room_id, key))
        db.add(ChatDraftFile(id=key, user_id=user_id, room_id=room_id, session_key=_scope(), file_id=file_id))
        await db.commit()
    return DraftFile(key=key, name=record.name, size=record.size_bytes, mime=record.media_type, uploaded=True)


async def draft_attachments(user_id: int, room_id: UUID, revision: int, client_message_id: UUID,
                            keys: list[UUID] | None = None) -> list[ObservedMessengerFile]:
    snapshot = await read_draft(user_id, room_id)
    if keys is None and snapshot.revision != revision:
        # A successful send may have already cleared this revision. Publication is
        # still idempotent by client_message_id when its HTTP receipt was lost.
        row = await _draft_row(user_id, room_id)
        if snapshot.content is None and row is not None and row.last_sent_key == client_message_id:
            return []
        raise DraftConflict("Draft changed before sending")
    if keys is None and (snapshot.content is None or snapshot.content.client_message_id != client_message_id):
        raise DraftConflict("Draft identity changed before sending")
    result: list[ObservedMessengerFile] = []
    selected = keys if keys is not None else [item.key for item in snapshot.content.files] if snapshot.content else []
    for key in selected:
        row = await get_db().scalar(select(ChatDraftFile).where(ChatDraftFile.id == key,
            ChatDraftFile.user_id == user_id, ChatDraftFile.room_id == room_id, ChatDraftFile.session_key == _scope()))
        record = await get_db().get(StoredFile, row.file_id) if row else None
        if record is None:
            draft = await _draft_row(user_id, room_id)
            if draft is not None and draft.last_sent_key == client_message_id:
                return []
            raise DraftFileUnavailable("An attachment has not finished uploading")
        result.append(ObservedMessengerFile(id=str(record.id), local_id=record.id, name=record.name,
            size=record.size_bytes, mime=record.media_type, kind=kind_from_mime(record.media_type)))
    return result


async def clear_sent_draft(user_id: int, room_id: UUID, revision: int, *, client_message_id: UUID | None = None) -> None:
    db = get_db()
    row = await _draft_row(user_id, room_id, lock=True)
    if row is None or row.revision != revision:
        return
    content = DraftContent.model_validate_json(row.payload) if row.payload != "{}" else None
    row.last_sent_key = client_message_id or (content.client_message_id if content else None)
    row.payload = "{}"
    row.revision += 1
    row.mutation_key = None
    # Canonical message registration precedes removal of these private references.
    for item in content.files if content else []:
        await _retire_upload(user_id, room_id, item.key)
    await db.commit()


async def _retire_upload(user_id: int, room_id: UUID, key: UUID) -> None:
    removed = await get_db().scalar(delete(ChatDraftFile).where(ChatDraftFile.id == key,
        ChatDraftFile.user_id == user_id, ChatDraftFile.room_id == room_id, ChatDraftFile.session_key == _scope())
        .returning(ChatDraftFile.id))
    if removed is not None:
        await retire_file_reference(_alias(user_id, room_id, key))


async def discard_draft_file(user_id: int, room_id: UUID, key: UUID) -> None:
    row = await _draft_row(user_id, room_id, lock=True)
    content = DraftContent.model_validate_json(row.payload) if row and row.payload != "{}" else None
    if content and any(item.key == key for item in content.files):
        raise DraftConflict("Save the attachment removal before discarding its bytes")
    await _retire_upload(user_id, room_id, key)
    await get_db().commit()
