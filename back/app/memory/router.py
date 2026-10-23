"""RBAC-protected administration API for governed memory."""

from __future__ import annotations
from core.util import require_editorial_client, local_timezone_name
from fastapi import Depends

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from loguru import logger

from core.authorize import Privileges, authorize
from app.agent import AgentManagementScope, current_management_scope
from core.params import runtime_settings
from core.user import HumanActor

from . import acquisition_service, automation, deduplication, facade, maintenance, metrics, retrieval, service
from .contracts import MemorySearchItem
from .schemas import (
    MemoryDuplicatePreview,
    MemoryForgetResult,
    MemoryFilterOptions,
    MemoryFindingAction,
    MemoryFindingPublic,
    MemoryGraphExpandRequest,
    MemoryGraphPage,
    MemoryGraphRootsRequest,
    MemoryItemCreate,
    MemoryItemDetail,
    MemoryItemPublic,
    MemoryItemUpdate,
    ManualMemoryLinkCreate,
    MemoryLinkCreate,
    MemoryLinkPublic,
    MemoryLinkReconciliationRunResult,
    MemoryLinkReconciliationStatus,
    MemoryRecallRequest,
    MemoryRetentionPreview,
    RecentMemoryItem,
    MemoryRevisionPublic,
    MemorySearchPage,
    MemorySearchRequest,
)
from .link_reconciliation import reconcile_memory_links
from . import graph_state
from app.document.interface import AppConsentRequired, AppWriteLimitError


router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/temporal/defaults")
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def temporal_defaults() -> dict[str, str | int]:
    return {"timezone": local_timezone_name(),
            "lookahead_hours": runtime_settings.MEMORY_TEMPORAL_LOOKAHEAD_HOURS}









async def _require_agent_scope(
    agent_id: int | None,
    *,
    allow_global: bool = False,
) -> AgentManagementScope:
    scope = await current_management_scope()
    if agent_id is None:
        if allow_global and scope.is_global:
            return scope
        raise HTTPException(status_code=403, detail="Agent management scope required")
    if not scope.allows(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return scope




@router.get("/recent", response_model=list[RecentMemoryItem])
@authorize(
    privileges=[
        Privileges.MEMORY_ACCESS,
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ]
)
async def read_recent_memories(
    limit: int = Query(default=8, ge=1, le=50),
) -> list[RecentMemoryItem]:
    """List recent memories in the caller's exact Agent-management scope."""

    scope = await current_management_scope()
    return await service.list_recent_memories(
        managed_agent_ids=scope.agent_ids,
        limit=limit,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, AppConsentRequired):
        return HTTPException(status_code=403, detail={"code": "permission_required", "message": str(exc)})
    if isinstance(exc, AppWriteLimitError):
        return HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "60"})
    if isinstance(exc, service.MemoryNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, service.MemoryPermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, service.MemoryConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (ValueError, service.MemoryError)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    reference = uuid4().hex[:12]
    logger.exception("Unexpected Memory API failure reference={}", reference)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected memory error. Reference: {reference}.",
    )


@router.post(
    "/items", dependencies=[Depends(require_editorial_client)], response_model=MemoryItemPublic, status_code=status.HTTP_201_CREATED
)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def create_memory_item(data: MemoryItemCreate) -> MemoryItemPublic:
    try:
        await _require_agent_scope(data.owner_agent_id)
        item = await acquisition_service.create_manual_item(data)
        return service.item_to_public(
            item, await service.assert_item_access(item, None, administrative=True)
        )
    except Exception as exc:
        raise _http_error(exc) from exc




@router.get("/metrics")
@authorize(
    privileges=[
        Privileges.MEMORY_ACCESS,
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ]
)
async def read_memory_metrics() -> dict[str, list[dict[str, Any]]]:
    """Return content-free process-local recall diagnostics."""

    await _require_agent_scope(None, allow_global=True)
    return metrics.snapshot()


@router.get(
    "/link-reconciliation",
    response_model=MemoryLinkReconciliationStatus,
)
@authorize(
    privileges=[
        Privileges.PARAMS_ACCESS,
        Privileges.PARAMS_EDIT,
        Privileges.MEMORY_ADMIN,
    ]
)
async def read_link_reconciliation_status() -> MemoryLinkReconciliationStatus:
    """Return the configured triggers and latest durable global sweep."""

    await _require_agent_scope(None, allow_global=True)
    return await automation.get_link_reconciliation_status()


@router.post(
    "/link-reconciliation",
    response_model=MemoryLinkReconciliationRunResult,
)
@authorize(privileges=Privileges.MEMORY_ADMIN)
async def launch_link_reconciliation() -> MemoryLinkReconciliationRunResult:
    """Run one idempotent global sweep immediately in this request."""

    await _require_agent_scope(None, allow_global=True)
    result = await reconcile_memory_links(item_id=None, families=None)
    return MemoryLinkReconciliationRunResult.model_validate(result.model_dump())




