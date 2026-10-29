"""RBAC-protected administration API for editorial Documents."""

from __future__ import annotations
from core.util import require_editorial_client, source_code_response_headers
from fastapi import Depends

from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from loguru import logger

from core.authorize import Privileges, authorize, check_privilege
from app.agent import AgentManagementScope, current_management_scope
from core.database import get_db
from core.storage import FileRename
from core.preview import PdfRenderError
from core.user import get_current_user, get_user_record, HumanActor

from . import (
    document_sharing,
    document_tags,
    document_service,
    document_export,
    document_attachment_service,
    dataset_attachments,
    process_references,
    internal_attachments,
    document_thumbnail_service,
    resource_service as service,
)
from .assertions import ManagedDocumentAccessAssertion
from .schemas import (
    DocumentProcessAttachmentWrite,
    DocumentInternalAttachmentWrite,
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
    DocumentParentMove,
    DocumentTagIconWrite,
    DocumentTagIconPublic,
    DocumentOwnerOptions,
    DocumentOwnerUpdate,
    ManagedDocumentDetail,
    DocumentResourceRedirect,
    DocumentDatasetAttachment,
    DocumentDatasetAttachments,
    DocumentDatasetAttachmentWrite,
    DocumentAttachmentPublic,
    DocumentDeletionResult,
    DocumentGrantUpdate,
    DocumentPublic,
    DocumentDetail,
    GoalFolderReconciliationRequest,
    GoalFolderReconciliationResult,
    DocumentUpdate,
)
from .document_apps import AppDatasetRequest, AppDatasetResult, AppGrantUpdate, AppPermissions
from .document_app_service import app_dataset, app_permissions, set_app_permission
from .document_app_security import AppConsentRequired, AppWriteLimitError


router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/types")
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_document_types() -> list[dict[str, str]]:
    from .type_registry import DOCUMENT_TYPES
    return [{"code": definition.code, "media_type": definition.media_type,
             "storage_kind": definition.storage_kind, "icon": definition.icon} for definition in DOCUMENT_TYPES]


@router.get("/folder-collections")
@router.get("/folder-collections/{folder_id}")
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_folder_collection(folder_id: UUID | None = None,
    agent_id: int | None = Query(default=None, gt=0), offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500), query: str = Query(default="", max_length=500),
    metadata_only: bool = False) -> dict[str, object]:
    from .folder_resources import describe_folder, list_folder
    scope = await current_management_scope()
    if agent_id is not None:
        await _require_agent_scope(agent_id)
        from app.agent import get_agent_record
        if await get_agent_record(agent_id) is None:
            raise HTTPException(404, "Agent not found")
    actor = agent_id if agent_id is not None else HumanActor(scope.user_id)
    try:
        folder = await describe_folder(folder_id, actor)
        page: dict[str, object] = {"entries": [], "total": 0} if metadata_only else await list_folder(folder_id, actor, limit=limit, offset=offset, query=query)
        return {**page, "folder": folder}
    except FileNotFoundError as exc:
        raise HTTPException(404, "Folder unavailable") from exc


@router.post("/goal-folders/reconcile", status_code=202, response_model=GoalFolderReconciliationResult)
@authorize(privileges=Privileges.DOCUMENT_ADMIN)
async def launch_goal_folder_reconciliation(data: GoalFolderReconciliationRequest) -> GoalFolderReconciliationResult:
    from .goal_folders import enqueue_goal_folder_reconciliation
    identity = await enqueue_goal_folder_reconciliation(user_id=data.user_id, goal_id=data.goal_id)
    await get_db().commit()
    return GoalFolderReconciliationResult(job_id=identity)


@router.get("/{document_id}/summary", response_model=DocumentDetail)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_document_summary(document_id: UUID, agent_id: int | None = Query(default=None, gt=0)) -> DocumentDetail:
    from .summary_service import read_summary
    try:
        actor = await _document_request_actor(document_id, agent_id)
        return await read_summary(document_id, actor=actor)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/{document_id}/summary", dependencies=[Depends(require_editorial_client)], response_model=DocumentDetail)
