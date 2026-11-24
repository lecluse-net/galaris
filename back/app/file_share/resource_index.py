"""Build current source indexes through Dream and reuse analysis across occurrences."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from hashlib import sha256
from itertools import islice
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Literal, Protocol
from uuid import UUID

from loguru import logger
from sqlalchemy import SQLColumnExpression, Select, String, and_, cast as sql_cast, delete, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.elements import ColumnElement

from app.document import Document, DocumentAttachment, extract_document_bytes
from app.task import Task, TaskStatus
from core.database import get_db
from core.document import preparation_version, prepare_document
from core.storage import FileAlias, StoredFile, file_path, get_storage
from core.util import complete_io, visible_text

from .catalogue import catalogue_binding_is_current, indexed_mail_account
from .document_search import DOCUMENTARY_EXTENSIONS, supports_document_search
from .fingerprinting import hash_materialized_file
from .models import FileCatalogEntry, ManagedFileOwner, ResourceIndexContent, ResourceIndexLink, ResourceIndexPassage, ResourceIndexSource
from .resource_contracts import ResourceContext, ResourceDescriptor
from .resource_index_content import MAX_PASSAGES, IndexedPassage, contact_evidence, document_kind, json_passages, keywords, order_evidence, passages
from .resource_observation import suspend_observations
from .resource_uri import parse_resource_uri

SourceKind = Literal["document", "file", "task", "stored", "attachment"]
SOURCE_KINDS: tuple[SourceKind, ...] = ("document", "file", "task", "stored", "attachment")
_MAX_BYTES = 32 * 1024**2
ANALYSIS_VERSION = 3
_EXTENSION_PATTERN = "(" + "|".join(re.escape(extension) for extension in sorted(DOCUMENTARY_EXTENSIONS)) + ")$"


class IndexEmbeddingModel(Protocol):
    @property
    def key(self) -> str: ...
    async def embed(self, texts: list[str], *, timeout: float = 5.0) -> list[list[float]]: ...


_embedding_model: Callable[[], Awaitable[IndexEmbeddingModel | None]] | None = None
_topic_lookup: Callable[[str], Awaitable[UUID | None]] | None = None


def register_resource_index_embedding(provider: Callable[[], Awaitable[IndexEmbeddingModel | None]]) -> None:
    global _embedding_model
    _embedding_model = provider


def register_resource_index_topics(lookup: Callable[[str], Awaitable[UUID | None]]) -> None:
    global _topic_lookup
    _topic_lookup = lookup


async def embedding_model() -> IndexEmbeddingModel | None:
    return await _embedding_model() if _embedding_model is not None else None


def _digest(values: list[str]) -> str:
    return sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class IndexSubject:
    kind: SourceKind
    key: UUID
    fingerprint: str

    @property
    def value(self) -> str:
        return f"{self.kind}:{self.key}:{self.fingerprint}"

    @classmethod
    def parse(cls, raw: str) -> IndexSubject:
        kind, key, fingerprint = raw.split(":", 2)
        if kind not in SOURCE_KINDS:
            raise ValueError("Unknown resource index source")
        return cls(kind, UUID(key), fingerprint)


@dataclass(frozen=True, slots=True)
class IndexInput:
    uri: str
    content_hash: str
    format_key: str
    scope: str
    record: Document | FileCatalogEntry | Task | StoredFile

    @property
    def analysis_key(self) -> str:
        return self.analysis_key_for(ANALYSIS_VERSION)

    def analysis_key_for(self, version: int) -> str:
        return _digest([f"resource-index-{version}", self.scope, self.format_key, self.content_hash])


def task_fingerprint() -> ColumnElement[str]:
    data = func.jsonb_build_array(Task.objective, Task.execution_result["result"]).cast(String)
    return func.encode(func.sha256(func.convert_to(data, "UTF8")), "hex")


def indexable_task() -> ColumnElement[bool]:
    return and_(Task.deleted_at.is_(None), Task.status.in_((TaskStatus.SUCCESS, TaskStatus.ERROR)),
                Task.messenger_message_id.is_(None), Task.messenger_connection_id.is_(None), Task.message_platform.is_(None))


def _supported_file(mime: SQLColumnExpression[str], name: SQLColumnExpression[str]) -> ColumnElement[bool]:
    return or_(mime.startswith("text/"), func.split_part(mime, ";", 1) == "application/pdf",
               name.bool_op("~*")(_EXTENSION_PATTERN))


def _file_format(name: str, media_type: str) -> str:
    mime = media_type.split(";", 1)[0].lower()
    if mime == "text/vnd.galaris.mail":
        return mime
    extension = Path(name).suffix.lower()
    return f"{mime}:{extension if extension in DOCUMENTARY_EXTENSIONS else ''}:{preparation_version(name)}"


def catalogue_text_supported() -> ColumnElement[bool]:
    size = FileCatalogEntry.descriptor["size"].as_integer()
    return and_(or_(size.is_(None), size <= _MAX_BYTES), _supported_file(
        FileCatalogEntry.descriptor["media_type"].as_string(), FileCatalogEntry.descriptor["name"].as_string()))


def active_document_attachment() -> ColumnElement[bool]:
    return exists(select(DocumentAttachment.id).join(Document, Document.id == DocumentAttachment.document_id).where(
        DocumentAttachment.active.is_(True), Document.deleted_at.is_(None),
        FileAlias.uri == func.concat("document://", DocumentAttachment.document_id, "/attachments/", DocumentAttachment.id)))


def _pending(kind: SourceKind, handled: Select[tuple[str]]) -> Select[tuple[UUID, str]]:
    if kind == "document":
        key, fingerprint = Document.id, Document.content_hash
        selected = select(key, fingerprint).where(Document.deleted_at.is_(None),
            Document.document_format.not_in(("dataset", "process")), Document.size_bytes <= _MAX_BYTES)
    elif kind == "task":
        key, fingerprint = Task.id, task_fingerprint()
        selected = select(key, fingerprint).where(indexable_task())
    elif kind in ("stored", "attachment"):
        fingerprint = StoredFile.sha256
        if kind == "stored":
            key = StoredFile.id
            selected = select(key, fingerprint).join(ManagedFileOwner, ManagedFileOwner.file_id == StoredFile.id)
        else:
            key = FileAlias.id
            selected = select(key, fingerprint).join(StoredFile, StoredFile.id == FileAlias.file_id).where(active_document_attachment())
        selected = selected.where(StoredFile.deleted_at.is_(None), StoredFile.size_bytes <= _MAX_BYTES,
                                  _supported_file(StoredFile.media_type, StoredFile.name))
    else:
        key = FileCatalogEntry.id
        fingerprint = func.coalesce(FileCatalogEntry.source_version, "")
        selected = select(key, fingerprint).where(FileCatalogEntry.present.is_(True),
            FileCatalogEntry.source_version.is_not(None), FileCatalogEntry.file_sha256.is_not(None),
            catalogue_text_supported(), catalogue_binding_is_current())
    current = exists(select(ResourceIndexSource.id).join(ResourceIndexContent, ResourceIndexContent.id == ResourceIndexSource.content_id)
        .where(ResourceIndexSource.source_kind == kind, ResourceIndexSource.source_key == key,
               ResourceIndexSource.fingerprint == fingerprint, ResourceIndexContent.analysis_version == ANALYSIS_VERSION))
    return selected.where(~current, ~func.concat(literal(kind + ":"), sql_cast(key, String), ":", fingerprint).in_(handled))


async def pending_subjects(handled: Select[tuple[str]]) -> list[IndexSubject]:
    db = get_db()
    result: list[IndexSubject] = []
    for kind in SOURCE_KINDS:
        query = _pending(kind, handled)
        row = (await db.execute(query.order_by(query.selected_columns[0]).limit(1))).one_or_none()
        if row is not None:
            result.append(IndexSubject(kind, row[0], row[1]))
    return result


async def pending_count(handled: Select[tuple[str]]) -> int:
    result = 0
    for kind in SOURCE_KINDS:
        result += int(await get_db().scalar(select(func.count()).select_from(_pending(kind, handled).subquery())) or 0)
    return result


async def _source(subject: IndexSubject, *, lock: bool = False) -> IndexInput | None:
    db = get_db()
    if subject.kind == "document":
        statement = select(Document).where(Document.id == subject.key, Document.deleted_at.is_(None),
            Document.content_hash == subject.fingerprint, Document.size_bytes <= _MAX_BYTES).execution_options(populate_existing=True)
        doc = await db.scalar(statement.with_for_update() if lock else statement)
        if doc is None or doc.document_format in {"dataset", "process"}:
            return None
        scheme = "data" if doc.document_format == "data" else "document"
        return IndexInput(f"{scheme}://{doc.id}", doc.content_hash,
            f"document:{doc.document_format}:{doc.format_version}", "documents", doc)
    if subject.kind == "task":
        statement = select(Task).where(Task.id == subject.key, indexable_task(),
            task_fingerprint() == subject.fingerprint).execution_options(populate_existing=True)
        task = await db.scalar(statement.with_for_update() if lock else statement)
        return IndexInput(f"galaris://task/{task.id}", subject.fingerprint, "task", "tasks", task) if task is not None else None
    if subject.kind in ("stored", "attachment"):
        if subject.kind == "stored":
            stored_statement = select(StoredFile, func.concat("file://", StoredFile.id)).join(
                ManagedFileOwner, ManagedFileOwner.file_id == StoredFile.id).where(StoredFile.id == subject.key)
        else:
            stored_statement = select(StoredFile, FileAlias.uri).join(FileAlias, FileAlias.file_id == StoredFile.id).where(
                FileAlias.id == subject.key, active_document_attachment())
        stored_statement = stored_statement.where(StoredFile.deleted_at.is_(None), StoredFile.sha256 == subject.fingerprint,
                                                   StoredFile.size_bytes <= _MAX_BYTES)
        row = (await db.execute(stored_statement.with_for_update() if lock else stored_statement)).one_or_none()
        if row is None:
            return None
        stored, uri = row
        return IndexInput(uri, stored.sha256, _file_format(stored.name, stored.media_type), "files", stored)
    file_statement = select(FileCatalogEntry).where(FileCatalogEntry.id == subject.key, FileCatalogEntry.present.is_(True),
        FileCatalogEntry.source_version == subject.fingerprint, FileCatalogEntry.file_sha256.is_not(None),
        catalogue_binding_is_current()).execution_options(populate_existing=True)
    entry = await db.scalar(file_statement.with_for_update() if lock else file_statement)
    if entry is None or entry.file_sha256 is None:
        return None
    descriptor = ResourceDescriptor.model_validate(entry.descriptor)
    if descriptor.size is not None and descriptor.size > _MAX_BYTES:
        return None
    reference = parse_resource_uri(entry.uri)
    # Keep the existing exact Mail account/generation binding for all derivatives.
    scope = f"mail:{entry.connection_id}" if indexed_mail_account(reference) is not None else "files"
    return IndexInput(entry.uri, entry.file_sha256, _file_format(descriptor.name, descriptor.media_type), scope, entry)


def _plain(text: str) -> str:
    try:
        return visible_text(text) if "<" in text else text
    except ValueError:
        return text


async def _document_passages(path: Path, name: str, media_type: str, directory: Path) -> list[IndexedPassage]:
    if media_type.split(";", 1)[0].lower() == "text/vnd.galaris.mail":
        body = await complete_io(path.read_text, encoding="utf-8")
        return list(islice(passages(body, section="message"), MAX_PASSAGES))
    prepared = await prepare_document(path, name, media_type, directory)
    parts = (part for number, text in [*((page.number, page.text) for page in prepared.pages), (None, prepared.structured_text)]
             for part in passages(text or "", page=number))
    return list(islice(parts, MAX_PASSAGES))


async def _extract(source: IndexInput) -> list[IndexedPassage]:
    record = source.record
    parts: Iterator[IndexedPassage]
    if isinstance(record, Document):
        data = record.content.encode() if record.content is not None else await get_storage(record.provider_code).read(record.resource_id)
        if len(data) > _MAX_BYTES or sha256(data).hexdigest() != source.content_hash:
            raise ValueError("Document bytes changed during indexing")
        if record.document_format == "data":
            parts = json_passages(data.decode())
        else:
            parts = passages(await complete_io(extract_document_bytes, record.document_format, data), section="document")
    elif isinstance(record, Task):
        result = (record.execution_result or {}).get("result")
        parts = (part for section, text in (("objective", record.objective or ""), ("result", result if isinstance(result, str) else ""))
                 for part in passages(_plain(text), section=section))
    elif isinstance(record, StoredFile):
        path = file_path(record.id)
        if await hash_materialized_file(path) != source.content_hash:
            raise ValueError("Stored file bytes changed during indexing")
        with TemporaryDirectory(prefix="galaris-resource-index-") as directory:
            return await _document_passages(path, record.name, record.media_type, Path(directory))
    else:
        from .resource_service import materialize_resource, resource_info
        from .catalogue import descriptor_version

        actor = ResourceContext(record.agent_id, record.runtime)
        with suspend_observations(), TemporaryDirectory(prefix="galaris-resource-index-") as directory:
            path = Path(directory) / "source"
            descriptor = await resource_info(actor, source.uri)
            if not supports_document_search(descriptor):
                return []
            await materialize_resource(actor, source.uri, path, max_bytes=_MAX_BYTES)
            if await hash_materialized_file(path) != source.content_hash:
                raise ValueError("File bytes changed during indexing")
            live = await resource_info(actor, source.uri)
            if descriptor_version(live.model_dump()) != record.source_version:
                raise ValueError("File metadata changed during indexing")
            return await _document_passages(path, descriptor.name, descriptor.media_type, Path(directory))
    return list(islice(parts, MAX_PASSAGES))


async def _embed(model: IndexEmbeddingModel, texts: Sequence[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for offset in range(0, len(texts), 32):
        vectors.extend(await model.embed(list(texts[offset:offset + 32])))
    dimensions = {len(vector) for vector in vectors}
    if len(vectors) != len(texts) or len(dimensions) != 1 or any(not any(vector) for vector in vectors):
        raise ValueError("Incomplete resource embeddings")
    return vectors


async def _analyse(source: IndexInput) -> ResourceIndexContent:
    db = get_db()
    parts = await _extract(source)
    kind = document_kind(parts) if source.format_key not in {"task", "text/vnd.galaris.mail"} else None
    order = order_evidence(parts, kind)
    topic = await _topic_lookup("\n".join(part.text for part in parts[:16])) if parts and _topic_lookup is not None else None
    content = ResourceIndexContent(analysis_key=source.analysis_key, content_hash=source.content_hash, analysis_version=ANALYSIS_VERSION,
        generated_summary=" ".join(parts[0].text.split())[:600] if parts and sum(len(part.text) for part in parts) > 1_000 else "",
        generated_keywords=keywords(parts),
        suggested_topic_id=topic, document_kind=kind, contact_evidence=contact_evidence(parts),
        order_key=_digest([order.issuer, order.order]) if order else None, order_role=order.role if order else None,
        order_evidence={"order": order.order, "issuer": order.issuer, "reference": order.reference.locator,
                        "issuer_reference": order.issuer_reference.locator} if order else None)
    db.add(content)
    await db.flush()
    db.add_all([ResourceIndexPassage(content_id=content.id, position=position, locator=part.locator, text=part.text)
                for position, part in enumerate(parts)])
    return content


async def _pending_vectors(handled: Select[tuple[str]]) -> Select[tuple[str]] | None:
    try:
        model = await embedding_model()
    except Exception as error:
        logger.warning("Resource index vector model unavailable: {}", type(error).__name__)
        return None
    if model is None:
        return None
    subject = func.concat("vectors:", ResourceIndexContent.id, ":", model.key, type_=String())
    return select(subject).where(ResourceIndexContent.embedding_model_key.is_distinct_from(model.key),
        exists(select(ResourceIndexPassage.id).where(ResourceIndexPassage.content_id == ResourceIndexContent.id)),
        exists(select(ResourceIndexSource.id).where(ResourceIndexSource.content_id == ResourceIndexContent.id)),
        ~subject.in_(handled)).order_by(ResourceIndexContent.id)


async def pending_vector_subject(handled: Select[tuple[str]]) -> str | None:
    query = await _pending_vectors(handled)
    return str(row) if query is not None and (row := await get_db().scalar(query.limit(1))) is not None else None


async def pending_vector_count(handled: Select[tuple[str]]) -> int:
    query = await _pending_vectors(handled)
    return int(await get_db().scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0) if query is not None else 0


async def refresh_vectors(content_id: UUID, model_key: str) -> bool:
    model = await embedding_model()
    if model is None or model.key != model_key:
        return False
    db = get_db()
    content = await db.scalar(select(ResourceIndexContent).where(ResourceIndexContent.id == content_id,
        ResourceIndexContent.embedding_model_key.is_distinct_from(model_key),
        exists(select(ResourceIndexSource.id).where(ResourceIndexSource.content_id == ResourceIndexContent.id))).with_for_update())
    if content is None:
        return False
    parts = list(await db.scalars(select(ResourceIndexPassage).where(ResourceIndexPassage.content_id == content_id)
                                 .order_by(ResourceIndexPassage.position)))
    if not parts:
        return False
    for part, vector in zip(parts, await _embed(model, [part.text for part in parts]), strict=True):
        part.embedding = vector
    content.embedding_model_key = model_key
    return True


async def _link_orders(source_id: UUID, content: ResourceIndexContent) -> None:
    db = get_db()
    if content.order_key is not None:
        # A concurrent piece of the same order must see the committed pointers.
        await db.execute(select(func.pg_advisory_xact_lock(int.from_bytes(bytes.fromhex(content.order_key[:16]), "big", signed=True))))
    await db.execute(delete(ResourceIndexLink).where(or_(ResourceIndexLink.source_id == source_id, ResourceIndexLink.target_id == source_id)))
    if content.order_key is None:
        return
    peers = await db.execute(select(ResourceIndexSource.id, ResourceIndexContent.order_evidence, ResourceIndexContent.order_role,
        ResourceIndexSource.fingerprint).join(ResourceIndexContent, ResourceIndexSource.content_id == ResourceIndexContent.id)
        .where(ResourceIndexContent.order_key == content.order_key, ResourceIndexContent.order_role != content.order_role,
               ResourceIndexSource.id != source_id).order_by(ResourceIndexSource.id).limit(100))
    for peer, proof, role, fingerprint in peers:
        await db.execute(insert(ResourceIndexLink).values(source_id=source_id, target_id=peer, relation="same_order",
            state="confirmed", evidence={"source": content.order_evidence, "target": proof, "source_role": content.order_role,
                                         "target_role": role, "target_fingerprint": fingerprint}).on_conflict_do_nothing())


async def index_subject(subject: IndexSubject) -> bool:
    source = await _source(subject)
    if source is None:
        return False
    db = get_db()
    # The lock is scoped to one analysis, including the provider call. A second
    # worker for the same bytes waits and then reuses the committed result.
    key = int.from_bytes(bytes.fromhex(source.analysis_key[:16]), "big", signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(key)))
    content = await db.scalar(select(ResourceIndexContent).where(ResourceIndexContent.analysis_key == source.analysis_key)
                              .with_for_update())
    refreshed = False
    if content is None:
        # Version 3 changes only contact evidence. Reuse the same extracted pages and vectors.
        content = await db.scalar(select(ResourceIndexContent).where(
            ResourceIndexContent.analysis_key == source.analysis_key_for(2),
            ResourceIndexContent.analysis_version == 2).with_for_update())
        if content is not None:
            rows = await db.execute(select(ResourceIndexPassage.text, ResourceIndexPassage.locator).where(
                ResourceIndexPassage.content_id == content.id).order_by(ResourceIndexPassage.position))
            content.contact_evidence = contact_evidence([IndexedPassage(text, locator) for text, locator in rows])
            content.analysis_version = ANALYSIS_VERSION
            content.analysis_key = source.analysis_key
            await db.flush()
            refreshed = True
    if content is None:
        content = await _analyse(source)
    latest = await _source(subject, lock=True)
    if latest is None or latest.analysis_key != source.analysis_key or latest.uri != source.uri:
        await db.execute(delete(ResourceIndexContent).where(ResourceIndexContent.id == content.id,
            ~exists(select(ResourceIndexSource.id).where(ResourceIndexSource.content_id == content.id))))
        return False
    previous = await db.scalar(select(ResourceIndexSource.content_id).where(
        ResourceIndexSource.source_kind == subject.kind, ResourceIndexSource.source_key == subject.key))
    topic = latest.record.topic_id if isinstance(latest.record, (Document, Task)) else content.suggested_topic_id
    statement = insert(ResourceIndexSource).values(source_kind=subject.kind, source_key=subject.key,
        uri=source.uri, fingerprint=subject.fingerprint, content_id=content.id, topic_id=topic)
    statement = statement.on_conflict_do_update(index_elements=[ResourceIndexSource.source_kind, ResourceIndexSource.source_key],
        set_={"uri": source.uri, "fingerprint": subject.fingerprint, "content_id": content.id, "topic_id": topic},
        where=or_(ResourceIndexSource.uri != source.uri, ResourceIndexSource.fingerprint != subject.fingerprint,
                  ResourceIndexSource.content_id != content.id))
    identifier = await db.scalar(statement.returning(ResourceIndexSource.id))
    if identifier is None:
        return refreshed
    await _link_orders(identifier, content)
    if previous is not None and previous != content.id:
        previous_unreferenced = await db.scalar(select(ResourceIndexContent.id).where(ResourceIndexContent.id == previous,
            ~exists(select(ResourceIndexSource.id).where(ResourceIndexSource.content_id == previous))).with_for_update(skip_locked=True))
        if previous_unreferenced is not None:
            await db.execute(delete(ResourceIndexContent).where(ResourceIndexContent.id == previous_unreferenced,
                ~exists(select(ResourceIndexSource.id).where(ResourceIndexSource.content_id == previous_unreferenced))))
    return True


async def prune_retired_index_sources() -> None:
    """Drop obsolete pointers and unreferenced passages in bounded batches."""
    db = get_db()
    current = or_(
        and_(ResourceIndexSource.source_kind == "document", exists(select(Document.id).where(
            Document.id == ResourceIndexSource.source_key, Document.deleted_at.is_(None),
            Document.content_hash == ResourceIndexSource.fingerprint))),
        and_(ResourceIndexSource.source_kind == "task", exists(select(Task.id).where(
            Task.id == ResourceIndexSource.source_key, indexable_task(), task_fingerprint() == ResourceIndexSource.fingerprint))),
        and_(ResourceIndexSource.source_kind == "file", exists(select(FileCatalogEntry.id).where(
            FileCatalogEntry.id == ResourceIndexSource.source_key, FileCatalogEntry.present.is_(True),
            FileCatalogEntry.uri == ResourceIndexSource.uri, FileCatalogEntry.source_version == ResourceIndexSource.fingerprint,
            catalogue_binding_is_current()))),
        and_(ResourceIndexSource.source_kind == "stored", exists(select(StoredFile.id).join(ManagedFileOwner,
            ManagedFileOwner.file_id == StoredFile.id).where(StoredFile.id == ResourceIndexSource.source_key,
                StoredFile.deleted_at.is_(None), StoredFile.sha256 == ResourceIndexSource.fingerprint))),
        and_(ResourceIndexSource.source_kind == "attachment", exists(select(FileAlias.id).join(StoredFile,
            StoredFile.id == FileAlias.file_id).where(FileAlias.id == ResourceIndexSource.source_key,
                StoredFile.deleted_at.is_(None), StoredFile.sha256 == ResourceIndexSource.fingerprint, active_document_attachment()))),
    )
    retired = select(ResourceIndexSource.id).where(~current).order_by(ResourceIndexSource.id).limit(500).with_for_update(skip_locked=True)
    await db.execute(delete(ResourceIndexSource).where(ResourceIndexSource.id.in_(retired)).execution_options(synchronize_session=False))
    unreferenced = ~exists(select(ResourceIndexSource.id).where(ResourceIndexSource.content_id == ResourceIndexContent.id))
    orphans = select(ResourceIndexContent.id).where(unreferenced).order_by(ResourceIndexContent.id).limit(500).with_for_update(skip_locked=True)
    await db.execute(delete(ResourceIndexContent).where(ResourceIndexContent.id.in_(orphans), unreferenced)
                     .execution_options(synchronize_session=False))
