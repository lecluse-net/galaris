"""Human API for JSON Dataset resources."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.agent import current_management_scope
from app.memory import MemoryNotFoundError, MemoryPermissionError, MemoryConflictError
from app.share import SharingUpdate as DocumentSharingLevelUpdate
from core.authorize import authorize
from core.database import get_db
from core.storage import FileRename

from . import service, organization, ownership, sharing as sharing_service, usage

router = APIRouter(prefix="/datasets", tags=["datasets"])
READ = ["DATASET_READ", "DATASET_EDIT", "DATASET_ADMIN"]
EDIT = ["DATASET_EDIT", "DATASET_ADMIN"]


@contextmanager
def errors() -> Generator[None]:
    try:
        yield
    except (FileNotFoundError, MemoryNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, MemoryPermissionError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except (service.DatasetConflictError, MemoryConflictError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except service.DatasetWriteLimitError as exc:
        raise HTTPException(429, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateDataset(Request):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(default="[]", max_length=2_000_000)
    owner_agent_id: int | None = Field(default=None, gt=0)


class WriteDataset(Request):
    content: str = Field(max_length=2_000_000)
    expected_revision: int = Field(ge=1)
    expected_lock_version: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)


class RevisionRequest(Request):
    expected_revision: int = Field(ge=1)


class UpdateMetadata(Request):
    expected_lock_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    keywords: list[str] | None = Field(default=None, max_length=100)
    global_access: Literal[0, 1, 2] | None = None
    group_access: Literal[0, 1, 2] | None = None
    read_only: bool | None = None


class Grant(Request):
    expected_lock_version: int = Field(ge=1)
    kind: Literal["agent", "user", "team"]
    principal: int = Field(gt=0)
    can_write: bool | None


class OwnerUpdate(Request):
    expected_lock_version: int = Field(ge=1)
    kind: Literal["agent", "user"]
    principal: int = Field(gt=0)


class TagCreate(Request):
    name: str = Field(min_length=1, max_length=100)
    parent_id: UUID | None = None


class Classification(Request):
    tags: list[UUID] = Field(max_length=100)
    icon: str | None = Field(default=None, max_length=1000)
    position: int = 0


class Attach(Request):
    uri: str = Field(max_length=2000)
    agent_id: int = Field(gt=0)
    name: str | None = Field(default=None, max_length=512)


@router.get("")
@authorize(privileges=READ)
async def list_datasets(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500), q: str = Query("", max_length=500), tag_id: UUID | None = None, owner_agent_id: int | None = Query(None, gt=0)) -> dict[str, Any]:
    with errors():
        return await service.list_datasets(await current_management_scope(), page=page, page_size=page_size, query=q, tag_id=tag_id, owner_agent_id=owner_agent_id)


@router.post("")
@authorize(privileges=EDIT)
async def create_dataset(data: CreateDataset) -> dict[str, Any]:
    with errors():
        actor = await current_management_scope()
        dataset = await service.create(actor, **data.model_dump())
        await get_db().commit()
        return await service.describe(dataset, actor)


@router.get("/tags")
@authorize(privileges=READ)
async def list_tags() -> list[dict[str, Any]]:
    with errors():
        return await organization.tags(await current_management_scope())


@router.post("/tags")
@authorize(privileges=EDIT)
async def create_tag(data: TagCreate) -> dict[str, Any]:
    with errors():
        item = await organization.save_tag(await current_management_scope(), **data.model_dump())
        await get_db().commit()
        return {"id": str(item.id), "name": item.name, "parent_id": str(item.parent_id) if item.parent_id else None}


@router.get("/{identity}")
@authorize(privileges=READ)
async def read_dataset(identity: UUID) -> dict[str, Any]:
    with errors():
        actor = await current_management_scope()
        return await service.describe(await service.record(identity, actor), actor)


@router.put("/{identity}/content")
@authorize(privileges=EDIT)
async def write_dataset(identity: UUID, data: WriteDataset) -> dict[str, Any]:
    with errors():
        actor = await current_management_scope()
        current = await service.record(identity, actor, write=True, lock=True)
        if data.expected_lock_version is not None and current.lock_version != data.expected_lock_version:
            raise service.DatasetConflictError("Dataset metadata changed; reload before saving")
        dataset = await service.replace(identity, actor, content=data.content, expected_revision=data.expected_revision, consume_budget=True)
        if data.title is not None and data.title != dataset.title:
            dataset = await service.metadata(identity, actor, expected_lock_version=dataset.lock_version, values={"title": data.title})
        await get_db().commit()
        return await service.describe(dataset, actor)


@router.patch("/{identity}")
@authorize(privileges=EDIT)
async def update_dataset(identity: UUID, data: UpdateMetadata) -> dict[str, Any]:
    with errors():
        actor = await current_management_scope()
        dataset = await service.metadata(identity, actor, expected_lock_version=data.expected_lock_version,
            values=data.model_dump(exclude_unset=True, exclude={"expected_lock_version"}))
        await get_db().commit()
        return await service.describe(dataset, actor)


@router.delete("/{identity}")
@authorize(privileges=EDIT)
async def delete_dataset(identity: UUID, expected_lock_version: int = Query(ge=1)) -> None:
    with errors():
        await service.remove(identity, await current_management_scope(), expected_lock_version=expected_lock_version)
        await get_db().commit()


@router.get("/{identity}/revisions")
@authorize(privileges=READ)
async def read_history(identity: UUID, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    with errors():
        return await service.history(identity, await current_management_scope(), page=page, page_size=page_size)


@router.get("/{identity}/revisions/{number}")
@authorize(privileges=READ)
async def read_revision(identity: UUID, number: int) -> dict[str, Any]:
    with errors():
        revision = await service.revision(identity, await current_management_scope(), number)
        return {"revision": number, "content": revision.content}


@router.post("/{identity}/revisions/{number}/restore")
@authorize(privileges=EDIT)
async def restore_revision(identity: UUID, number: int, data: RevisionRequest) -> dict[str, Any]:
    with errors():
        actor = await current_management_scope()
        dataset = await service.restore(identity, actor, number=number, expected_revision=data.expected_revision)
        await get_db().commit()
        return await service.describe(dataset, actor)


@router.get("/{identity}/sharing")
@authorize(privileges=READ)
async def sharing(identity: UUID) -> dict[str, Any]:
    with errors():
        return (await sharing_service.read(identity, await current_management_scope())).model_dump(mode="json")


@router.get("/{identity}/owner", response_model=ownership.OwnerOptions)
@authorize(privileges=READ)
async def owner_options(identity: UUID) -> ownership.OwnerOptions:
    with errors():
        return await ownership.options(identity, await current_management_scope())


@router.patch("/{identity}/owner")
@authorize(privileges=EDIT)
async def transfer_owner(identity: UUID, data: OwnerUpdate) -> dict[str, Any]:
    with errors():
        actor = await current_management_scope()
        dataset = await ownership.transfer(identity, actor, **data.model_dump())
        await get_db().commit()
        return await service.describe(dataset, actor)


@router.put("/{identity}/sharing-level")
@authorize(privileges=EDIT)
async def sharing_level(identity: UUID, data: DocumentSharingLevelUpdate) -> dict[str, Any]:
    with errors():
        result = await sharing_service.update(identity, await current_management_scope(), data)
        await get_db().commit()
        return result.model_dump(mode="json")


@router.get("/{identity}/usages")
@authorize(privileges=READ)
async def usages(identity: UUID, kind: Literal["documents", "processes", "agents"] = "documents",
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    with errors():
        actor = await current_management_scope()
        return await usage.list_usages(identity, actor, kind=kind, page=page, page_size=page_size)


@router.put("/{identity}/sharing")
@authorize(privileges=EDIT)
async def set_grant(identity: UUID, data: Grant) -> dict[str, Any]:
    with errors():
        actor = await current_management_scope()
        await service.set_grant(identity, actor, **data.model_dump())
        await get_db().commit()
        return await service.sharing(identity, actor)


@router.get("/{identity}/attachments")
@authorize(privileges=READ)
async def attachments(identity: UUID) -> list[dict[str, Any]]:
    from .attachments import list_attachments
    with errors():
        return await list_attachments(identity, await current_management_scope())


@router.post("/{identity}/attachments")
@authorize(privileges=EDIT)
async def attach(identity: UUID, data: Attach) -> dict[str, Any]:
    from .attachments import attach_existing
    with errors():
        item = await attach_existing(identity, await current_management_scope(), **data.model_dump())
        await get_db().commit()
        return {"id": str(item.id), "uri": item.uri, "name": item.name}


@router.patch("/{identity}/attachments/{attachment_id}")
@authorize(privileges=EDIT)
async def rename_dataset_attachment(identity: UUID, attachment_id: UUID, data: FileRename) -> None:
    from .attachments import rename_attachment
    with errors():
        await rename_attachment(identity, attachment_id, await current_management_scope(), data.name)


@router.put("/{identity}/classification")
@authorize(privileges=READ)
async def classify(identity: UUID, data: Classification) -> None:
    with errors():
        await organization.classify(identity, await current_management_scope(), **data.model_dump())
        await get_db().commit()