@authorize(privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def edit_document_summary(document_id: UUID, data: DocumentUpdate,
    actor_agent_id: int | None = Query(default=None, gt=0)) -> DocumentDetail:
    from .summary_service import edit_summary
    try:
        actor = await _document_request_actor(document_id, actor_agent_id)
        return await edit_summary(document_id, data, actor=actor)
    except Exception as exc:
        raise _http_error(exc) from exc

async def _require_app_write(scope: AgentManagementScope) -> None:
    user = await get_user_record(scope.user_id)
    if user is None or not (
        await check_privilege(user, Privileges.DOCUMENT_EDIT, get_db())
        or await check_privilege(user, Privileges.DOCUMENT_ADMIN, get_db())
    ):
        raise service.DocumentPermissionError("Dataset edit privilege required.")

@router.get("/{document_id}/app-permissions", response_model=AppPermissions)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_app_permissions(document_id: UUID) -> AppPermissions:
    try:
        return await app_permissions(document_id, await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/{document_id}/app-permissions/{app_key}/{alias}", response_model=AppPermissions)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def update_app_permission(document_id: UUID, app_key: str, alias: str, data: AppGrantUpdate) -> AppPermissions:
    try:
        scope = await current_management_scope()
        if data.access == "write":
            await _require_app_write(scope)
        return await set_app_permission(document_id, app_key, alias, data, scope)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.post("/{document_id}/apps/{app_id}/datasets/{alias}", response_model=AppDatasetResult)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
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


def _http_error(exc: Exception) -> HTTPException:
    from .data.contracts import DatasetConflictError, DatasetNotFoundError, DatasetPermissionError, DatasetWriteLimitError
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, AppConsentRequired):
        return HTTPException(status_code=403, detail={"code": "permission_required", "message": str(exc)})
    if isinstance(exc, (AppWriteLimitError, DatasetWriteLimitError)):
        return HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "60"})
    if isinstance(exc, (service.DocumentNotFoundError, DatasetNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (service.DocumentPermissionError, DatasetPermissionError)):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, (service.DocumentConflictError, DatasetConflictError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (ValueError, service.DocumentError)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    reference = uuid4().hex[:12]
    logger.exception("Unexpected Memory API failure reference={}", reference)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected document error. Reference: {reference}.",
    )

@router.post(
    "",
    dependencies=[Depends(require_editorial_client)],
    response_model=DocumentPublic,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.DOCUMENT_EDIT)
async def create_managed_document(data: DocumentCreate) -> DocumentPublic:
    """Create a document owned by the caller or by one managed Agent."""

    try:
        scope = await _require_agent_scope(data.actor_agent_id) if data.actor_agent_id is not None else await current_management_scope()
        if data.owner_kind == "agent":
            await _require_agent_scope(data.owner_id)
            item = await document_service.create_document(
                owner_agent_id=data.owner_id,
                title=data.title,
                document_type=data.document_type,
                content="",
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
                Privileges.DOCUMENT_ASSIGN_ALL_USERS,
                get_db(),
            ):
                raise HTTPException(status_code=403, detail="User owner denied")
            item = await document_service.create_user_document(
                owner_user_id=data.owner_id,
                editor_agent_id=data.actor_agent_id,
                title=data.title,
                document_type=data.document_type,
                content="",
                folder=data.folder,
            )
        return service.item_to_public(
            item,
            await service.effective_access(item, HumanActor(scope.user_id) if data.owner_kind == "user" else data.owner_id),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


async def _item_request_actor(agent_id: int | None) -> tuple[int | HumanActor | None, bool]:
    if agent_id is not None:
        await _require_agent_scope(agent_id)
        return agent_id, False
    scope = await current_management_scope()
    return (None, True) if scope.is_global else (HumanActor(scope.user_id), False)

@router.get("/keywords", response_model=list[str])
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_document_keywords(agent_id: int = Query(gt=0)) -> list[str]:
    """List the keywords available on documents readable by one agent."""

    try:
        await _require_agent_scope(agent_id)
        return await service.list_document_keywords(agent_id)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.post("/library", response_model=DocumentLibraryPage)
@authorize(
    privileges=[
        Privileges.DOCUMENT_ACCESS,
        Privileges.DOCUMENT_EDIT,
        Privileges.DOCUMENT_ADMIN,
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

@router.post("/icons/resolve", response_model=dict[UUID, str | None])
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def resolve_document_icons(data: DocumentIconRequest) -> dict[UUID, str | None]:
    from . import document_icons

    return await document_icons.resolve(await current_management_scope(), data.document_ids)

@router.put("/{document_id}/icon", response_model=DocumentIconWrite)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN], assertion=ManagedDocumentAccessAssertion)
async def save_document_icon(document_id: UUID, data: DocumentIconWrite) -> DocumentIconWrite:
    from . import document_icons

    try:
        return await document_icons.save(await current_management_scope(), document_id, data)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/order", status_code=204)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def reorder_personal_documents(data: DocumentOrderMove) -> None:
    from .document_order import reorder

    try:
        await reorder(await current_management_scope(), data)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/order/sort", status_code=204)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def sort_personal_documents(data: DocumentOrderSort) -> None:
    from .document_order import sort_children

    try:
        await sort_children((await current_management_scope()).user_id, data)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.get("/tag-icons", response_model=list[DocumentTagIconPublic])
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_personal_tag_icons() -> list[DocumentTagIconPublic]:
    return await document_tags.list_icons((await current_management_scope()).user_id)

@router.post("/tag-icons", response_model=DocumentTagIconPublic)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def upload_personal_tag_icon(data: DocumentTagIconWrite) -> DocumentTagIconPublic:
    try:
        return await document_tags.upload_icon((await current_management_scope()).user_id, data)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/{document_id}/tags", status_code=204)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN], assertion=ManagedDocumentAccessAssertion)
async def move_personal_document(document_id: UUID, data: DocumentTagMove) -> None:
    try:
        await document_tags.move_document(await current_management_scope(), document_id, data.tag_id, at_root=data.at_root)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/{document_id}/parent", status_code=204)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN], assertion=ManagedDocumentAccessAssertion)
async def move_personal_subdocument(document_id: UUID, data: DocumentParentMove) -> None:
    from .document_nesting import move

    try:
        await move(await current_management_scope(), document_id, data.parent_document_id)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.get("/tags", response_model=DocumentTagCatalog)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_personal_document_tags() -> DocumentTagCatalog:
    user_id = (await current_management_scope()).user_id
    return DocumentTagCatalog(user_id=user_id, tags=await document_tags.list_tags(user_id))

@router.post("/tags", response_model=DocumentTagPublic)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def create_personal_document_tag(data: DocumentTagWrite) -> DocumentTagPublic:
    try:
        return await document_tags.write_tag((await current_management_scope()).user_id, data)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.get("/tags/{tag_id}/sharing", response_model=DocumentSharing)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_folder_sharing(tag_id: UUID) -> DocumentSharing:
    from . import folder_sharing
    try:
        return await folder_sharing.sharing(tag_id, await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/tags/{tag_id}/sharing", response_model=DocumentSharing)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def update_folder_sharing(tag_id: UUID, data: DocumentSharingLevelUpdate) -> DocumentSharing:
    from . import folder_sharing
    try:
        return await folder_sharing.update(tag_id, data, await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/tags/{tag_id}", response_model=DocumentTagPublic)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def update_personal_document_tag(tag_id: UUID, data: DocumentTagWrite) -> DocumentTagPublic:
    try:
        return await document_tags.write_tag((await current_management_scope()).user_id, data, tag_id)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.delete("/tags/{tag_id}", response_model=DocumentTagDeletionResult)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def delete_personal_document_tag(tag_id: UUID, confirmed: bool = False) -> DocumentTagDeletionResult:
    try:
        return await document_tags.remove_tag((await current_management_scope()).user_id, tag_id, confirmed=confirmed)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/{document_id}/tags/{tag_id}", status_code=204)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN], assertion=ManagedDocumentAccessAssertion)
async def add_personal_document_tag(document_id: UUID, tag_id: UUID) -> None:
    try:
        await document_tags.assign_tag(await current_management_scope(), document_id, tag_id)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.delete("/{document_id}/tags/{tag_id}", status_code=204)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN], assertion=ManagedDocumentAccessAssertion)
async def remove_personal_document_tag(document_id: UUID, tag_id: UUID) -> None:
    try:
        await document_tags.assign_tag(await current_management_scope(), document_id, tag_id, remove=True)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.get("/folders", response_model=list[str] | list[DocumentFolderOption])
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
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

@router.get("/owner-options", response_model=DocumentOwnerOptions)
@authorize(privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_document_owner_options(
    search: str = Query(default="", max_length=200),
) -> DocumentOwnerOptions:
    """List Agents and only the Users the caller may select as owner."""

    try:
        scope = await current_management_scope()
        current_user = await get_current_user()
        if current_user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        include_all_users = await check_privilege(
            current_user,
            Privileges.DOCUMENT_ASSIGN_ALL_USERS,
            get_db(),
        )
        return await service.list_document_owner_options(
            current_user_id=current_user.id,
            current_user=current_user,
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
    "/{document_id}/content-revisions",
    response_model=DocumentContentRevisionPage,
)
@authorize(
    privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN],
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
    "/{document_id}/content-revisions/{revision}",
    response_model=DocumentContentRevisionDetail,
)
@authorize(
    privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN],
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
    "/{document_id}/content-revisions/{revision}/diff",
    response_model=DocumentContentDiff,
)
@authorize(
    privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN],
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
    "/{document_id}/content-revisions/{revision}/restore",
    response_model=DocumentPublic,
)
@authorize(
    privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def restore_managed_document_content_revision(
    document_id: UUID,
    revision: int,
    data: DocumentContentRestore,
) -> DocumentPublic:
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

@router.post("/{document_id}/import-image", response_model=DocumentAttachmentPublic)
@authorize(privileges=Privileges.DOCUMENT_EDIT)
async def import_document_image(document_id: UUID, data: DocumentLinkRequest, actor_agent_id: int | None = Query(default=None, gt=0)) -> DocumentAttachmentPublic:
    from .document_image_import import import_document_image as import_image
    try:
        actor = await _document_request_actor(document_id, actor_agent_id)
        return await import_image(document_id, data.url, actor=actor)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.post("/link-card/thumbnail", response_class=Response)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_link_card_thumbnail(data: DocumentLinkRequest, agent_id: int | None = Query(default=None, gt=0)) -> Response:
    from .document_links import link_thumbnail
    try:
        actor, _ = await _item_request_actor(agent_id)
        if actor is None:
            actor = HumanActor((await current_management_scope()).user_id)
        content = await link_thumbnail(data.url, actor=actor)
        return Response(content, status_code=200 if content else 204, media_type="image/webp",
                        headers={"Cache-Control": "no-store"})
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{document_id}/link-card", response_model=DocumentLinkCard)
@authorize(privileges=Privileges.DOCUMENT_EDIT)
async def create_document_link_card(document_id: UUID, data: DocumentLinkRequest, actor_agent_id: int | None = Query(default=None, gt=0)) -> DocumentLinkCard:
    from .document_links import create_link_card
    try:
        actor = await _document_request_actor(document_id, actor_agent_id)
        return await create_link_card(document_id, data.url, actor_agent_id=actor)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.post("/{document_id}/export-bundle")
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def export_document_bundle(document_id: UUID, data: DocumentPdfExport, agent_id: int | None = Query(default=None, gt=0)) -> Response:
    try:
        actor = await _document_request_actor(document_id, agent_id)
        content = await document_export.export_document_bundle(document_id, data.html, actor_agent_id=actor)
        return Response(content, media_type="application/zip", headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="document.zip"'})
    except Exception as exc:
        raise _http_error(exc) from exc

@router.post("/{document_id}/export-pdf")
@authorize(
    privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN],
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

@router.post("/{document_id}/thumbnail", response_class=Response)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
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
        return Response(content, media_type="image/webp", headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        })
    except Exception as exc:
        raise _http_error(exc) from exc

@router.get("/{document_id}/dataset-attachments", response_model=DocumentDatasetAttachments)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_document_datasets(document_id: UUID, agent_id: int | None = Query(default=None, gt=0)) -> DocumentDatasetAttachments:
    try:
        actor = await _document_request_actor(document_id, agent_id)
        items, version = await dataset_attachments.list_references(document_id, actor, dataset_actor=await current_management_scope())
        return DocumentDatasetAttachments(items=[DocumentDatasetAttachment(uri=item.uri, title=item.title, available=item.available) for item in items], lock_version=version)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.get("/{document_id}/internal-attachments")
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_internal_attachments(document_id: UUID, resource_agent_id: int = Query(gt=0),
    agent_id: int | None = Query(default=None, gt=0)) -> dict[str, Any]:
    try:
        await _require_agent_scope(resource_agent_id)
        actor = await _document_request_actor(document_id, agent_id)
        return await internal_attachments.references(document_id, actor, resource_agent_id, scope=await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/{document_id}/internal-attachments")
@authorize(privileges=Privileges.DOCUMENT_EDIT)
async def change_internal_attachments(document_id: UUID, data: DocumentInternalAttachmentWrite,
    actor_agent_id: int | None = Query(default=None, gt=0)) -> dict[str, Any]:
    try:
        await _require_agent_scope(data.resource_agent_id)
        actor = await _document_request_actor(document_id, actor_agent_id)
        return await internal_attachments.change_references(document_id, actor, data.resource_agent_id,
            uris=data.uris, expected_lock_version=data.expected_lock_version, remove=data.remove, scope=await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc

@router.get("/{document_id}/process-attachments")
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_document_processes(document_id: UUID, agent_id: int | None = Query(default=None, gt=0)) -> dict[str, Any]:
    try:
        actor = await _document_request_actor(document_id, agent_id)
        return await process_references.references(document_id, actor,
            agent_id if agent_id is not None else await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/{document_id}/process-attachments")
@authorize(privileges=Privileges.DOCUMENT_EDIT)
async def attach_document_process(document_id: UUID, data: DocumentProcessAttachmentWrite,
    actor_agent_id: int | None = Query(default=None, gt=0)) -> dict[str, Any]:
    try:
        actor = await _document_request_actor(document_id, actor_agent_id)
        return await process_references.change_reference(document_id, actor,
            actor_agent_id if actor_agent_id is not None else await current_management_scope(),
            uri=data.uri, expected_lock_version=data.expected_lock_version, remove=data.remove)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/{document_id}/dataset-attachments", response_model=DocumentDatasetAttachments)
@authorize(privileges=Privileges.DOCUMENT_EDIT)
async def attach_document_dataset(document_id: UUID, data: DocumentDatasetAttachmentWrite,
    actor_agent_id: int | None = Query(default=None, gt=0)) -> DocumentDatasetAttachments:
    try:
        actor = await _document_request_actor(document_id, actor_agent_id)
        items, version = await dataset_attachments.change_reference(document_id, data.dataset_id, actor,
            dataset_actor=await current_management_scope(), expected_lock_version=data.expected_lock_version)
        return DocumentDatasetAttachments(items=[DocumentDatasetAttachment(uri=item.uri, title=item.title, available=item.available) for item in items], lock_version=version)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.delete("/{document_id}/dataset-attachments/{dataset_id}", response_model=DocumentDatasetAttachments)
@authorize(privileges=Privileges.DOCUMENT_EDIT)
async def detach_document_dataset(document_id: UUID, dataset_id: UUID, expected_lock_version: int = Query(ge=1),
    actor_agent_id: int | None = Query(default=None, gt=0)) -> DocumentDatasetAttachments:
    try:
        actor = await _document_request_actor(document_id, actor_agent_id)
        items, version = await dataset_attachments.change_reference(document_id, dataset_id, actor,
            dataset_actor=await current_management_scope(), expected_lock_version=expected_lock_version, remove=True)
        return DocumentDatasetAttachments(items=[DocumentDatasetAttachment(uri=item.uri, title=item.title, available=item.available) for item in items], lock_version=version)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.get("/{document_id}", response_model=ManagedDocumentDetail | DocumentResourceRedirect)
@authorize(
    privileges=[
        Privileges.DOCUMENT_ACCESS,
        Privileges.DOCUMENT_EDIT,
        Privileges.DOCUMENT_ADMIN,
    ],
    assertion=ManagedDocumentAccessAssertion,
)
async def read_managed_document(document_id: UUID, agent_id: Annotated[int | None, Query(gt=0)] = None) -> ManagedDocumentDetail | DocumentResourceRedirect:
    try:
        scope = await current_management_scope()
        if agent_id is not None:
            await _require_agent_scope(agent_id)
            actor: int | HumanActor = agent_id
        else:
            actor = await document_sharing.document_actor(document_id, scope)
        item, content, access, content_type, media_type = await service.get_item(
            document_id, agent_id=actor, include_revisions=False,
        )
        if item.document_type == "dataset":
            return DocumentResourceRedirect(resource_uri=f"data://{item.id}")
        if item.document_type not in {"text", "html", "data"}:
            raise service.DocumentNotFoundError("HTML Document not found")
        return ManagedDocumentDetail(
            item=await service.item_to_detail(item, content, access, content_type=content_type, media_type=media_type),
            agent_id=actor if isinstance(actor, int) else None,
        )
    except Exception as exc:
        raise _http_error(exc) from exc

@router.delete("/{document_id}", response_model=DocumentDeletionResult)
@authorize(privileges=Privileges.DOCUMENT_EDIT)
async def delete_managed_document(
    document_id: UUID,
    actor_agent_id: int | None = Query(default=None, gt=0),
) -> DocumentDeletionResult:
    try:
        actor, administrative = await _item_request_actor(actor_agent_id)
        return await service.delete_document(
            document_id, actor_agent_id=actor, administrative=administrative,
        )
    except Exception as exc:
        raise _http_error(exc) from exc

@router.patch("/{document_id}", response_model=DocumentPublic, dependencies=[Depends(require_editorial_client)])
@authorize(privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def update_human_document(document_id: UUID, data: DocumentUpdate, actor_agent_id: Annotated[int | None, Query(gt=0)] = None) -> DocumentPublic:
    try:
        scope = await current_management_scope()
        if actor_agent_id is not None:
            await _require_agent_scope(actor_agent_id)
            actor: int | HumanActor = actor_agent_id
        else:
            actor = HumanActor(scope.user_id)
        item = await service.update_item(document_id, data, actor_agent_id=actor, include_revisions=False)
        return service.item_to_public(item, await service.effective_access(item, actor))
    except Exception as exc:
        raise _http_error(exc) from exc

@router.get("/{document_id}/sharing", response_model=DocumentSharing)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_document_sharing(document_id: UUID) -> DocumentSharing:
    try:
        return await document_sharing.sharing(document_id, await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/{document_id}/sharing", response_model=DocumentSharing)
@authorize(privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def update_document_sharing(document_id: UUID, data: DocumentSharingUpdate) -> DocumentSharing:
    try:
        return await document_sharing.update_sharing(document_id, data, await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put("/{document_id}/sharing-level", response_model=DocumentSharing)
@authorize(privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def update_document_sharing_level(document_id: UUID, data: DocumentSharingLevelUpdate) -> DocumentSharing:
    try:
        return await document_sharing.update_level(document_id, data, await current_management_scope())
    except Exception as exc:
        raise _http_error(exc) from exc

@router.patch("/{document_id}/folder", response_model=DocumentPublic)
@authorize(
    privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def move_managed_document(
    document_id: UUID,
    data: DocumentFolderUpdate,
) -> DocumentPublic:
    """Move one writable managed document to a logical folder."""

    try:
        scope = await current_management_scope()
        actor = await document_sharing.document_actor(document_id, scope, write=True)
        item, _ = await service.get_item_metadata(document_id, agent_id=actor)
        metadata = dict(item.metadata_)
        if data.folder:
            metadata["document_path"] = data.folder
        else:
            metadata.pop("document_path", None)
        updated = await service.update_item(
            document_id,
            DocumentUpdate(
                expected_revision=data.expected_revision,
                expected_lock_version=data.expected_lock_version,
                metadata=metadata,
            ),
            actor_agent_id=actor,
            include_revisions=False,
        )
        return service.item_to_public(
            updated,
            await service.effective_access(updated, actor),
        )
    except Exception as exc:
        raise _http_error(exc) from exc

@router.patch("/{document_id}/owner", response_model=DocumentPublic)
@authorize(
    privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def change_document_owner(
    document_id: UUID,
    data: DocumentOwnerUpdate,
) -> DocumentPublic:
    """Transfer one writable document to an Agent or an authorized User."""

    try:
        scope = await current_management_scope()
        actor = await document_sharing.document_actor(document_id, scope, write=True)
        item, _ = await service.get_item_metadata(document_id, agent_id=actor)
        current_user = await get_user_record(scope.user_id)
        owns_document = (
            scope.allows(item.owner_agent_id)
            or item.owner_user_id == scope.user_id
        )
        if not owns_document and not await check_privilege(
            current_user,
            Privileges.DOCUMENT_ADMIN,
            get_db(),
        ):
            raise service.DocumentPermissionError(
                "Only the document owner can transfer ownership."
            )
        if data.kind == "agent" and not scope.allows(data.id):
            raise HTTPException(status_code=404, detail="Agent not found")
        if data.kind == "user" and data.id != scope.user_id:
            if not await check_privilege(
                current_user,
                Privileges.DOCUMENT_ASSIGN_ALL_USERS,
                get_db(),
            ):
                raise HTTPException(status_code=403, detail="User owner denied")
        updated = await service.transfer_document_owner(
            document_id,
            data,
            actor_agent_id=actor,
            include_revisions=False,
        )
        access = await service.effective_access(updated, actor)
        return service.item_to_public(updated, access)
    except Exception as exc:
        raise _http_error(exc) from exc

async def _assert_can_manage_document_grants(
    document_id: UUID, *, target_agent_id: int | None = None,
) -> tuple[AgentManagementScope, int | HumanActor]:
    scope = await current_management_scope()
    item = await service.document_record(document_id, revisions=False)
    if item is None or not await document_sharing.can_manage(item, scope):
        raise service.DocumentPermissionError("Only the document owner can manage sharing")
    if target_agent_id is not None and not scope.allows(target_agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return scope, await document_sharing.document_actor(document_id, scope, write=True)

@router.patch(
    "/{document_id}/global-access",
    response_model=DocumentPublic,
)
@authorize(
    privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def set_managed_document_global_access(
    document_id: UUID,
    data: DocumentGlobalAccessUpdate,
) -> DocumentPublic:
    """Set the access inherited by every current and future Agent."""

    try:
        _scope, actor_agent_id = await _assert_can_manage_document_grants(document_id)
        updated = await service.set_document_global_access(
            document_id,
            data,
            actor_agent_id=actor_agent_id if isinstance(actor_agent_id, int) else None,
            include_revisions=False,
        )
        return service.item_to_public(
            updated,
            await service.effective_access(updated, actor_agent_id),
        )
    except Exception as exc:
        raise _http_error(exc) from exc

@router.put(
    "/{document_id}/collaborators/{agent_id}",
    response_model=DocumentPublic,
)
@authorize(
    privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def set_managed_document_grant(
    document_id: UUID,
    agent_id: int,
    data: DocumentGrantUpdate,
) -> DocumentPublic:
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
            include_revisions=False,
        )
        return service.item_to_public(
            updated,
            await service.effective_access(updated, actor_agent_id),
        )
    except Exception as exc:
        raise _http_error(exc) from exc

@router.delete(
    "/{document_id}/collaborators/{agent_id}",
    response_model=DocumentPublic,
)
@authorize(
    privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN],
    assertion=ManagedDocumentAccessAssertion,
)
async def remove_managed_document_grant(
    document_id: UUID,
    agent_id: int,
    expected_lock_version: int | None = Query(default=None, ge=1),
) -> DocumentPublic:
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
            include_revisions=False,
        )
        return service.item_to_public(
            updated,
            await service.effective_access(updated, actor_agent_id),
        )
    except Exception as exc:
        raise _http_error(exc) from exc

@router.get(
    "/{document_id}/attachments",
    response_model=list[DocumentAttachmentPublic],
)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
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
    "/{document_id}/attachments",
    response_model=DocumentAttachmentPublic,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.DOCUMENT_EDIT)
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
    "/{document_id}/attachments/{attachment_id}/thumbnail",
    response_class=Response,
)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def read_document_attachment_thumbnail(
    document_id: UUID,
    attachment_id: UUID,
    agent_id: int | None = Query(default=None, gt=0),
    cached_only: bool = False,
) -> Response:
    """Return a small cached preview without transferring the full attachment."""

    try:
        actor = await _document_request_actor(document_id, agent_id)
        content = await document_thumbnail_service.read_or_schedule_document_attachment_thumbnail(
            document_id,
            attachment_id,
            actor_agent_id=actor,
            cached_only=cached_only,
        )
        if content is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail pending")
        return Response(
            content=content,
            media_type="image/webp",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as exc:
        raise _http_error(exc) from exc

@router.patch("/{document_id}/attachments/{attachment_id}", response_model=DocumentAttachmentPublic)
@authorize(privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def rename_document_attachment(document_id: UUID, attachment_id: UUID, data: FileRename,
    actor_agent_id: int | None = Query(default=None, gt=0)) -> DocumentAttachmentPublic:
    try:
        actor = await _document_request_actor(document_id, actor_agent_id)
        return await document_attachment_service.rename_document_attachment(
            document_id, attachment_id, actor_agent_id=actor, name=data.name)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.get(
    "/{document_id}/attachments/{attachment_id}/info",
    response_model=DocumentAttachmentPublic,
)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
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
    "/{document_id}/attachments/{attachment_id}",
    response_class=FileResponse,
)
@authorize(privileges=[Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
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
                **source_code_response_headers(attachment.name, attachment.media_type),
            },
        )
    except Exception as exc:
        raise _http_error(exc) from exc

@router.delete(
    "/{document_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@authorize(privileges=Privileges.DOCUMENT_EDIT)
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
    "/{document_id}/grants/{agent_id}",
    response_model=DocumentPublic,
)
@authorize(privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def set_document_grant(
    document_id: UUID,
    agent_id: int,
    data: DocumentGrantUpdate,
    owner_agent_id: int = Query(gt=0),
) -> DocumentPublic:
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
        item, access = await service.get_item_metadata(
            document_id,
            agent_id=owner_agent_id,
        )
        return service.item_to_public(item, access)
    except Exception as exc:
        raise _http_error(exc) from exc

@router.delete(
    "/{document_id}/grants/{agent_id}",
    response_model=DocumentPublic,
)
@authorize(privileges=[Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN])
async def remove_document_grant(
    document_id: UUID,
    agent_id: int,
    owner_agent_id: int = Query(gt=0),
) -> DocumentPublic:
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
        item, access = await service.get_item_metadata(
            document_id,
            agent_id=owner_agent_id,
        )
        return service.item_to_public(item, access)
    except Exception as exc:
        raise _http_error(exc) from exc
