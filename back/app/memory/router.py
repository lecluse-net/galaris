"""RBAC-protected administration API for governed memory."""

from __future__ import annotations
from core.util import require_editorial_client
from fastapi import Depends

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from loguru import logger

from core.authorize import Privileges, authorize, check_privilege
from app.agent import AgentManagementScope, current_management_scope
from core.database import get_db
from core.params import runtime_settings
from core.preview import PdfRenderError
from core.user import get_user_record, HumanActor

from . import (
    item_sharing,
    document_sharing,
    document_tags,
    acquisition_service,
    automation,
    deduplication,
    document_service,
    document_export,
    document_attachment_service,
    document_thumbnail_service,
    facade,
    maintenance,
    metrics,
    service,
)
from .assertions import ManagedDocumentAccessAssertion
from .contracts import MemorySearchItem
from .schemas import (
    GoalFolderReconciliationRequest,
    GoalFolderReconciliationResult,
    DocumentSharing, DocumentSharingUpdate, DocumentSharingLevelUpdate,
    DocumentContentDiff,
    DocumentContentRestore,
    DocumentContentRevisionDetail,
    DocumentContentRevisionPage,
    DocumentCreate,
    DocumentPdfExport,
    DocumentThumbnailRender,
    DocumentLinkRequest,
    DocumentLinkCard,
    DocumentFolderUpdate,
    DocumentFolderOption,
    DocumentGlobalAccessUpdate,
    DocumentLibraryPage,
    DocumentLibraryRequest,
    DocumentTagPublic,
    DocumentOrderMove,
    DocumentOrderSort,
    DocumentIconRequest,
    DocumentIconWrite,
    DocumentTagCatalog,
    DocumentTagDeletionResult,
    DocumentTagWrite,
    DocumentTagMove,
    DocumentTagIconWrite,
    DocumentTagIconPublic,
    DocumentOwnerOptions,
    DocumentOwnerUpdate,
    ManagedDocumentDetail,
    MemoryDuplicatePreview,
    DocumentAttachmentPublic,
    MemoryForgetResult,
    MemoryFilterOptions,
    MemoryFindingAction,
    MemoryFindingPublic,
    MemoryGraphExpandRequest,
    MemoryGraphPage,
    MemoryGraphRootsRequest,
    MemoryGrantUpdate,
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
from .document_apps import AppDatasetRequest, AppDatasetResult, AppGrantUpdate, AppPermissions
from .document_app_service import app_dataset, app_permissions, set_app_permission
from .document_app_security import AppConsentRequired, AppWriteLimitError


router = APIRouter(prefix="/memory", tags=["memory"])


async def _require_app_write(scope: AgentManagementScope) -> None:
    user = await get_user_record(scope.user_id)
    if user is None or not (
        await check_privilege(user, Privileges.MEMORY_EDIT, get_db())
        or await check_privilege(user, Privileges.MEMORY_ADMIN, get_db())
    ):
        raise service.MemoryPermissionError("Dataset edit privilege required.")


@router.get("/documents/{document_id}/app-permissions", response_model=AppPermissions)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_app_permissions(document_id: UUID) -> AppPermissions:
    try:
        return await app_permissions(document_id, await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/documents/{document_id}/app-permissions/{app_key}/{alias}", response_model=AppPermissions)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def update_app_permission(document_id: UUID, app_key: str, alias: str, data: AppGrantUpdate) -> AppPermissions:
    try:
        scope = await current_management_scope()
        if data.access == "write":
            await _require_app_write(scope)
        return await set_app_permission(document_id, app_key, alias, data, scope)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/documents/{document_id}/apps/{app_id}/datasets/{alias}", response_model=AppDatasetResult)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def access_app_dataset(document_id: UUID, app_id: str, alias: str, data: AppDatasetRequest) -> AppDatasetResult:
    try:
        scope = await current_management_scope()
        if data.operation != "read":
            await _require_app_write(scope)
        return await app_dataset(document_id, app_id, alias, data, scope)
    except Exception as exc:
        raise _http_error(exc) from exc


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


async def _require_item_owner_scope(item_id: UUID) -> AgentManagementScope:
    owner_agent_id = await service.get_item_owner_agent_id(item_id)
    if owner_agent_id is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return await _require_agent_scope(owner_agent_id)


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


@router.post(
    "/documents",
    dependencies=[Depends(require_editorial_client)],
    response_model=MemoryItemPublic,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def create_managed_document(data: DocumentCreate) -> MemoryItemPublic:
    """Create a document owned by the caller or by one managed Agent."""

    try:
        scope = await _require_agent_scope(data.actor_agent_id)
        if data.owner_kind == "agent":
            await _require_agent_scope(data.owner_id)
            item = await document_service.create_document(
                owner_agent_id=data.owner_id,
                title=data.title,
                document_type=data.document_type,
                content="{}" if data.document_type == "dataset" else "",
                task_id=None,
                folder=data.folder,
            )
        else:
            current_user = await get_user_record(scope.user_id)
            if current_user is None:
                raise HTTPException(status_code=401, detail="Authentication required")
            owner_user = await get_user_record(data.owner_id)
            if owner_user is None or not owner_user.is_active:
                raise HTTPException(status_code=404, detail="User not found")
            if data.owner_id != scope.user_id and not await check_privilege(
                current_user,
                Privileges.MEMORY_ASSIGN_ALL_USERS,
                get_db(),
            ):
                raise HTTPException(status_code=403, detail="User owner denied")
            item = await document_service.create_user_document(
                owner_user_id=data.owner_id,
                editor_agent_id=data.actor_agent_id,
                title=data.title,
                document_type=data.document_type,
                content="{}" if data.document_type == "dataset" else "",
                folder=data.folder,
            )
        return service.item_to_public(
            item,
            await service.effective_access(item, HumanActor(scope.user_id) if data.owner_kind == "user" else data.actor_agent_id),
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


@router.post("/goal-folders/reconcile", status_code=202, response_model=GoalFolderReconciliationResult)
@authorize(privileges=Privileges.MEMORY_ADMIN)
async def launch_goal_folder_reconciliation(
    data: GoalFolderReconciliationRequest,
) -> GoalFolderReconciliationResult:
    """Queue personal Goal filing; an empty filter requests a global sweep."""
    job_id = await facade.enqueue_goal_folder_reconciliation(user_id=data.user_id, goal_id=data.goal_id)
    await get_db().commit()
    return GoalFolderReconciliationResult(job_id=job_id)


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
        return await service.search_items(data, record_llm_access=False)
    except Exception as exc:
        raise _http_error(exc) from exc


async def _ranked_memory_search(data: MemoryRecallRequest) -> list[MemorySearchItem]:
    return await facade.search_memory(
        data.query,
        agent_id=data.agent_id,
        semantic_query=data.semantic_query,
        limit=data.limit,
        memory_types=data.memory_types,
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
        await _require_agent_scope(data.agent_id)
        return await service.list_graph_roots(data)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/graph/expand", response_model=MemoryGraphPage)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def expand_memory_graph_node(
    data: MemoryGraphExpandRequest,
) -> MemoryGraphPage:
    try:
        await _require_agent_scope(data.agent_id)
        return await service.expand_graph_node(data)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/items/{item_id}/sharing", response_model=DocumentSharing)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_item_sharing(item_id: UUID) -> DocumentSharing:
    try:
        return await item_sharing.sharing(item_id, await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/items/{item_id}/sharing", response_model=DocumentSharing)
@authorize(privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def update_item_sharing(item_id: UUID, data: DocumentSharingLevelUpdate) -> DocumentSharing:
    try:
        return await item_sharing.update_level(item_id, data, await current_management_scope())
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
        )
        return await service.item_to_detail(
            item,
            content,
            access,
            content_type=content_type,
            media_type=media_type,
            revision=revision,
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
        item = await service.update_item(
            item_id,
            data,
            actor_agent_id=actor,
            administrative=administrative,
        )
        access = await service.assert_item_access(
            item, actor, administrative=administrative
        )
        return service.item_to_public(item, access)
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


@router.get("/documents/keywords", response_model=list[str])
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_document_keywords(agent_id: int = Query(gt=0)) -> list[str]:
    """List the keywords available on documents readable by one agent."""

    try:
        await _require_agent_scope(agent_id)
        return await service.list_document_keywords(agent_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/documents/library", response_model=DocumentLibraryPage)
@authorize(
    privileges=[
        Privileges.MEMORY_ACCESS,
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ],
    assertion=ManagedDocumentAccessAssertion,
)
async def browse_managed_documents(
    data: DocumentLibraryRequest,
) -> DocumentLibraryPage:
    """Return the union of documents visible to the caller's managed Agents."""

    try:
        scope = await current_management_scope()
        return await service.browse_document_library(
            data,
            managed_agent_ids=scope.agent_ids, user_id=scope.user_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/documents/icons/resolve", response_model=dict[UUID, str | None])
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def resolve_document_icons(data: DocumentIconRequest) -> dict[UUID, str | None]:
    from . import document_icons

    return await document_icons.resolve(await current_management_scope(), data.document_ids)


@router.put("/documents/{document_id}/icon", response_model=DocumentIconWrite)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN], assertion=ManagedDocumentAccessAssertion)
async def save_document_icon(document_id: UUID, data: DocumentIconWrite) -> DocumentIconWrite:
    from . import document_icons

    try:
        return await document_icons.save(await current_management_scope(), document_id, data)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/documents/order", status_code=204)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def reorder_personal_documents(data: DocumentOrderMove) -> None:
    from .document_order import reorder

    try:
        await reorder(await current_management_scope(), data)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/documents/order/sort", status_code=204)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def sort_personal_documents(data: DocumentOrderSort) -> None:
    from .document_order import sort_children

    try:
        await sort_children((await current_management_scope()).user_id, data)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/documents/tag-icons", response_model=list[DocumentTagIconPublic])
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_personal_tag_icons() -> list[DocumentTagIconPublic]:
    return await document_tags.list_icons((await current_management_scope()).user_id)


@router.post("/documents/tag-icons", response_model=DocumentTagIconPublic)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def upload_personal_tag_icon(data: DocumentTagIconWrite) -> DocumentTagIconPublic:
    try:
        return await document_tags.upload_icon((await current_management_scope()).user_id, data)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/documents/{document_id}/tags", status_code=204)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN], assertion=ManagedDocumentAccessAssertion)
async def move_personal_document(document_id: UUID, data: DocumentTagMove) -> None:
    try:
        await document_tags.move_document(await current_management_scope(), document_id, data.tag_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/documents/tags", response_model=DocumentTagCatalog)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_personal_document_tags() -> DocumentTagCatalog:
    user_id = (await current_management_scope()).user_id
    return DocumentTagCatalog(user_id=user_id, tags=await document_tags.list_tags(user_id))


@router.post("/documents/tags", response_model=DocumentTagPublic)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def create_personal_document_tag(data: DocumentTagWrite) -> DocumentTagPublic:
    try:
        return await document_tags.write_tag((await current_management_scope()).user_id, data)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/documents/tags/{tag_id}", response_model=DocumentTagPublic)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def update_personal_document_tag(tag_id: UUID, data: DocumentTagWrite) -> DocumentTagPublic:
    try:
        return await document_tags.write_tag((await current_management_scope()).user_id, data, tag_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/documents/tags/{tag_id}", response_model=DocumentTagDeletionResult)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def delete_personal_document_tag(tag_id: UUID, confirmed: bool = False) -> DocumentTagDeletionResult:
    try:
        return await document_tags.remove_tag((await current_management_scope()).user_id, tag_id, confirmed=confirmed)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/documents/{document_id}/tags/{tag_id}", status_code=204)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN], assertion=ManagedDocumentAccessAssertion)
async def add_personal_document_tag(document_id: UUID, tag_id: UUID) -> None:
    try:
        await document_tags.assign_tag(await current_management_scope(), document_id, tag_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/documents/{document_id}/tags/{tag_id}", status_code=204)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN], assertion=ManagedDocumentAccessAssertion)
async def remove_personal_document_tag(document_id: UUID, tag_id: UUID) -> None:
    try:
        await document_tags.assign_tag(await current_management_scope(), document_id, tag_id, remove=True)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/documents/folders", response_model=list[str] | list[DocumentFolderOption])
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_document_folders(
    agent_id: int = Query(gt=0), details: bool = Query(default=False),
) -> list[str] | list[DocumentFolderOption]:
    """List logical folders available to the shared document editor."""

    try:
        await _require_agent_scope(agent_id)
        if details:
            return await service.list_document_folder_options(agent_id)
        return await service.list_document_folders(agent_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/documents/owner-options", response_model=DocumentOwnerOptions)
@authorize(privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_document_owner_options(
    search: str = Query(default="", max_length=200),
) -> DocumentOwnerOptions:
    """List Agents and only the Users the caller may select as owner."""

    try:
        scope = await current_management_scope()
        current_user = await get_user_record(scope.user_id)
        if current_user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        include_all_users = await check_privilege(
            current_user,
            Privileges.MEMORY_ASSIGN_ALL_USERS,
            get_db(),
        )
        return await service.list_document_owner_options(
            current_user_id=current_user.id,
            include_all_users=include_all_users,
            managed_agent_ids=scope.agent_ids,
            search=search,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


async def _managed_document_actor(
    document_id: UUID, *, write: bool = False,
) -> tuple[AgentManagementScope, int | HumanActor]:
    scope = await current_management_scope()
    return scope, await document_sharing.document_actor(document_id, scope, write=write)


async def _document_request_actor(document_id: UUID, agent_id: int | None) -> int | HumanActor:
    scope = await current_management_scope()
    if agent_id is None:
        return HumanActor(scope.user_id)
    await _require_agent_scope(agent_id)
    return agent_id


@router.get(
    "/documents/{document_id}/content-revisions",
    response_model=DocumentContentRevisionPage,
)
@authorize(
    privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def list_managed_document_content_revisions(
    document_id: UUID,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> DocumentContentRevisionPage:
    """List every immutable, restorable content version for one document."""

    try:
        _scope, actor_agent_id = await _managed_document_actor(document_id)
        return await service.list_document_content_revisions(
            document_id,
            actor_agent_id=actor_agent_id,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/documents/{document_id}/content-revisions/{revision}",
    response_model=DocumentContentRevisionDetail,
)
@authorize(
    privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def read_managed_document_content_revision(
    document_id: UUID,
    revision: int,
) -> DocumentContentRevisionDetail:
    """Read one historical Markdown version without exposing historical ACLs."""

    try:
        _scope, actor_agent_id = await _managed_document_actor(document_id)
        return await service.get_document_content_revision(
            document_id,
            revision,
            actor_agent_id=actor_agent_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/documents/{document_id}/content-revisions/{revision}/diff",
    response_model=DocumentContentDiff,
)
@authorize(
    privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def diff_managed_document_content_revision(
    document_id: UUID,
    revision: int,
) -> DocumentContentDiff:
    """Compare one historical Markdown version with the current content."""

    try:
        _scope, actor_agent_id = await _managed_document_actor(document_id)
        return await service.diff_document_content_revision(
            document_id,
            revision,
            actor_agent_id=actor_agent_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/documents/{document_id}/content-revisions/{revision}/restore",
    response_model=MemoryItemPublic,
)
@authorize(
    privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def restore_managed_document_content_revision(
    document_id: UUID,
    revision: int,
    data: DocumentContentRestore,
) -> MemoryItemPublic:
    """Restore only content as a new forward version."""

    try:
        _scope, actor_agent_id = await _managed_document_actor(
            document_id,
            write=True,
        )
        updated = await service.restore_document_content_revision(
            document_id,
            revision,
            expected_revision=data.expected_revision,
            actor_agent_id=actor_agent_id,
        )
        return service.item_to_public(
            updated,
            await service.effective_access(updated, actor_agent_id),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/documents/{document_id}/import-image", response_model=DocumentAttachmentPublic)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def import_document_image(document_id: UUID, data: DocumentLinkRequest, actor_agent_id: int | None = Query(default=None, gt=0)) -> DocumentAttachmentPublic:
    from .document_image_import import import_document_image as import_image
    try:
        actor = await _document_request_actor(document_id, actor_agent_id)
        return await import_image(document_id, data.url, actor=actor)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/documents/{document_id}/link-card", response_model=DocumentLinkCard)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def create_document_link_card(document_id: UUID, data: DocumentLinkRequest, actor_agent_id: int | None = Query(default=None, gt=0)) -> DocumentLinkCard:
    from .document_links import create_link_card
    try:
        actor = await _document_request_actor(document_id, actor_agent_id)
        return await create_link_card(document_id, data.url, actor_agent_id=actor)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/documents/{document_id}/export-bundle")
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def export_document_bundle(document_id: UUID, data: DocumentPdfExport, agent_id: int | None = Query(default=None, gt=0)) -> Response:
    try:
        actor = await _document_request_actor(document_id, agent_id)
        content = await document_export.export_document_bundle(document_id, data.html, actor_agent_id=actor)
        return Response(content, media_type="application/zip", headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="document.zip"'})
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/documents/{document_id}/export-pdf")
@authorize(
    privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def export_managed_document_pdf(document_id: UUID, data: DocumentPdfExport) -> Response:
    try:
        scope = await current_management_scope()
        pdf = await document_export.export_document_pdf(
            document_id, data.html, managed_agent_ids=scope.agent_ids, actor=await document_sharing.document_actor(document_id, scope),
        )
        return Response(pdf, media_type="application/pdf", headers={
            "Content-Disposition": 'attachment; filename="document.pdf"',
            "Cache-Control": "no-store",
        })
    except PdfRenderError as exc:
        raise HTTPException(status_code=503, detail="PDF export unavailable") from exc
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/documents/{document_id}/thumbnail", response_class=Response)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_document_thumbnail(
    document_id: UUID, data: DocumentThumbnailRender, agent_id: int | None = Query(default=None, gt=0),
) -> Response:
    try:
        if agent_id is None:
            _, actor = await _managed_document_actor(document_id)
        else:
            actor = await _document_request_actor(document_id, agent_id)
        content = await document_thumbnail_service.read_document_thumbnail(
            document_id, data, actor_agent_id=actor,
        )
        if content is None:
            return Response(status_code=204, headers={"Cache-Control": "private, no-store"})
        return Response(content, media_type="image/png", headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        })
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/documents/{document_id}", response_model=ManagedDocumentDetail)
@authorize(
    privileges=[
        Privileges.MEMORY_ACCESS,
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ],
    assertion=ManagedDocumentAccessAssertion,
)
async def read_managed_document(document_id: UUID) -> ManagedDocumentDetail:
    try:
        scope = await current_management_scope()
        actor = await document_sharing.document_actor(document_id, scope)
        item, content, access, content_type, media_type = await service.get_item(document_id, agent_id=actor)
        return ManagedDocumentDetail(
            item=await service.item_to_detail(item, content, access, content_type=content_type, media_type=media_type),
            agent_id=actor if isinstance(actor, int) else None,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch("/documents/{document_id}", response_model=MemoryItemPublic, dependencies=[Depends(require_editorial_client)])
@authorize(privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def update_human_document(document_id: UUID, data: MemoryItemUpdate) -> MemoryItemPublic:
    try:
        scope = await current_management_scope()
        actor = HumanActor(scope.user_id)
        item = await service.update_item(document_id, data, actor_agent_id=actor)
        return service.item_to_public(item, await service.effective_access(item, actor))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/documents/{document_id}/sharing", response_model=DocumentSharing)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_document_sharing(document_id: UUID) -> DocumentSharing:
    try:
        return await document_sharing.sharing(document_id, await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/documents/{document_id}/sharing", response_model=DocumentSharing)
@authorize(privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def update_document_sharing(document_id: UUID, data: DocumentSharingUpdate) -> DocumentSharing:
    try:
        return await document_sharing.update_sharing(document_id, data, await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/documents/{document_id}/sharing-level", response_model=DocumentSharing)
@authorize(privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def update_document_sharing_level(document_id: UUID, data: DocumentSharingLevelUpdate) -> DocumentSharing:
    try:
        return await document_sharing.update_level(document_id, data, await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch("/documents/{document_id}/folder", response_model=MemoryItemPublic)
@authorize(
    privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def move_managed_document(
    document_id: UUID,
    data: DocumentFolderUpdate,
) -> MemoryItemPublic:
    """Move one writable managed document to a logical folder."""

    try:
        scope = await current_management_scope()
        actor = await document_sharing.document_actor(document_id, scope, write=True)
        item, *_ = await service.get_item(document_id, agent_id=actor)
        metadata = dict(item.metadata_)
        if data.folder:
            metadata["document_path"] = data.folder
        else:
            metadata.pop("document_path", None)
        updated = await service.update_item(
            document_id,
            MemoryItemUpdate(
                expected_revision=data.expected_revision,
                expected_lock_version=data.expected_lock_version,
                metadata=metadata,
            ),
            actor_agent_id=actor,
        )
        return service.item_to_public(
            updated,
            await service.effective_access(updated, actor),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch("/documents/{document_id}/owner", response_model=MemoryItemPublic)
@authorize(
    privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def change_document_owner(
    document_id: UUID,
    data: DocumentOwnerUpdate,
) -> MemoryItemPublic:
    """Transfer one writable document to an Agent or an authorized User."""

    try:
        scope = await current_management_scope()
        actor = await document_sharing.document_actor(document_id, scope, write=True)
        item, *_ = await service.get_item(document_id, agent_id=actor)
        current_user = await get_user_record(scope.user_id)
        owns_document = (
            scope.allows(item.owner_agent_id)
            or item.owner_user_id == scope.user_id
        )
        if not owns_document and not await check_privilege(
            current_user,
            Privileges.MEMORY_ADMIN,
            get_db(),
        ):
            raise service.MemoryPermissionError(
                "Only the document owner can transfer ownership."
            )
        if data.kind == "agent" and not scope.allows(data.id):
            raise HTTPException(status_code=404, detail="Agent not found")
        if data.kind == "user" and data.id != scope.user_id:
            if not await check_privilege(
                current_user,
                Privileges.MEMORY_ASSIGN_ALL_USERS,
                get_db(),
            ):
                raise HTTPException(status_code=403, detail="User owner denied")
        updated = await service.transfer_document_owner(
            document_id,
            data,
            actor_agent_id=actor,
        )
        access = await service.effective_access(updated, actor)
        return service.item_to_public(updated, access)
    except Exception as exc:
        raise _http_error(exc) from exc


async def _assert_can_manage_document_grants(
    document_id: UUID, *, target_agent_id: int | None = None,
) -> tuple[AgentManagementScope, int | HumanActor]:
    scope = await current_management_scope()
    item = await service.document_record(document_id)
    if item is None or not await document_sharing.can_manage(item, scope):
        raise service.MemoryPermissionError("Only the document owner can manage sharing")
    if target_agent_id is not None and not scope.allows(target_agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return scope, await document_sharing.document_actor(document_id, scope, write=True)


@router.patch(
    "/documents/{document_id}/global-access",
    response_model=MemoryItemPublic,
)
@authorize(
    privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def set_managed_document_global_access(
    document_id: UUID,
    data: DocumentGlobalAccessUpdate,
) -> MemoryItemPublic:
    """Set the access inherited by every current and future Agent."""

    try:
        _scope, actor_agent_id = await _assert_can_manage_document_grants(document_id)
        updated = await service.set_document_global_access(
            document_id,
            data,
            actor_agent_id=actor_agent_id if isinstance(actor_agent_id, int) else None,
        )
        return service.item_to_public(
            updated,
            await service.effective_access(updated, actor_agent_id),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put(
    "/documents/{document_id}/collaborators/{agent_id}",
    response_model=MemoryItemPublic,
)
@authorize(
    privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def set_managed_document_grant(
    document_id: UUID,
    agent_id: int,
    data: MemoryGrantUpdate,
) -> MemoryItemPublic:
    """Update sharing as the managed Agent owner or current User owner."""

    try:
        _scope, actor_agent_id = await _assert_can_manage_document_grants(
            document_id,
            target_agent_id=agent_id,
        )
        updated = await service.set_item_grant(
            document_id,
            agent_id,
            data,
            actor_agent_id=actor_agent_id if isinstance(actor_agent_id, int) else None,
        )
        return service.item_to_public(
            updated,
            await service.effective_access(updated, actor_agent_id),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/documents/{document_id}/collaborators/{agent_id}",
    response_model=MemoryItemPublic,
)
@authorize(
    privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def remove_managed_document_grant(
    document_id: UUID,
    agent_id: int,
    expected_lock_version: int | None = Query(default=None, ge=1),
) -> MemoryItemPublic:
    """Remove sharing as the managed Agent owner or current User owner."""

    try:
        _scope, actor_agent_id = await _assert_can_manage_document_grants(
            document_id,
            target_agent_id=agent_id,
        )
        updated = await service.remove_item_grant(
            document_id,
            agent_id,
            actor_agent_id=actor_agent_id if isinstance(actor_agent_id, int) else None,
            expected_lock_version=expected_lock_version,
        )
        return service.item_to_public(
            updated,
            await service.effective_access(updated, actor_agent_id),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/documents/{document_id}/attachments",
    response_model=list[DocumentAttachmentPublic],
)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def list_document_attachments(
    document_id: UUID,
    agent_id: int | None = Query(default=None, gt=0),
) -> list[DocumentAttachmentPublic]:
    try:
        actor = await _document_request_actor(document_id, agent_id)
        return await document_attachment_service.list_document_attachments(
            document_id,
            actor_agent_id=actor,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/documents/{document_id}/attachments",
    response_model=DocumentAttachmentPublic,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def add_document_attachment(
    document_id: UUID,
    file: UploadFile = File(...),
    actor_agent_id: int | None = Query(default=None, gt=0),
) -> DocumentAttachmentPublic:
    try:
        actor = await _document_request_actor(document_id, actor_agent_id)
        return await document_attachment_service.add_document_attachment(
            document_id,
            actor_agent_id=actor,
            upload=file,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/documents/{document_id}/attachments/{attachment_id}/thumbnail",
    response_class=Response,
)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_document_attachment_thumbnail(
    document_id: UUID,
    attachment_id: UUID,
    agent_id: int | None = Query(default=None, gt=0),
) -> Response:
    """Return a small cached preview without transferring the full attachment."""

    try:
        actor = await _document_request_actor(document_id, agent_id)
        content = await document_thumbnail_service.read_or_schedule_document_attachment_thumbnail(
            document_id,
            attachment_id,
            actor_agent_id=actor,
        )
        if content is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail pending")
        return Response(
            content=content,
            media_type="image/png",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/documents/{document_id}/attachments/{attachment_id}/info",
    response_model=DocumentAttachmentPublic,
)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_document_attachment_info(
    document_id: UUID, attachment_id: UUID, agent_id: int | None = Query(default=None, gt=0),
) -> DocumentAttachmentPublic:
    try:
        actor = await _document_request_actor(document_id, agent_id)
        attachment, _path = await document_attachment_service.document_attachment_path(
            document_id, attachment_id, actor_agent_id=actor,
        )
        return attachment
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/documents/{document_id}/attachments/{attachment_id}",
    response_class=FileResponse,
)
@authorize(privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def read_document_attachment(
    document_id: UUID,
    attachment_id: UUID,
    agent_id: int | None = Query(default=None, gt=0),
) -> FileResponse:
    try:
        actor = await _document_request_actor(document_id, agent_id)
        attachment, path = await document_attachment_service.document_attachment_path(
            document_id,
            attachment_id,
            actor_agent_id=actor,
        )
        return FileResponse(
            path,
            media_type=attachment.media_type,
            filename=attachment.name,
            content_disposition_type="inline",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/documents/{document_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def delete_document_attachment(
    document_id: UUID,
    attachment_id: UUID,
    actor_agent_id: int | None = Query(default=None, gt=0),
) -> Response:
    try:
        actor = await _document_request_actor(document_id, actor_agent_id)
        await document_attachment_service.delete_document_attachment(
            document_id,
            attachment_id,
            actor_agent_id=actor,
        )
        await document_thumbnail_service.delete_document_attachment_thumbnail(
            document_id,
            attachment_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put(
    "/documents/{document_id}/grants/{agent_id}",
    response_model=MemoryItemPublic,
)
@authorize(privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def set_document_grant(
    document_id: UUID,
    agent_id: int,
    data: MemoryGrantUpdate,
    owner_agent_id: int = Query(gt=0),
) -> MemoryItemPublic:
    """Let a document owner grant read or edit access to one agent."""

    try:
        scope = await _require_agent_scope(owner_agent_id)
        if not scope.allows(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        await document_service.share_document(
            document_id,
            owner_agent_id=owner_agent_id,
            target_agent_id=agent_id,
            access="edit" if data.can_write else "read",
            task_id=None,
        )
        item, _content, access, _content_type, _media_type = await service.get_item(
            document_id,
            agent_id=owner_agent_id,
        )
        return service.item_to_public(item, access)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/documents/{document_id}/grants/{agent_id}",
    response_model=MemoryItemPublic,
)
@authorize(privileges=[Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN])
async def remove_document_grant(
    document_id: UUID,
    agent_id: int,
    owner_agent_id: int = Query(gt=0),
) -> MemoryItemPublic:
    """Let a document owner remove one collaborator's access."""

    try:
        scope = await _require_agent_scope(owner_agent_id)
        if not scope.allows(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        await document_service.share_document(
            document_id,
            owner_agent_id=owner_agent_id,
            target_agent_id=agent_id,
            access="none",
            task_id=None,
        )
        item, _content, access, _content_type, _media_type = await service.get_item(
            document_id,
            agent_id=owner_agent_id,
        )
        return service.item_to_public(item, access)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/items/{item_id}/grants/{agent_id}", response_model=MemoryItemPublic)
@authorize(privileges=Privileges.MEMORY_ADMIN)
async def set_memory_item_grant(
    item_id: UUID, agent_id: int, data: MemoryGrantUpdate
) -> MemoryItemPublic:
    try:
        await _require_item_owner_scope(item_id)
        await _require_agent_scope(agent_id)
        item = await service.set_item_grant(item_id, agent_id, data)
        access = await service.assert_item_access(item, None, administrative=True)
        return service.item_to_public(item, access)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/items/{item_id}/grants/{agent_id}", response_model=MemoryItemPublic)
@authorize(privileges=Privileges.MEMORY_ADMIN)
async def remove_memory_item_grant(
    item_id: UUID, agent_id: int
) -> MemoryItemPublic:
    try:
        await _require_item_owner_scope(item_id)
        await _require_agent_scope(agent_id)
        item = await service.remove_item_grant(item_id, agent_id)
        access = await service.assert_item_access(item, None, administrative=True)
        return service.item_to_public(item, access)
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
