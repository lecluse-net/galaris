"""Live provenance admission for facts captured from canonical conversations."""

import hashlib
from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import String, and_, case, column, exists, func, literal, or_, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.connection import Connection
from app.messenger import Message, Room, Attachment, File, conversation_audio_transcripts
from app.llm.facade import acquired_document_evidence, document_evidence_access_clause
from core.database import get_db
from .contracts import MemoryExtractionEvidence


def conversation_evidence_clause(
    metadata: InstrumentedAttribute[dict[str, object]],
) -> ColumnElement[bool]:
    empty: list[dict[str, Any]] = []
    evidence = case(
        (func.jsonb_typeof(metadata["source_evidence"]) == "array", metadata["source_evidence"]),
        else_=literal(empty, type_=JSONB),
    )
    parts = func.jsonb_array_elements(evidence).table_valued(column("value", JSONB))
    part = parts.c.value
    file_identity = func.regexp_replace(part["uri"].astext, "^.*/", "")
    source_file = exists(
        select(Attachment.file_id)
        .join(File, File.id == Attachment.file_id)
        .where(
            Attachment.message_id == Message.id,
            sql_cast(File.id, String) == file_identity,
            File.deleted_at.is_(None),
            File.connection_id == Message.connection_id,
        )
        .correlate(Message, parts)
    )
    text_hash = func.encode(func.sha256(func.convert_to(Message.text, "UTF8")), "hex")
    transcript_hash = func.encode(
        func.sha256(
            func.convert_to(
                func.regexp_replace(
                    Message.metadata_["conversation_audio_transcripts"][file_identity].astext,
                    r"^[[:space:]]+|[[:space:]]+$",
                    "",
                    "g",
                ),
                "UTF8",
            )
        ),
        "hex",
    )
    live_part = exists(
        select(Message.id)
        .join(Room, Room.id == Message.messenger_room_id)
        .join(Connection, Connection.id == Room.connection_id)
        .where(
            sql_cast(Message.id, String) == part["message_id"].astext,
            Message.deleted_at.is_(None),
            Room.deleted_at.is_(None),
            Connection.active.is_(True),
            Connection.id == Message.connection_id,
            or_(
                and_(
                    part["kind"].astext == "written",
                    text_hash == part["version"]["text_sha256"].astext,
                ),
                and_(
                    part["kind"].astext == "transcription",
                    source_file,
                    transcript_hash == part["version"]["text_sha256"].astext,
                ),
                and_(
                    part["kind"].astext.in_(("document_extraction", "document_interpretation")),
                    source_file,
                    document_evidence_access_clause(
                        part, cast(ColumnElement[int], Connection.agent_id)
                    ),
                ),
            ),
        )
        .correlate(parts)
    )
    return and_(
        func.jsonb_array_length(evidence) > 0,
        ~exists(select(part).select_from(parts).where(~live_part)),
    )


async def conversation_evidence_readable(metadata: dict[str, object], agent_id: int) -> bool:
    source_id = UUID(int=0)
    return source_id in await conversation_evidence_readable_batch(
        [(source_id, metadata)], agent_id
    )


async def conversation_evidence_readable_batch(
    records: Sequence[tuple[UUID, dict[str, object]]],
    agent_id: int,
) -> set[UUID]:
    """Fresh source validation shared across a page, never a persistent cache."""
    sources: dict[UUID, list[MemoryExtractionEvidence]] = {}
    for source_id, metadata in records:
        raw = metadata.get("source_evidence")
        if not isinstance(raw, list) or not raw:
            continue
        try:
            sources[source_id] = [
                MemoryExtractionEvidence.model_validate(value) for value in cast(list[object], raw)
            ]
        except ValidationError:
            continue
    parts = [part for source_parts in sources.values() for part in source_parts]
    if not parts:
        return set()
    messages = {
        message.id: message
        for message in await get_db().scalars(
            select(Message)
            .join(Room, Room.id == Message.messenger_room_id)
            .join(Connection, Connection.id == Room.connection_id)
            .where(
                Message.id.in_({part.message_id for part in parts}),
                Connection.agent_id == agent_id,
                Connection.id == Message.connection_id,
                Connection.active.is_(True),
                Message.deleted_at.is_(None),
                Room.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
    }
    attached = (
        {
            (message_id, str(file.id)): file
            for message_id, file in await get_db().execute(
                select(Attachment.message_id, File)
                .join(File, File.id == Attachment.file_id)
                .where(
                    Attachment.message_id.in_(messages),
                    File.deleted_at.is_(None),
                )
                .execution_options(populate_existing=True)
            )
        }
        if any(part.uri for part in parts)
        else {}
    )
    document_tasks: set[UUID] = set()
    document_uris: set[str] = set()
    analysis_ids: set[UUID] = set()
    for part in parts:
        if part.kind in {"document_extraction", "document_interpretation"}:
            try:
                document_tasks.add(UUID(str(part.version["task_ref"])))
                analysis_ids.add(UUID(str(part.version["analysis_ref"])))
            except KeyError, ValueError:
                continue
            if part.uri:
                document_uris.add(part.uri)
    documents = await acquired_document_evidence(
        agent_id,
        tuple(document_tasks),
        tuple(document_uris),
        analysis_ids=tuple(analysis_ids),
    )

    def part_is_readable(part: MemoryExtractionEvidence) -> bool:
        message = messages.get(part.message_id)
        if message is None:
            return False
        if part.kind == "written":
            return hashlib.sha256(message.text.encode()).hexdigest() == part.version.get(
                "text_sha256"
            )
        if not part.uri:
            return False
        file = attached.get((message.id, part.uri.rsplit("/", 1)[-1]))
        if file is None or file.connection_id != message.connection_id:
            return False
        if part.kind == "transcription":
            text = conversation_audio_transcripts(message.metadata_).get(str(file.id), "")
            return hashlib.sha256(text.encode()).hexdigest() == part.version.get("text_sha256")
        elif part.kind in {"document_extraction", "document_interpretation"}:
            return any(
                str(evidence.analysis_id) == part.version.get("analysis_ref")
                and evidence.version == part.version
                for evidence in documents
            )
        else:
            return False

    return {
        source_id
        for source_id, source_parts in sources.items()
        if all(part_is_readable(part) for part in source_parts)
    }