@router.get("/retention/preview", response_model=MemoryRetentionPreview)
@authorize(
    privileges=[
        Privileges.MEMORY_ACCESS,
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ]
)
async def estimate_memory_retention(
    days: int = Query(default=365, ge=0, le=36_500),
) -> MemoryRetentionPreview:
    """Preview a global inactivity duration without enabling deletion."""

    await _require_agent_scope(None, allow_global=True)
    return await service.preview_retention(days)


@router.get("/duplicates/preview", response_model=MemoryDuplicatePreview)
@authorize(
    privileges=[
        Privileges.MEMORY_ACCESS,
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ]
)
async def estimate_memory_duplicates(
    limit: int = Query(default=100, ge=1, le=500),
    agent_id: int | None = Query(default=None, gt=0),
) -> MemoryDuplicatePreview:
    """Preview near-duplicate ordinary memories without mutating them."""

    await _require_agent_scope(agent_id, allow_global=True)
    return await deduplication.preview_duplicate_pairs(
        threshold=runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD,
        limit=limit,
        agent_id=agent_id,
    )


@router.get("/findings", response_model=list[MemoryFindingPublic])
@authorize(
    privileges=[
        Privileges.MEMORY_ACCESS,
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ]
)
async def list_memory_findings(
    agent_id: int = Query(gt=0),
    item_id: UUID | None = Query(default=None),
    finding_status: str = Query(default="pending", pattern="^(pending|applied|dismissed|obsolete|error)$"),
    limit: int = Query(default=500, ge=1, le=500),
) -> list[MemoryFindingPublic]:
    """List deterministic maintenance findings without exposing them as Dream work."""

    await _require_agent_scope(agent_id)
    return await maintenance.list_findings(
        agent_id=agent_id,
        item_id=item_id,
        status=finding_status,
        limit=limit,
    )


