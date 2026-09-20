"""Dataset capability checks always use the current viewer, never the app author."""

from typing import Literal
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import select

from app.agent import AgentManagementScope
from core.database import get_db

from . import document_sharing, service
from .document_apps import (
    AppDatasetRequest, AppDatasetResult, AppGrantPublic, AppGrantUpdate,
    AppPermissions, DocumentApp, document_apps,
)
from .document_app_security import AppConsentRequired, consume_write_budget, encode_app_data
from .models import DocumentAppGrant, MemoryItem
from .schemas import MemoryItemUpdate, MemoryPayload

_json: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


async def _applications(document_id: UUID, scope: AgentManagementScope) -> tuple[MemoryItem, list[DocumentApp]]:
    db = get_db()
    await db.scalar(select(MemoryItem.id).where(MemoryItem.id == document_id).with_for_update())
    actor = await document_sharing.document_actor(document_id, scope)
    document, source, *_ = await service.get_item(document_id, agent_id=actor)
    if document.document_type != "html" or document.content_profile != "document":
        raise service.MemoryPermissionError("This document cannot run applications.")
    return document, document_apps(source.decode())


async def _grant(document_id: UUID, app_key: str, alias: str, user_id: int) -> DocumentAppGrant | None:
    return await get_db().scalar(select(DocumentAppGrant).where(
        DocumentAppGrant.document_id == document_id, DocumentAppGrant.app_key == app_key,
        DocumentAppGrant.alias == alias, DocumentAppGrant.user_id == user_id,
    ).execution_options(populate_existing=True))


async def app_permissions(document_id: UUID, scope: AgentManagementScope) -> AppPermissions:
    document, apps = await _applications(document_id, scope)
    grants: list[AppGrantPublic] = []
    for app in apps:
        for alias, binding in app.datasets.items():
            grant = await _grant(document_id, app.id, alias, scope.user_id)
            access: Literal["read", "write"] | None = None
            if grant and grant.document_revision == document.revision and grant.dataset_id == binding.document_id:
                if grant.access in ("read", "write"):
                    access = "write" if grant.access == "write" else "read"
            title = None
            try:
                await document_sharing.document_actor(binding.document_id, scope)
                dataset = await get_db().get(MemoryItem, binding.document_id)
                title = dataset.title if dataset else None
            except (service.MemoryPermissionError, service.MemoryNotFoundError):
                pass
            grants.append(AppGrantPublic(app_key=app.id, app_title=app.title, alias=alias,
                dataset_id=binding.document_id, dataset_title=title, requested_access=binding.access, access=access))
    return AppPermissions(document_revision=document.revision, grants=grants)


async def set_app_permission(
    document_id: UUID, app_key: str, alias: str, data: AppGrantUpdate, scope: AgentManagementScope,
) -> AppPermissions:
    db = get_db()
    document, apps = await _applications(document_id, scope)
    if document.revision != data.document_revision:
        raise service.MemoryConflictError("The application changed. Review its permissions again.")
    app = next((entry for entry in apps if entry.id == app_key), None)
    binding = app.datasets.get(alias) if app else None
    if binding is None or (data.access == "write" and binding.access != "write"):
        raise service.MemoryPermissionError("Dataset operation is not declared by this application.")
    if data.access is not None:
        await document_sharing.document_actor(binding.document_id, scope, write=data.access == "write")
        dataset = await db.get(MemoryItem, binding.document_id)
        if dataset is None or dataset.document_type != "dataset":
            raise ValueError("Application bindings must target Dataset documents.")
    grant = await _grant(document_id, app_key, alias, scope.user_id)
    if grant is None:
        if data.access is None:
            return await app_permissions(document_id, scope)
        grant = DocumentAppGrant(document_id=document_id, dataset_id=binding.document_id,
            app_key=app_key, alias=alias, user_id=scope.user_id)
        db.add(grant)
    grant.dataset_id, grant.document_revision, grant.access = binding.document_id, document.revision, data.access
    await db.commit()
    return await app_permissions(document_id, scope)


async def app_dataset(
    document_id: UUID, app_id: str, alias: str, data: AppDatasetRequest,
    scope: AgentManagementScope,
) -> AppDatasetResult:
    db = get_db()
    # The same lock serializes consent changes, revocations and application calls.
    document, apps = await _applications(document_id, scope)
    if document.revision != data.document_revision:
        raise service.MemoryConflictError("The application changed. Reopen it before accessing data.")
    app = next((entry for entry in apps if entry.id == app_id), None)
    binding = app.datasets.get(alias) if app else None
    if binding is None or (data.operation != "read" and binding.access != "write"):
        raise service.MemoryPermissionError("Dataset operation is not declared by this application.")
    identity = binding.document_id
    grant = await _grant(document_id, app_id, alias, scope.user_id)
    if (grant is None or grant.dataset_id != identity or grant.document_revision != document.revision
            or grant.access is None or (data.operation != "read" and grant.access != "write")):
        raise AppConsentRequired("Approve this application's Dataset access in document permissions.")
    dataset_actor = await document_sharing.document_actor(identity, scope, write=data.operation != "read")
    locked = await db.scalar(select(MemoryItem.id).where(
        MemoryItem.id == identity, MemoryItem.document_type == "dataset",
    ).with_for_update())
    if locked is None:
        raise ValueError("Application bindings must target Dataset documents.")
    dataset, content, *_ = await service.get_item(identity, agent_id=dataset_actor)
    if dataset.document_type != "dataset":
        raise ValueError("Application bindings must target Dataset documents.")
    value = _json.validate_json(content)
    if data.operation != "read":
        encode_app_data(data.value)
        if dataset.revision != data.expected_revision:
            raise service.MemoryConflictError("The Dataset changed. Read its current revision before submitting again.")
        if data.operation == "append":
            if not isinstance(value, list):
                raise ValueError("Append requires a Dataset whose root is a JSON array.")
            value.append(data.value)
        else:
            value = data.value
        encoded = encode_app_data(value)
        await consume_write_budget(scope.user_id, identity, len(encoded.encode("utf-8")))
        dataset = await service.update_item(identity, MemoryItemUpdate(
            expected_revision=data.expected_revision,
            payload=MemoryPayload(text=encoded),
        ), actor_agent_id=dataset_actor)
    return AppDatasetResult(revision=dataset.revision, data=value)
