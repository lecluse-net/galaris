"""Asynchronous, rebuildable embedding projection for governed memory."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID, uuid4

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import Float, String, cast as sql_cast, column, delete, exists, func, or_, select, update, values
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.dialects.postgresql import UUID as PGUUID, insert

from core.database import get_db, get_db_session
from .passages import Passage, document_passages
from .storage import get_storage

from .embedding import (
    EmbeddingModel,
    MemoryEmbeddingNotConfiguredError,
    embed_many,
    resolve_embedding_model,
)
from .models import MemoryAutomationJob, MemoryEmbeddingChunk, MemoryEmbeddingManifest, MemoryItem


SEMANTIC_INDEX_VERSION = 4
CHUNK_WORDS = 360
CHUNK_OVERLAP_WORDS = 60
MAX_CHUNKS_PER_MEMORY = 4096
EMBEDDING_BATCH_SIZE = 32


class MemoryEmbeddingRebuildResult(BaseModel):
    model_configured: bool
    model_code: str | None = None
    scanned: int = 0
    queued: int = 0
    current: int = 0


@dataclass(frozen=True)
class _Chunk:
    text: str
    embedding_text: str
    locator: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class _MemorySnapshot:
    item_id: UUID
    fingerprint: str
    title: str
    keywords: tuple[str, ...]
    search_text: str
    passages: tuple[Passage, ...] = ()


def semantic_fingerprint_values(
    *,
    content_hash: str,
    title: str,
    keywords: Sequence[str],
    content_type: str,
    media_type: str,
) -> str:
    """Hash every field that contributes to the semantic representation."""

    serialized = json.dumps(
        {
            "version": SEMANTIC_INDEX_VERSION,
            "content_hash": content_hash,
            "title": title.strip(),
            "keywords": [str(value).strip() for value in keywords],
            "content_type": content_type,
            "media_type": media_type,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def semantic_fingerprint(item: MemoryItem) -> str:
    return semantic_fingerprint_values(
        # Block locators are part of the index contract. Equal visible text in
        # differently structured HTML must not reuse the previous locations.
        content_hash=item.content_hash,
        title=item.title,
        keywords=item.keywords,
        content_type=item.content_type,
        media_type=item.media_type,
    )


def _chunks(snapshot: _MemorySnapshot) -> list[_Chunk]:
    prefix_parts = [f"Title: {snapshot.title}"]
    if snapshot.keywords:
        prefix_parts.append(f"Keywords: {', '.join(snapshot.keywords)}")
    prefix = "\n".join(prefix_parts)
    if snapshot.passages:
        if len(snapshot.passages) > MAX_CHUNKS_PER_MEMORY:
            raise ValueError("Document exceeds the semantic passage budget")
        return [_Chunk(
            text=passage.text,
            embedding_text=f"{prefix}\nSection: {' > '.join(passage.section_path)}\n\n{passage.text}",
            locator={"block_start": passage.block_start, "block_end": passage.block_end,
                     "section_path": list(passage.section_path)},
        ) for passage in snapshot.passages]
    words = snapshot.search_text.split()
    if not words:
        excerpt = snapshot.title
        return [_Chunk(text=excerpt, embedding_text=prefix)]

    step = CHUNK_WORDS - CHUNK_OVERLAP_WORDS
    chunks: list[_Chunk] = []
    for start in range(0, len(words), step):
        body = " ".join(words[start : start + CHUNK_WORDS])
        if not body:
            break
        chunks.append(
            _Chunk(
                text=body,
                embedding_text=f"{prefix}\n\n{body}",
            )
        )
        if len(chunks) >= MAX_CHUNKS_PER_MEMORY:
            if start + CHUNK_WORDS < len(words):
                raise ValueError("Memory exceeds the semantic passage budget")
            break
        if start + CHUNK_WORDS >= len(words):
            break
    return chunks


def _job_key(item_id: UUID, fingerprint: str, model_key: str) -> str:
    raw = f"semantic_index:{item_id}:{fingerprint}:{model_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stage_embedding_refresh(item: MemoryItem) -> None:
    """Persist the indexing intent in the source transaction, without a provider.

    The worker resolves the configured model at execution time. Repeated source
    changes may coalesce there; rolling back the source also rolls back its job.
    """
    fingerprint = semantic_fingerprint(item)
    if item.semantic_fingerprint == fingerprint:
        return
    item.semantic_fingerprint = fingerprint
    if item.node_kind in {"attachment", "folder"} and not item.search_text.strip():
        return
    if getattr(item, "id", None) is None:
        item.id = uuid4()
    get_db().add(MemoryAutomationJob(
        kind="semantic_index", idempotency_key=_job_key(item.id, fingerprint, str(uuid4())),
        payload={"item_id": str(item.id), "source_fingerprint": fingerprint},
    ))


def complete_projection_clause(model_key: str) -> ColumnElement[bool]:
    """A manifest is ready only while all its declared chunks still exist."""
    manifest = MemoryEmbeddingManifest
    count = select(func.count(MemoryEmbeddingChunk.id)).where(
        MemoryEmbeddingChunk.item_id == manifest.item_id,
        MemoryEmbeddingChunk.model_key == manifest.model_key,
        MemoryEmbeddingChunk.source_fingerprint == manifest.source_fingerprint,
        MemoryEmbeddingChunk.dimensions == manifest.dimensions,
        func.vector_dims(MemoryEmbeddingChunk.embedding) == manifest.dimensions,
        sql_cast(MemoryEmbeddingChunk.embedding.op("<#>")(MemoryEmbeddingChunk.embedding), Float) < 0,
        MemoryEmbeddingChunk.chunk_index >= 0,
        MemoryEmbeddingChunk.chunk_index < manifest.chunk_count,
    ).correlate(manifest).scalar_subquery()
    return exists(select(manifest.item_id).where(
        manifest.item_id == MemoryItem.id,
        manifest.model_key == model_key,
        manifest.source_fingerprint == MemoryItem.semantic_fingerprint,
        manifest.index_version == SEMANTIC_INDEX_VERSION,
        count == manifest.chunk_count,
    )).correlate(MemoryItem)


async def _ensure_index_job(
    *,
    item_id: UUID,
    fingerprint: str,
    model: EmbeddingModel,
    requeue: bool,
) -> bool:
    db = get_db()
    key = _job_key(item_id, fingerprint, model.key)
    statement = insert(MemoryAutomationJob).values(
        kind="semantic_index", idempotency_key=key,
        payload={"item_id": str(item_id), "source_fingerprint": fingerprint, "model_key": model.key},
    )
    if requeue:
        statement = statement.on_conflict_do_update(
            index_elements=[MemoryAutomationJob.idempotency_key],
            set_={"status": "pending", "attempts": 0, "available_at": datetime.now(timezone.utc),
                  "locked_at": None, "last_error": None},
            where=MemoryAutomationJob.status != "running",
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=[MemoryAutomationJob.idempotency_key])
    if await db.scalar(statement.returning(MemoryAutomationJob.id)) is not None:
        return True
    return await db.scalar(select(MemoryAutomationJob.status).where(MemoryAutomationJob.idempotency_key == key)) == "pending"


async def enqueue_embedding_refresh(item: MemoryItem) -> bool:
    """Queue the current projection without invoking a model on the write path."""

    fingerprint = semantic_fingerprint(item)
    if item.semantic_fingerprint != fingerprint:
        item.semantic_fingerprint = fingerprint
        await get_db().commit()
    pending_intent = await get_db().scalar(select(MemoryAutomationJob.id).where(
        MemoryAutomationJob.kind == "semantic_index",
        MemoryAutomationJob.status.in_(("pending", "running")),
        MemoryAutomationJob.payload["item_id"].as_string() == str(item.id),
        MemoryAutomationJob.payload["source_fingerprint"].as_string() == fingerprint,
        MemoryAutomationJob.payload["model_key"].as_string().is_(None),
    ).limit(1))
    if pending_intent is not None:
        return True
    try:
        model = await resolve_embedding_model()
    except MemoryEmbeddingNotConfiguredError:
        return False
    queued = await _ensure_index_job(
        item_id=item.id,
        fingerprint=fingerprint,
        model=model,
        requeue=False,
    )
    await get_db().commit()
    return queued


async def enqueue_embedding_reconciliation() -> None:
    """Queue one cheap reconciliation after the selected model changes."""

    nonce = uuid4()
    get_db().add(
        MemoryAutomationJob(
            kind="semantic_reconcile",
            idempotency_key=hashlib.sha256(
                f"semantic_reconcile:{nonce}".encode("utf-8")
            ).hexdigest(),
            payload={},
        )
    )
    await get_db().commit()


async def reconcile_embedding_index(
    *, missing_only: bool = True
) -> MemoryEmbeddingRebuildResult:
    """Synchronize source fingerprints and queue missing vector projections."""

    try:
        model = await resolve_embedding_model()
    except MemoryEmbeddingNotConfiguredError:
        return MemoryEmbeddingRebuildResult(model_configured=False)

    db = get_db()
    scanned = queued = current = 0
    after: UUID | None = None
    while True:
        statement = select(
            MemoryItem.id, MemoryItem.content_hash, MemoryItem.title,
            MemoryItem.keywords, MemoryItem.content_type, MemoryItem.media_type,
            MemoryItem.semantic_fingerprint, MemoryItem.search_text,
        ).where(or_(MemoryItem.node_kind.not_in(("attachment", "folder")), MemoryItem.search_text != "")).order_by(MemoryItem.id).limit(250)
        if after is not None:
            statement = statement.where(MemoryItem.id > after)
        rows = list((await db.execute(statement)).all())
        if not rows:
            break
        indexed = await db.execute(select(
            MemoryItem.id, MemoryItem.semantic_fingerprint,
        ).where(complete_projection_clause(model.key),
                MemoryItem.id.in_([row.id for row in rows])))
        projections = set(indexed.tuples().all())
        changes: list[tuple[UUID, str, str]] = []
        jobs: list[dict[str, Any]] = []
        for row in rows:
            fingerprint = semantic_fingerprint_values(content_hash=row.content_hash,
                title=row.title, keywords=row.keywords,
                content_type=row.content_type, media_type=row.media_type)
            if row.semantic_fingerprint != fingerprint:
                changes.append((row.id, row.semantic_fingerprint, fingerprint))
            is_current = (row.id, fingerprint) in projections
            current += int(is_current)
            if is_current and missing_only:
                continue
            jobs.append({"kind": "semantic_index", "idempotency_key": _job_key(row.id, fingerprint, model.key),
                "payload": {"item_id": str(row.id), "source_fingerprint": fingerprint, "model_key": model.key,
                            "force": not missing_only}})
        if changes:
            revisions = values(column("item", PGUUID(as_uuid=True)), column("previous", String),
                column("fingerprint", String), name="semantic_revisions").data(changes)
            await db.execute(update(MemoryItem).where(MemoryItem.id == revisions.c.item,
                MemoryItem.semantic_fingerprint == revisions.c.previous).values(
                    semantic_fingerprint=revisions.c.fingerprint, updated_at=MemoryItem.updated_at,
                ).execution_options(synchronize_session=False))
        if jobs:
            statement_jobs = insert(MemoryAutomationJob).values(jobs)
            statement_jobs = statement_jobs.on_conflict_do_update(
                index_elements=[MemoryAutomationJob.idempotency_key],
                set_={"status": "pending", "attempts": 0, "available_at": datetime.now(timezone.utc),
                      "locked_at": None, "last_error": None, "payload": statement_jobs.excluded.payload},
                where=(MemoryAutomationJob.status != "running" if not missing_only else
                       MemoryAutomationJob.status == "success"),
            ).returning(MemoryAutomationJob).execution_options(populate_existing=True)
            queued += len(list(await db.scalars(statement_jobs)))
        scanned += len(rows)
        after = rows[-1].id
        # Fingerprints and idempotent jobs persist together after each bounded
        # page. A restart can scan again without losing or duplicating jobs.
        await db.commit()
    return MemoryEmbeddingRebuildResult(model_configured=True, model_code=model.code,
        scanned=scanned, queued=queued, current=current)


async def _load_snapshot(
    item_id: UUID,
    *, force: bool = False,
) -> tuple[_MemorySnapshot, EmbeddingModel] | None:
    async with get_db_session():
        item = await get_db().get(MemoryItem, item_id)
        if item is None or item.deleted_at is not None:
            await get_db().execute(
                delete(MemoryEmbeddingChunk).where(
                    MemoryEmbeddingChunk.item_id == item_id
                )
            )
            return None
        try:
            model = await resolve_embedding_model()
        except MemoryEmbeddingNotConfiguredError:
            return None
        if not force and await get_db().scalar(select(MemoryItem.id).where(
            MemoryItem.id == item_id, complete_projection_clause(model.key),
        )) is not None:
            return None
        if item.node_kind in {"attachment", "folder"} and not item.search_text.strip():
            return None
        fingerprint = semantic_fingerprint(item)
        if item.semantic_fingerprint != fingerprint:
            item.semantic_fingerprint = fingerprint
        passages: tuple[Passage, ...] = ()
        if item.media_type == "text/html" and item.search_text.strip():
            content = await get_storage(item.provider_code).read(item.resource_id)
            if hashlib.sha256(content).hexdigest() != item.content_hash:
                raise ValueError("Memory resource checksum differs from its revision")
            passages = tuple(document_passages(content.decode("utf-8"), max_words=CHUNK_WORDS))
        return (
            _MemorySnapshot(
                item_id=item.id,
                fingerprint=fingerprint,
                title=item.title,
                keywords=tuple(item.keywords),
                search_text=item.search_text,
                passages=passages,
            ),
            model,
        )


async def process_embedding_job(payload: dict[str, Any]) -> None:
    """Build one item outside its write transaction, then atomically swap it."""

    try:
        item_id = UUID(str(payload.get("item_id") or ""))
    except ValueError as exc:
        raise ValueError("Semantic index payload requires a valid item_id.") from exc
    loaded = await _load_snapshot(item_id, force=payload.get("force") is True)
    if loaded is None:
        return
    snapshot, model = loaded
    chunks = _chunks(snapshot)
    embeddings: list[list[float]] = []
    for offset in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[offset : offset + EMBEDDING_BATCH_SIZE]
        embeddings.extend(
            await embed_many(
                [chunk.embedding_text for chunk in batch],
                model=model,
            )
        )
    if len(embeddings) != len(chunks) or not embeddings or not embeddings[0]:
        raise ValueError("Embedding response does not cover every passage")
    dimensions = len(embeddings[0])
    if any(len(vector) != dimensions or not all(math.isfinite(value) for value in vector)
           or not any(value != 0 for value in vector) for vector in embeddings):
        raise ValueError("Embedding response contains an invalid vector")

    async with get_db_session():
        item = await get_db().scalar(select(MemoryItem).where(MemoryItem.id == item_id).with_for_update())
        if item is None or item.deleted_at is not None:
            await get_db().execute(
                delete(MemoryEmbeddingChunk).where(
                    MemoryEmbeddingChunk.item_id == item_id
                )
            )
            return
        try:
            current_model = await resolve_embedding_model()
        except MemoryEmbeddingNotConfiguredError:
            return
        current_fingerprint = semantic_fingerprint(item)
        if (
            current_model.key != model.key
            or current_fingerprint != snapshot.fingerprint
        ):
            item.semantic_fingerprint = current_fingerprint
            await _ensure_index_job(
                item_id=item.id,
                fingerprint=current_fingerprint,
                model=current_model,
                requeue=False,
            )
            return
        await get_db().execute(
            delete(MemoryEmbeddingChunk).where(
                MemoryEmbeddingChunk.item_id == item_id
            )
        )
        get_db().add_all(
            [
                MemoryEmbeddingChunk(
                    item_id=item_id,
                    source_fingerprint=snapshot.fingerprint,
                    model_key=model.key,
                    model_code=model.code,
                    dimensions=dimensions,
                    chunk_index=index,
                    locator=chunk.locator,
                    text=chunk.text,
                    embedding=embedding,
                )
                for index, (chunk, embedding) in enumerate(
                    zip(chunks, embeddings, strict=True)
                )
            ]
        )
        source_words = len(snapshot.search_text.split())
        manifest_values = dict(
            item_id=item_id, source_fingerprint=snapshot.fingerprint, model_key=model.key,
            index_version=SEMANTIC_INDEX_VERSION, dimensions=dimensions, chunk_count=len(chunks),
            source_word_count=source_words, indexed_word_count=source_words,
            indexed_at=datetime.now(timezone.utc),
        )
        await get_db().execute(insert(MemoryEmbeddingManifest).values(**manifest_values).on_conflict_do_update(
            index_elements=[MemoryEmbeddingManifest.item_id], set_=manifest_values,
        ))
async def process_reconciliation_job() -> None:
    async with get_db_session():
        result = await reconcile_embedding_index(missing_only=True)
    logger.info("Memory semantic-index reconciliation: {}", result.model_dump())


async def delete_item_embeddings(item_id: UUID) -> None:
    await get_db().execute(delete(MemoryEmbeddingManifest).where(MemoryEmbeddingManifest.item_id == item_id))
    await get_db().execute(
        delete(MemoryEmbeddingChunk).where(
            MemoryEmbeddingChunk.item_id == item_id
        )
    )


__all__ = [
    "MemoryEmbeddingRebuildResult",
    "delete_item_embeddings",
    "enqueue_embedding_reconciliation",
    "enqueue_embedding_refresh",
    "process_embedding_job",
    "process_reconciliation_job",
    "reconcile_embedding_index",
    "semantic_fingerprint",
    "semantic_fingerprint_values",
]
