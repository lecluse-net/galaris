"""Source-owned access checks for private managed projections.

Registration belongs to application composition. Memory never resolves transports.
"""

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar
from uuid import UUID

from sqlalchemy import and_, or_, select
from core.database import get_db
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.orm import InstrumentedAttribute

from .models import MemoryItem
from .schemas import MemoryGraphPage, MemoryGraphRootsRequest, MemoryGraphExpandRequest

SourceClause = Callable[[InstrumentedAttribute[UUID]], ColumnElement[bool]]
SourceReader = Callable[[UUID, int], Awaitable[bool]]
_checks: dict[str, tuple[SourceClause, SourceReader]] = {}


def register_source_access(kind: str, clause: SourceClause, reader: SourceReader) -> None:
    _checks[kind] = clause, reader


def source_access_clause() -> ColumnElement[bool]:
    return and_(True, *(or_(
        MemoryItem.managed_source_kind.is_(None),
        MemoryItem.managed_source_kind != kind,
        clause(MemoryItem.id),
    ) for kind, (clause, _reader) in _checks.items()))


async def source_is_readable(item_id: UUID, source_kind: str | None, agent_id: int) -> bool:
    check = _checks.get(source_kind or "")
    return True if check is None else await check[1](item_id, agent_id)


GraphRequest = TypeVar("GraphRequest", MemoryGraphRootsRequest, MemoryGraphExpandRequest)


def source_checked_graph(function: Callable[[GraphRequest], Awaitable[MemoryGraphPage]]) -> Callable[[GraphRequest], Awaitable[MemoryGraphPage]]:
    @wraps(function)
    async def checked(request: GraphRequest) -> MemoryGraphPage:
        page = await function(request)
        endpoints = {node.id for node in page.nodes} | {identity for edge in page.edges
            for identity in (edge.source_item_id, edge.target_item_id)}
        focus = request.item_id if isinstance(request, MemoryGraphExpandRequest) else None
        if focus is not None:
            endpoints.add(focus)
        sources: list[tuple[UUID, str | None]] = []
        if endpoints:
            sources = list((await get_db().execute(select(MemoryItem.id, MemoryItem.managed_source_kind).where(
                MemoryItem.id.in_(endpoints), MemoryItem.managed_source_kind.in_(_checks),
            ))).tuples().all())
        denied = {identity for identity, kind in sources
                  if not await source_is_readable(identity, kind, request.agent_id)}
        if sources:
            visible = set(await get_db().scalars(select(MemoryItem.id).where(
                MemoryItem.id.in_([identity for identity, _kind in sources]), source_access_clause(),
            )))
            denied.update(identity for identity, _kind in sources if identity not in visible)
        if focus in denied:
            return MemoryGraphPage(nodes=[], edges=[], has_more=False)
        return page.model_copy(update={
            "nodes": [node for node in page.nodes if node.id not in denied],
            "edges": [edge for edge in page.edges if edge.source_item_id not in denied and edge.target_item_id not in denied],
        })
    return checked