@router.post("/findings/{finding_id}/apply", response_model=MemoryFindingPublic)
@authorize(privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def apply_memory_finding(
    finding_id: UUID, data: MemoryFindingAction
) -> MemoryFindingPublic:
    try:
        agent_id = await maintenance.get_finding_agent_id(finding_id)
        if agent_id is None:
            raise service.MemoryNotFoundError("Memory finding not found.")
        await _require_agent_scope(agent_id)
        return await maintenance.apply_finding(
            finding_id,
            canonical_item_id=data.canonical_item_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/findings/{finding_id}/dismiss", response_model=MemoryFindingPublic)
@authorize(privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def dismiss_memory_finding(finding_id: UUID) -> MemoryFindingPublic:
    try:
        agent_id = await maintenance.get_finding_agent_id(finding_id)
        if agent_id is None:
            raise service.MemoryNotFoundError("Memory finding not found.")
        await _require_agent_scope(agent_id)
        return await maintenance.dismiss_finding(finding_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/browse", response_model=MemorySearchPage)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def browse_memory(data: MemorySearchRequest) -> MemorySearchPage:
    try:
        await _require_agent_scope(data.agent_id)
        return await retrieval.browse_items(data)
    except Exception as exc:
        raise _http_error(exc) from exc


async def _ranked_memory_search(data: MemoryRecallRequest) -> list[MemorySearchItem]:
    return await facade.search_memory(
        data.query,
        agent_id=data.agent_id,
        target_at=data.target_at,
        exclude_temporal=data.exclude_temporal,
        keyword=data.keyword,
        filter_topic_item_id=data.filter_topic_item_id,
        filter_contact_item_id=data.filter_contact_item_id,
        semantic_query=data.semantic_query,
        limit=data.limit,
        node_kinds=data.node_kinds,
        memory_role=data.memory_role,
        task_id=data.task_id,
        topic_item_id=data.topic_item_id,
        contact_item_id=data.contact_item_id,
        strict_contact_scope=data.strict_contact_scope,
        exclude_source_managed=data.exclude_source_managed,
    )


@router.post("/search", response_model=list[MemorySearchItem])
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def search_memory(data: MemoryRecallRequest) -> list[MemorySearchItem]:
    """Return the canonical score-free relevance ranking."""

    try:
        await _require_agent_scope(data.agent_id)
        return await _ranked_memory_search(data)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/filter-options", response_model=MemoryFilterOptions)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_memory_filter_options(
    agent_id: int = Query(gt=0),
) -> MemoryFilterOptions:
    try:
        await _require_agent_scope(agent_id)
        return await service.list_filter_options(agent_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/recall",
    response_model=list[MemorySearchItem],
    deprecated=True,
)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def recall_memory(data: MemoryRecallRequest) -> list[MemorySearchItem]:
    """Compatibility alias for the canonical score-free search endpoint."""

    try:
        await _require_agent_scope(data.agent_id)
        return await _ranked_memory_search(data)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/graph/roots", response_model=MemoryGraphPage)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def list_memory_graph_roots(
    data: MemoryGraphRootsRequest,
) -> MemoryGraphPage:
    try:
        scope = await _require_agent_scope(data.agent_id)
        page = await service.list_graph_roots(data)
        if data.include_saved_positions:
            points = await graph_state.page_positions(
                graph_state.GraphContext(**data.model_dump(include={"agent_id", "query", "topic_item_id", "contact_item_id"})),
                scope, [node.id for node in page.nodes],
            )
            page.positions = {str(key): (point.x, point.y) for key, point in points.items()}
        return page
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/graph/state/read", response_model=graph_state.GraphState)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_memory_graph_state(data: graph_state.GraphContext) -> graph_state.GraphState:
    try:
        return await graph_state.read_state(data, await _require_agent_scope(data.agent_id))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/graph/state", response_model=graph_state.GraphState)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def write_memory_graph_state(data: graph_state.GraphStateWrite) -> graph_state.GraphState:
    try:
        return await graph_state.write_state(data, await _require_agent_scope(data.agent_id))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/graph/expand", response_model=MemoryGraphPage)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def expand_memory_graph_node(
    data: MemoryGraphExpandRequest,
) -> MemoryGraphPage:
    try:
        scope = await _require_agent_scope(data.agent_id)
        page = await service.expand_graph_node(data)
        if data.include_saved_positions:
            points = await graph_state.page_positions(
                graph_state.GraphContext(**data.model_dump(include={"agent_id", "query", "topic_item_id", "contact_item_id"})),
                scope, [node.id for node in page.nodes],
            )
            page.positions = {str(key): (point.x, point.y) for key, point in points.items()}
        return page
    except Exception as exc:
        raise _http_error(exc) from exc






async def _item_request_actor(agent_id: int | None) -> tuple[int | HumanActor | None, bool]:
    if agent_id is not None:
        await _require_agent_scope(agent_id)
        return agent_id, False
    scope = await current_management_scope()
    return (None, True) if scope.is_global else (HumanActor(scope.user_id), False)


@router.get("/items/{item_id}", response_model=MemoryItemDetail)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def get_memory_item(
    item_id: UUID,
    agent_id: int | None = Query(default=None, gt=0),
    revision: int | None = Query(default=None, ge=1),
) -> MemoryItemDetail:
    try:
        actor, administrative = await _item_request_actor(agent_id)
        item, content, access, content_type, media_type = await service.get_item(
            item_id,
            agent_id=actor,
            administrative=administrative,
            revision=revision,
            record_llm_access=False,
            include_revisions=False,
            memory_content=True,
        )
        return await service.item_to_detail(
            item,
            content,
            access,
            content_type=content_type,
            media_type=media_type,
            revision=revision,
            memory_content=True,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/items/{item_id}/revisions", response_model=list[MemoryRevisionPublic]
)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def list_memory_revisions(
    item_id: UUID, agent_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
) -> list[MemoryRevisionPublic]:
    try:
        await _require_agent_scope(agent_id, allow_global=True)
        return await service.list_revisions(
            item_id, agent_id=agent_id, administrative=agent_id is None, limit=limit, offset=offset,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/items/{item_id}", dependencies=[Depends(require_editorial_client)], response_model=MemoryItemPublic)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def update_memory_item(
    item_id: UUID,
    data: MemoryItemUpdate,
    actor_agent_id: int | None = Query(default=None, gt=0),
) -> MemoryItemPublic:
    try:
        actor, administrative = await _item_request_actor(actor_agent_id)
        item = await service.update_memory_content(
            item_id,
            data,
            actor_agent_id=actor,
            administrative=administrative,
        )
        access = await service.assert_item_access(
            item, actor, administrative=administrative
        )
        return service.item_to_public(item, access, memory_content=True)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/items/{item_id}", response_model=MemoryForgetResult)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def forget_memory_item(
    item_id: UUID,
    actor_agent_id: int | None = Query(default=None, gt=0),
) -> MemoryForgetResult:
    try:
        actor, administrative = await _item_request_actor(actor_agent_id)
        return await service.forget_item(
            item_id,
            actor_agent_id=actor,
            administrative=administrative,
        )
    except Exception as exc:
        raise _http_error(exc) from exc

























































































































@router.post(
    "/links", response_model=MemoryLinkPublic, status_code=status.HTTP_201_CREATED
)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def create_memory_link(
    data: ManualMemoryLinkCreate,
    actor_agent_id: int | None = Query(default=None, gt=0),
) -> MemoryLinkPublic:
    try:
        await _require_agent_scope(actor_agent_id, allow_global=True)
        link = await service.create_link(
            MemoryLinkCreate.model_validate(data.model_dump()),
            actor_agent_id=actor_agent_id,
            administrative=actor_agent_id is None,
        )
        return service.link_to_public(link)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/items/{item_id}/links", response_model=list[MemoryLinkPublic])
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def list_memory_links(
    item_id: UUID,
    actor_agent_id: int | None = Query(default=None, gt=0),
) -> list[MemoryLinkPublic]:
    try:
        await _require_agent_scope(actor_agent_id, allow_global=True)
        links = await service.list_links(
            item_id,
            actor_agent_id=actor_agent_id,
            administrative=actor_agent_id is None,
        )
        return [service.link_to_public(link) for link in links]
    except Exception as exc:
        raise _http_error(exc) from exc
