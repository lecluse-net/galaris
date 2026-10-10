"""Private graph snapshots, incremental writes and optimistic concurrency.

Coordinates never grant access: reads use IDs from an already checked graph page,
and writes check canonical and live source access before admitting coordinates.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.agent import AgentManagementScope
from core.database import get_db

from .models import MemoryContextEdge, MemoryContextNode, MemoryGraphPosition, MemoryGraphView, MemoryItem
from .schemas import MemoryGraphRootsRequest
from .service import MemoryConflictError, MemoryPermissionError, graph_item_filters
from .source_access import readable_source_ids

GraphKind = Literal["memory", "document", "attachment", "folder", "file", "directory", "topic", "contact", "conversation"]
GraphCoordinate3d = Annotated[float, Field(ge=-1e15, le=1e15)]
GraphRegionPages = Annotated[int, Field(ge=1, le=10_000)]


class GraphPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float = Field(ge=-1e15, le=1e15)
    y: float = Field(ge=-1e15, le=1e15)


class GraphCamera(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    center: tuple[float, float] | None = None
    zoom: float = Field(ge=0.2, le=1_000_000)


class GraphCamera3d(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    position: tuple[GraphCoordinate3d, GraphCoordinate3d, GraphCoordinate3d]
    target: tuple[GraphCoordinate3d, GraphCoordinate3d, GraphCoordinate3d]
    layout_version: int = Field(default=1, ge=1, le=2)


class GraphPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden_entity_kinds: list[GraphKind] = Field(default_factory=lambda: list[GraphKind](), max_length=9)
    expanded_branches: list[UUID] = Field(default_factory=lambda: list[UUID](), max_length=10_000)
    camera: GraphCamera | None = None
    camera_3d: GraphCamera3d | None = None
    resource_branches: dict[UUID, GraphRegionPages] = Field(default_factory=lambda: dict[UUID, GraphRegionPages](), max_length=10_000)


class GraphPreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden_entity_kinds: list[GraphKind] | None = Field(default=None, max_length=9)
    expanded_branches: list[UUID] | None = Field(default=None, max_length=10_000)
    camera: GraphCamera | None = None
    camera_3d: GraphCamera3d | None = None
    resource_branches: dict[UUID, GraphRegionPages] | None = Field(default=None, max_length=10_000)


class GraphContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: int = Field(gt=0)
    query: str = Field(default="", max_length=2_000)
    topic_item_id: UUID | None = None
    contact_item_id: UUID | None = None

    def cache_key(self) -> str:
        identity = ["2d-v1", self.query.strip(), str(self.topic_item_id or ""), str(self.contact_item_id or "")]
        return sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


class GraphStateWrite(GraphContext):
    expected_revision: int = Field(ge=0)
    positions: dict[UUID, GraphPoint] = Field(default_factory=lambda: dict[UUID, GraphPoint](), max_length=500)
    preferences: GraphPreferencesPatch = Field(default_factory=GraphPreferencesPatch)


class GraphState(BaseModel):
    format_version: Literal[1] = 1
    revision: int = 0
    preferences: GraphPreferences = Field(default_factory=GraphPreferences)
    positions: dict[UUID, GraphPoint] = Field(default_factory=lambda: dict[UUID, GraphPoint]())


def _check_scope(context: GraphContext, scope: AgentManagementScope) -> None:
    if not scope.allows(context.agent_id):
        raise MemoryPermissionError("Agent management scope required.")


async def _view(context: GraphContext, scope: AgentManagementScope, *, lock: bool = False) -> MemoryGraphView | None:
    query = select(MemoryGraphView).where(
        MemoryGraphView.user_id == scope.user_id,
        MemoryGraphView.agent_id == context.agent_id,
        MemoryGraphView.context_key == context.cache_key(),
    ).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    return await get_db().scalar(query)


async def read_state(context: GraphContext, scope: AgentManagementScope) -> GraphState:
    _check_scope(context, scope)
    view = await _view(context, scope)
    if view is None:
        return GraphState()
    preferences = GraphPreferences.model_validate(view.preferences)
    # A stale expansion must not expose the identity of a revoked node.
    allowed = await _admissible(context, set(preferences.expanded_branches) | set(preferences.resource_branches))
    preferences.expanded_branches = [key for key in preferences.expanded_branches if key in allowed]
    preferences.resource_branches = {key: pages for key, pages in preferences.resource_branches.items() if key in allowed}
    return GraphState(revision=view.revision, preferences=preferences)


async def page_positions(context: GraphContext, scope: AgentManagementScope, checked_keys: list[UUID]) -> dict[UUID, GraphPoint]:
    """Call only with nodes from the graph API's live-source-checked page."""
    _check_scope(context, scope)
    if not checked_keys:
        return {}
    view = await _view(context, scope)
    if view is None:
        return {}
    rows = await get_db().scalars(select(MemoryGraphPosition).where(
        MemoryGraphPosition.view_id == view.id, MemoryGraphPosition.node_key.in_(checked_keys),
    ))
    return {row.node_key: GraphPoint(x=row.x, y=row.y) for row in rows}


