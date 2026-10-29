"""Explicit adapters for historical Memory Dataset entry points."""

from app.share import ShareGrant

from contextlib import contextmanager
from collections.abc import Generator
import hashlib
from typing import Any, Literal, cast
from uuid import UUID
from pathlib import Path

from sqlalchemy import delete, select
from core.database import get_db
from core.user import HumanActor
from core.storage import StoredFile, FileAlias, registered_file_names
from app.document import DocumentConflictError, DocumentNotFoundError, DocumentPermissionError
from app.agent import AgentManagementScope

from . import service
from .access import access
from .migration import adopt_legacy
from .models import Dataset, DatasetAttachment


@contextmanager
def legacy_errors() -> Generator[None]:
    try:
        yield
    except service.DatasetConflictError as exc:
        raise DocumentConflictError(str(exc)) from exc
    except service.DatasetNotFoundError as exc:
        raise DocumentNotFoundError(str(exc)) from exc
    except service.DatasetPermissionError as exc:
        raise DocumentPermissionError(str(exc)) from exc


class LegacyDatasetAdapter:
    async def contains(self, identity: UUID) -> bool:
        return await get_db().scalar(select(Dataset.id).where(Dataset.id == identity)) is not None

    async def adopt(self, identity: UUID) -> None:
        await adopt_legacy(identity)

    async def read(self, identity: UUID, actor: int | HumanActor, revision: int | None = None) -> dict[str, Any]:
        with legacy_errors():
            dataset = await service.record(identity, actor)
            state = await service.describe(dataset, actor)
            permissions = await access(dataset, actor)
            state.update(can_read=permissions.can_read, can_write=permissions.can_write)
            if revision is not None:
                entry = await service.revision(identity, actor, revision)
                state.update(content=entry.content, revision=entry.revision, revision_detail={
                    "revision": entry.revision, "task_id": None, "content_hash": hashlib.sha256((entry.content or "").encode()).hexdigest(),
                    "media_type": "application/json", "content_profile_version": None, "author_agent_id": entry.author_agent_id,
                    "created_at": entry.created_at})
            return state

    async def update(self, identity: UUID, actor: int | HumanActor, values: dict[str, Any]) -> None:
        with legacy_errors():
            dataset = await service.record(identity, actor, write=True, lock=True)
            expected = values.pop("expected_revision", None)
            lock = values.pop("expected_lock_version", None)
            if lock is not None and lock != dataset.lock_version:
                raise service.DatasetConflictError("Dataset metadata changed; reload before editing")
            if values.get("content_type", "text") != "text" or values.get("media_type", "application/json") != "application/json":
                raise service.DatasetConflictError("A Dataset remains JSON; its type is immutable")
            values.pop("content_type", None)
            values.pop("media_type", None)
            payload = values.pop("payload", None)
            if payload is not None:
                from app.document import dataset_budget_reserved
                if payload.get("text") is None or payload.get("base64") is not None:
                    raise ValueError("A Dataset requires UTF-8 JSON text")
                await service.replace(identity, actor, content=payload["text"], expected_revision=expected,
                    consume_budget=not dataset_budget_reserved.get())
            if values:
                if "metadata" in values:
                    values["metadata"] = {key: value for key, value in values["metadata"].items() if key not in {"dataset_migrated", "dataset_uri"}}
                values.pop("visibility", None)
                if values:
                    await service.metadata(identity, actor, expected_lock_version=dataset.lock_version, values=values)
            if "document_attachments" in dataset.metadata_ or "retained_document_attachments" in dataset.metadata_:
                entries: list[dict[str, Any]] = [*dataset.metadata_.get("document_attachments", []), *dataset.metadata_.get("retained_document_attachments", [])]
                for entry in entries:
                    attachment_id = UUID(str(entry["id"]))
                    if await get_db().get(DatasetAttachment, attachment_id) is not None:
                        continue
                    alias = f"document://{identity}/attachments/{attachment_id}"
                    file_id = await get_db().scalar(select(FileAlias.file_id).where(FileAlias.uri == alias))
                    stored = await get_db().get(StoredFile, file_id) if file_id else None
                    get_db().add(DatasetAttachment(id=attachment_id, dataset_id=identity,
                        uri=f"file://{file_id}" if file_id else alias, file_id=file_id,
                        name=entry["name"], media_type=entry["media_type"], size_bytes=entry.get("size_bytes"),
                        sha256=stored.sha256 if stored else None))
                await get_db().flush()
            await get_db().commit()

    async def grant(self, identity: UUID, actor: int | HumanActor, kind: str, principal: int, write: bool | None) -> None:
        if kind not in {"agent", "user", "team"}:
            raise ValueError("Unknown Dataset collaborator kind")
        with legacy_errors():
            dataset = await service.record(identity, actor, manage=True)
            await service.set_grant(identity, actor, kind=cast(Literal["agent", "user", "team"], kind), principal=principal,
                can_write=write, expected_lock_version=dataset.lock_version)
            await get_db().commit()

    async def history(self, identity: UUID, actor: int | HumanActor, limit: int, offset: int) -> dict[str, Any]:
        with legacy_errors():
            await service.record(identity, actor)
            from .models import DatasetRevision
            from sqlalchemy import func
            total = await get_db().scalar(select(func.count()).select_from(DatasetRevision).where(DatasetRevision.dataset_id == identity)) or 0
            rows = await get_db().execute(select(
                DatasetRevision.revision,
                func.encode(func.sha256(func.convert_to(DatasetRevision.content, "UTF8")), "hex"),
                DatasetRevision.author_agent_id, DatasetRevision.created_at,
            ).where(DatasetRevision.dataset_id == identity)
                .order_by(DatasetRevision.revision.desc()).limit(limit).offset(offset))
            return {"total": total, "limit": limit, "offset": offset, "has_more": offset + limit < total,
                "items": [{"revision": revision, "task_id": None, "content_hash": digest,
                    "media_type": "application/json", "content_profile_version": None, "author_agent_id": agent_id,
                    "created_at": created_at} for revision, digest, agent_id, created_at in rows]}

    async def restore(self, identity: UUID, actor: int | HumanActor, number: int, expected_revision: int) -> None:
        with legacy_errors():
            await service.restore(identity, actor, number=number, expected_revision=expected_revision)
            await get_db().commit()

    async def budget(self, identity: UUID, user_id: int, size: int) -> None:
        await service.reserve_budget(user_id, identity, size)

    async def sharing(self, identity: UUID, state: dict[str, Any]) -> None:
        """Trusted legacy command: its caller already checked ownership and version."""
        with legacy_errors():
            original = await get_db().get(Dataset, identity)
            if original is None:
                raise service.DatasetNotFoundError("Dataset not found")
            actor = original.owner_agent_id if original.owner_agent_id is not None else HumanActor(original.owner_user_id or 0)
            dataset = await service.record(identity, actor, manage=True, lock=True)
            dataset.global_access, dataset.group_access = state["global_access"], state["group_access"]
            dataset.owner_agent_id, dataset.owner_user_id = state["owner_agent_id"], state["owner_user_id"]
            await get_db().execute(delete(ShareGrant).where(ShareGrant.share_id == Dataset.share_for(identity)))
            for entry in state["grants"]:
                get_db().add(ShareGrant(share_id=Dataset.share_for(identity), **entry))
            dataset.lock_version = max(dataset.lock_version + 1, state["lock_version"])
            await get_db().flush()
            from .projection import changed
            await changed(dataset)

    async def remove(self, identity: UUID, actor: int | HumanActor) -> None:
        with legacy_errors():
            dataset = await service.record(identity, actor, manage=True, lock=True)
            await service.remove(identity, actor, expected_lock_version=dataset.lock_version)

    async def application(self, operation: str, actor: AgentManagementScope, context: dict[str, Any]) -> dict[str, Any]:
        from .apps import application
        with legacy_errors():
            return await application(operation, actor, context)

    async def attachments(self, identity: UUID, actor: int | HumanActor) -> list[dict[str, Any]]:
        with legacy_errors():
            document = await service.record(identity, actor)
            rows = list(await get_db().scalars(select(DatasetAttachment).where(DatasetAttachment.dataset_id == identity).order_by(DatasetAttachment.created_at, DatasetAttachment.id).limit(500)))
            names = await registered_file_names(item.file_id for item in rows if item.file_id is not None)
            from ..document_attachment_service import attachments_from_item
            common = [item.model_dump(mode="json") for item in attachments_from_item(document)]
            native = [{"id": str(item.id), "uri": item.uri, "name": names.get(item.file_id, item.name) if item.file_id else item.name, "media_type": item.media_type,
                "size_bytes": item.size_bytes or 0, "created_at": item.created_at} for item in rows]
            return list({str(item["id"]): item for item in [*native, *common]}.values())

    async def read_attachment(self, identity: UUID, attachment_id: UUID, actor: int | HumanActor) -> tuple[dict[str, Any], bytes] | None:
        from .attachments import read_native
        with legacy_errors():
            return await read_native(identity, attachment_id, actor)

    async def attachment_path(self, identity: UUID, attachment_id: UUID, actor: int | HumanActor) -> tuple[dict[str, Any], Path] | None:
        from .attachments import native_path
        with legacy_errors():
            return await native_path(identity, attachment_id, actor)
