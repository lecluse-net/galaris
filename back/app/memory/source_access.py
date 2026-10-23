"""Source-owned access checks for private managed projections.

Registration belongs to application composition. Memory never resolves transports.
"""

from collections.abc import Awaitable, Callable, Sequence
from functools import wraps
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import and_, case, or_, select, exists, false
from app.document import DocumentSource
from core.database import get_db
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.orm import InstrumentedAttribute

from .models import MemoryItem, MemorySource, MemoryURL
from .query_policy import prepare_memory_read
from .schemas import MemoryGraphPage, MemoryGraphRootsRequest, MemoryGraphExpandRequest

SourceClause = Callable[[InstrumentedAttribute[UUID]], ColumnElement[bool]]
SourceReader = Callable[[UUID, int], Awaitable[bool]]
SourceBatchReader = Callable[[Sequence[UUID], int], Awaitable[set[UUID]]]
_checks: dict[str, tuple[SourceClause, SourceReader]] = {}
_batch_readers: dict[str, SourceBatchReader] = {}
EvidenceClause = Callable[[InstrumentedAttribute[dict[str, object]]], ColumnElement[bool]]
EvidenceReader = Callable[[dict[str, object], int], Awaitable[bool]]
EvidenceBatchReader = Callable[[Sequence[tuple[UUID, dict[str, object]]], int], Awaitable[set[UUID]]]
_evidence_checks: dict[str, tuple[EvidenceClause, EvidenceReader]] = {}
_evidence_batch_readers: dict[str, EvidenceBatchReader] = {}


def register_source_evidence_access(kind: str, clause: EvidenceClause, reader: EvidenceReader, *, batch_reader: EvidenceBatchReader | None = None) -> None:
    """Source owners validate derived facts; an independent live source survives."""
    _evidence_checks[kind] = clause, reader
    if batch_reader is None:
        _evidence_batch_readers.pop(kind, None)
    else:
        _evidence_batch_readers[kind] = batch_reader


def register_source_access(
    kind: str, clause: SourceClause, reader: SourceReader,
    *, batch_reader: SourceBatchReader | None = None,
) -> None:
    _checks[kind] = clause, reader
    if batch_reader is None:
        _batch_readers.pop(kind, None)
    else:
        _batch_readers[kind] = batch_reader


def source_access_clause() -> ColumnElement[bool]:
    sources = select(MemorySource.id).where(MemorySource.item_id == MemoryItem.id).correlate(MemoryItem)
    evidence_kind = MemorySource.metadata_["evidence_validator"].astext
    derived_access = or_(MemoryItem.metadata_["evidence_validator"].astext.is_(None),
        exists(sources.where(or_(evidence_kind.is_(None), false(), *(and_(evidence_kind == kind, clause(MemorySource.metadata_))
            for kind, (clause, _reader) in _evidence_checks.items())))))
    return and_(derived_access, *(or_(
        MemoryItem.managed_source_kind.is_(None),
        MemoryItem.managed_source_kind != kind,
        clause(MemoryItem.id),
    ) for kind, (clause, _reader) in _checks.items()))


async def readable_evidence_ids(identities: set[UUID], agent_id: int) -> set[UUID]:
    readable, _refs = await source_evidence_admission(identities, agent_id)
    return readable


