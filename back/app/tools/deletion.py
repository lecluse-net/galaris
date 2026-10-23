"""Human-confirmed removal of a Tool and its dependent relational data.

SET NULL links retain independent business records. All other inbound links are
included in the purge, including RESTRICT links that normally protect history.
No remote service is contacted or deleted by this operation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Table, delete, inspect, select, tuple_, update
from sqlalchemy.sql.elements import ColumnElement

from core import settings
from core.database import Base, get_db

from .models import Tool

type Identity = tuple[Any, ...]
type Identities = dict[str, set[Identity]]
type ToolDeletionSelection = Mapping[str, Collection[tuple[object, ...]]]
type AfterToolDeletion = Callable[[], Awaitable[None]]
type ToolDeletionCleanup = Callable[[ToolDeletionSelection], Awaitable[AfterToolDeletion | None]]

_cleanups: dict[str, ToolDeletionCleanup] = {}


def register_tool_deletion_cleanup(name: str, callback: ToolDeletionCleanup) -> None:
    """Let owning domains retire non-FK resources and settle waiters after commit."""
    _cleanups[name] = callback

# These are configuration/approval projections, rather than independent history.
_OWNED_NULL_LINKS = frozenset({
    "tool_action_authorizations", "file_catalog_entries", "file_index_runs",
    "file_observation_repairs",
})


class DeletionConflict(ValueError):
    """The human must inspect the new impact before confirming again."""


class DeletionCount(BaseModel):
    kind: str
    count: int


class ToolDeletionImpact(BaseModel):
    tool_id: int
    version: str
    deleted: list[DeletionCount]
    detached_count: int


def _chunks(keys: set[Identity]) -> list[list[Identity]]:
    values = sorted(keys, key=lambda key: tuple(str(value) for value in key))
    return [values[start:start + 500] for start in range(0, len(values), 500)]


def _identity_clause(table: Table, keys: list[Identity]) -> ColumnElement[bool]:
    return tuple_(*table.primary_key.columns).in_(keys)


def _empty_identities() -> Identities:
    return {}


def _kind(name: str) -> str:
    if name == "connections":
        return "connections"
    if name == "connection_params":
        return "parameters"
    if name in {"connection_function_state", "tool_function_state", "tool_action_authorizations"}:
        return "authorizations"
    if name == "connection_oauth":
        return "accounts"
    if name.startswith(("messenger_", "conversation_", "chat_", "voice_")):
        return "messaging"
    if name.startswith("process_"):
        return "processes"
    if name.startswith("file_"):
        return "fileIndex"
    if name.startswith("code_"):
        return "workspaces"
    return "other"


@dataclass
class DeletionPlan:
    deleted: Identities = field(default_factory=_empty_identities)
    detached: Identities = field(default_factory=_empty_identities)

    def impact(self, tool: Tool) -> ToolDeletionImpact:
        counts: dict[str, int] = defaultdict(int)
        for name, keys in self.deleted.items():
            if name != "tools":
                counts[_kind(name)] += len(keys)
        counts["parameters"] += len(tool.global_params or {})
        # The digest binds the exact affected identities without disclosing any.
        state = {
            "tool": {column.name: getattr(tool, column.name) for column in Tool.__table__.columns},
            "deleted": {name: sorted(map(str, keys)) for name, keys in sorted(self.deleted.items())},
            "detached": {name: sorted(map(str, keys)) for name, keys in sorted(self.detached.items())},
        }
        version = hmac.new(settings.ENCRYPTION_MASTER_KEY.encode(),
            json.dumps(state, sort_keys=True, default=str).encode(), hashlib.sha256).hexdigest()
        return ToolDeletionImpact(tool_id=tool.id, version=version,
            deleted=[DeletionCount(kind=kind, count=count) for kind, count in sorted(counts.items()) if count],
            detached_count=sum(len(keys - self.deleted.get(name, set())) for name, keys in self.detached.items()))


async def collect(tool: Tool, *, lock: bool = False) -> DeletionPlan:
    """Follow inbound FK edges only; never traverse toward agents, users or files."""
    plan = DeletionPlan(deleted={"tools": {(tool.id,)}})
    pending = [(Base.metadata.tables["tools"], {(tool.id,)})]
    tables = sorted(Base.metadata.tables.values(), key=lambda table: table.name)
    while pending:
        parent, keys = pending.pop()
        if parent.name == "process_definitions":
            # Process policies are exclusive, owned parents, not shared principals.
            policies = Base.metadata.tables["share_configs"]
            found: set[Identity] = set()
            for batch in _chunks(keys):
                query = select(policies.c.id).where(policies.c.id.in_(
                    select(parent.c.share_id).where(_identity_clause(parent, batch))))
                if lock:
                    query = query.order_by(*policies.primary_key.columns).with_for_update()
                found.update(tuple(row) for row in await get_db().execute(query))
            known = plan.deleted.setdefault(policies.name, set())
            new = found - known
            known.update(found)
            if new:
                pending.append((policies, new))
        for table in tables:
            for constraint in sorted(table.foreign_key_constraints, key=lambda item: str(item.column_keys)):
                if constraint.referred_table is not parent:
                    continue
                detach = constraint.ondelete == "SET NULL" and table.name not in _OWNED_NULL_LINKS
                found = set()
                for batch in _chunks(keys):
                    # Composite FKs must match as a tuple, never as separate edges.
                    parent_values = select(*(fk.column for fk in constraint.elements)).where(_identity_clause(parent, batch))
                    query = select(*table.primary_key.columns).where(
                        tuple_(*(fk.parent for fk in constraint.elements)).in_(parent_values))
                    if lock and not detach:
                        query = query.order_by(*table.primary_key.columns).with_for_update()
                    found.update(tuple(row) for row in await get_db().execute(query))
                target = plan.detached if detach else plan.deleted
                known = target.setdefault(table.name, set())
                new = found - known
                known.update(found)
                if new and not detach:
                    pending.append((table, new))
    return plan


async def execute(plan: DeletionPlan, tool: Tool) -> list[AfterToolDeletion]:
    """Break nullable internal cycles, then remove children before their parents."""
    tables = {name: Base.metadata.tables[name] for name, keys in plan.deleted.items() if keys}
    children: dict[str, set[str]] = {name: set() for name in tables}
    for name, table in tables.items():
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent in tables and not fk.parent.nullable:
                children[parent].add(name)
    order: list[str] = []
    while children:
        leaves = sorted(name for name, descendants in children.items() if not descendants)
        if not leaves:
            raise ValueError("The Tool dependency graph contains a non-nullable cycle")
        order.extend(leaves)
        for name in leaves:
            del children[name]
        for descendants in children.values():
            descendants.difference_update(leaves)

    db = get_db()
    effects: list[AfterToolDeletion] = []
    for cleanup in _cleanups.values():
        effect = await cleanup(plan.deleted)
        if effect is not None:
            effects.append(effect)
    for name, table in tables.items():
        for fk in table.foreign_keys:
            if fk.column.table.name not in tables or not fk.parent.nullable:
                continue
            for batch in _chunks(plan.deleted[name]):
                # Only rows that will themselves disappear are changed here.
                await db.execute(update(table).where(_identity_clause(table, batch)).values({fk.parent.name: None}))
    for name in order:
        if name == "tools":
            await db.delete(tool)
        else:
            for batch in _chunks(plan.deleted[name]):
                await db.execute(delete(tables[name]).where(_identity_clause(tables[name], batch)))
    # Bulk deletion must not leave preloaded dependent identities usable in-session.
    for entity in list(db.sync_session.identity_map.values()):
        state = inspect(entity)
        if state is not None and state.mapper.local_table.name != "tools" and state.identity in plan.deleted.get(state.mapper.local_table.name, set()):
            db.expunge(entity)
    return effects