async def _admissible(context: GraphContext, keys: set[UUID]) -> set[UUID]:
    if not keys:
        return set()
    db = get_db()
    request = MemoryGraphRootsRequest(**context.model_dump())
    filters = graph_item_filters(request, now=datetime.now(timezone.utc))
    # Chunk to keep permission checks independent of a large expansion list.
    allowed: set[UUID] = set()
    identities = list(keys)
    for offset in range(0, len(identities), 500):
        batch = identities[offset:offset + 500]
        rows = await db.scalars(select(MemoryItem.id).where(
            MemoryItem.id.in_(batch), *filters,
        ))
        allowed.update(await readable_source_ids(set(rows), context.agent_id))
        contexts = (await db.execute(select(MemoryContextNode.id, MemoryContextEdge.item_id).join(
            MemoryContextEdge, MemoryContextEdge.context_node_id == MemoryContextNode.id,
        ).where(
            MemoryContextNode.id.in_(batch), MemoryContextNode.owner_agent_id == context.agent_id,
            MemoryContextEdge.item_id.in_(select(MemoryItem.id).where(*filters)),
        ).distinct())).tuples().all()
        linked = await readable_source_ids({item for _node, item in contexts}, context.agent_id)
        allowed.update(node for node, item in contexts if item in linked)
    return allowed


async def write_state(request: GraphStateWrite, scope: AgentManagementScope) -> GraphState:
    _check_scope(request, scope)
    db = get_db()
    changes = request.preferences.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    if "camera" in request.preferences.model_fields_set:
        changes["camera"] = request.preferences.camera.model_dump(mode="json") if request.preferences.camera else None
    if "camera_3d" in request.preferences.model_fields_set:
        changes["camera_3d"] = request.preferences.camera_3d.model_dump(mode="json") if request.preferences.camera_3d else None
    keys = set(request.positions)
    if request.preferences.expanded_branches is not None:
        keys.update(request.preferences.expanded_branches)
    if request.preferences.resource_branches is not None:
        keys.update(request.preferences.resource_branches)
    allowed = await _admissible(request, keys)
    if request.preferences.expanded_branches is not None:
        changes["expanded_branches"] = [str(key) for key in request.preferences.expanded_branches if key in allowed]
    if request.preferences.resource_branches is not None:
        changes["resource_branches"] = {str(key): pages for key, pages in request.preferences.resource_branches.items() if key in allowed}
    await db.execute(insert(MemoryGraphView).values(
        user_id=scope.user_id, agent_id=request.agent_id, context_key=request.cache_key(),
    ).on_conflict_do_nothing(index_elements=["user_id", "agent_id", "context_key"]))
    view = await _view(request, scope, lock=True)
    assert view is not None
    if view.revision != request.expected_revision:
        raise MemoryConflictError("Graph view changed; reload its revision before saving.")
    if changes:
        view.preferences = {**view.preferences, **changes}
    values = [{"view_id": view.id, "node_key": key, "x": point.x, "y": point.y}
              for key, point in request.positions.items() if key in allowed]
    if values:
        # Existing coordinates are anchors. A concurrent cold tab cannot replace them.
        await db.execute(insert(MemoryGraphPosition).values(values).on_conflict_do_nothing(
            index_elements=["view_id", "node_key"],
        ))
    view.revision += 1
    view.updated_at = datetime.now(timezone.utc)
    await db.flush()
    result = await read_state(request, scope)
    result.positions = await page_positions(request, scope, list(request.positions.keys() & allowed))
    await db.commit()
    return result