async def source_evidence_admission(identities: set[UUID], agent_id: int, *, include_locations: bool = False) -> tuple[set[UUID], dict[UUID, list[str]]]:
    """Read provenance once for permission and source-reference projection."""
    if not identities:
        return set(), {}
    # SQLAlchemy's mapped-column types do not express nulls from the outer join.
    rows = cast(list[tuple[UUID, str | None, UUID | None, dict[str, object] | None, str | None]],
        list((await get_db().execute(select(MemoryItem.id, MemoryItem.metadata_["evidence_validator"].astext,
        case((MemoryItem.node_kind == "document", DocumentSource.id), else_=MemorySource.id),
        case((MemoryItem.node_kind == "document", DocumentSource.metadata_), else_=MemorySource.metadata_),
        case((MemoryItem.node_kind == "document", DocumentSource.source_ref), else_=MemorySource.source_ref))
        .outerjoin(MemorySource, and_(MemorySource.item_id == MemoryItem.id, MemoryItem.node_kind != "document"))
        .outerjoin(DocumentSource, and_(DocumentSource.document_id == MemoryItem.id, MemoryItem.node_kind == "document"))
        .where(MemoryItem.id.in_(identities)).order_by(MemorySource.created_at))).tuples()))
    refs: dict[UUID, list[str]] = {}
    for item_id, _marker, _source_id, _metadata, source_ref in rows:
        if source_ref is not None:
            refs.setdefault(item_id, []).append(source_ref)
    if include_locations:
        locations = await get_db().execute(select(MemoryURL.memory_node_id, MemoryURL.url).where(
            MemoryURL.memory_node_id.in_(identities)).order_by(MemoryURL.url))
        for item_id, reference in locations:
            refs.setdefault(item_id, []).append(reference)
    readable: set[UUID] = {item_id for item_id, marker, _source_id, _metadata, _source_ref in rows if marker is None}
    groups: dict[str, list[tuple[UUID, dict[str, object]]]] = {}
    source_items: dict[UUID, UUID] = {}
    for item_id, _marker, source_id, metadata, _source_ref in rows:
        if item_id in readable:
            continue
        if source_id is None or metadata is None:
            continue
        if metadata.get("evidence_validator") is None:
            readable.add(item_id)
            continue
        kind = str(metadata.get("evidence_validator"))
        groups.setdefault(kind, []).append((source_id, metadata))
        source_items[source_id] = item_id
    for kind, records in groups.items():
        valid_sources: set[UUID]
        batch_reader = _evidence_batch_readers.get(kind)
        validator = _evidence_checks.get(kind)
        if batch_reader is not None:
            valid_sources = await batch_reader(records, agent_id)
        elif validator is not None:
            valid_sources = {source_id for source_id, metadata in records if await validator[1](metadata, agent_id)}
        else:
            valid_sources = set[UUID]()
        readable.update(source_items[source_id] for source_id in valid_sources if source_id in source_items)
    return readable, refs


async def source_is_readable(item_id: UUID, source_kind: str | None, agent_id: int, *, check_evidence: bool = True) -> bool:
    check = _checks.get(source_kind or "")
    if check is not None and not await check[1](item_id, agent_id):
        return False
    return not check_evidence or item_id in await readable_evidence_ids({item_id}, agent_id)


GraphRequest = TypeVar("GraphRequest", MemoryGraphRootsRequest, MemoryGraphExpandRequest)


async def readable_source_ids(endpoints: set[UUID], agent_id: int) -> set[UUID]:
    """Recheck source-owned access in batches for graph pages and saved positions."""
    sources: list[tuple[UUID, str | None]] = []
    if endpoints:
        sources = list((await get_db().execute(select(MemoryItem.id, MemoryItem.managed_source_kind).where(
            MemoryItem.id.in_(endpoints), MemoryItem.managed_source_kind.in_(_checks),
        ))).tuples().all())
    denied: set[UUID] = set()
    groups: dict[str, list[UUID]] = {}
    for identity, kind in sources:
        if kind is not None:
            groups.setdefault(kind, []).append(identity)
    for kind, identities in groups.items():
        batch_reader = _batch_readers.get(kind)
        if batch_reader is None:
            denied.update([identity for identity in identities if not await source_is_readable(identity, kind, agent_id)])
        else:
            readable = await batch_reader(identities, agent_id)
            denied.update(set(identities) - readable)
    if sources:
        visible = set(await get_db().scalars(select(MemoryItem.id).where(
            MemoryItem.id.in_([identity for identity, _kind in sources]), source_access_clause(),
        )))
        denied.update(identity for identity, _kind in sources if identity not in visible)
    # New derived facts also need their evidence-owner's live admission, including
    # ordinary memories that have no managed projection kind.
    return await readable_evidence_ids(endpoints - denied, agent_id)


def source_checked_graph(function: Callable[[GraphRequest], Awaitable[MemoryGraphPage]]) -> Callable[[GraphRequest], Awaitable[MemoryGraphPage]]:
    @wraps(function)
    async def checked(request: GraphRequest) -> MemoryGraphPage:
        await prepare_memory_read()
        page = await function(request)
        endpoints = {node.id for node in page.nodes} | {identity for edge in page.edges
            for identity in (edge.source_item_id, edge.target_item_id)}
        focus = request.item_id if isinstance(request, MemoryGraphExpandRequest) else None
        if focus is not None:
            endpoints.add(focus)
        denied = endpoints - await readable_source_ids(endpoints, request.agent_id)
        if focus in denied:
            return MemoryGraphPage(nodes=[], edges=[], has_more=False)
        return page.model_copy(update={
            "nodes": [node for node in page.nodes if node.id not in denied],
            "edges": [edge for edge in page.edges if edge.source_item_id not in denied and edge.target_item_id not in denied],
        })
    return checked
