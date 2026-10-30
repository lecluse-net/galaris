"""Document implementation of the Goal-owned HTML tracking port."""

from __future__ import annotations

from app.share import ShareGrant

from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.goal import (
    Goal,
    GoalDocumentKind,
    GoalDocumentStore,
    register_goal_document_store,
)
from core.database import get_db

from . import resource_service as service
from .document_service import create_document
from .models import Document
from .schemas import DocumentUpdate
from core.storage import get_storage


def _document_title(kind: GoalDocumentKind, goal_title: str) -> str:
    return f"{goal_title} — Suivi"


async def reconcile_goal_document_paths(session: AsyncSession) -> int:
    """Repair tracking titles without assigning any personal classification."""

    rows = (
        await session.execute(
            select(Document, Goal.title)
            .join(
                Goal,
                or_(
                    Goal.tracking_document_id == Document.id,
                ),
            )
        )
    ).all()
    changed = 0
    for item, goal_title in rows:
        raw_kind = item.metadata_.get("goal_document_kind")
        if raw_kind == "tracking":
            kind: GoalDocumentKind = "tracking"
        else:
            continue
        expected_title = _document_title(kind, str(goal_title))
        if item.title == expected_title:
            continue
        item.title = expected_title
        changed += 1
    await session.flush()
    return changed


class DocumentGoalDocumentStore(GoalDocumentStore):
    async def create(
        self,
        *,
        goal_id: UUID,
        owner_agent_id: int,
        kind: GoalDocumentKind,
        goal_title: str,
        content: str,
    ) -> UUID:
        if kind != "tracking":
            raise ValueError(f"Unsupported Goal document kind: {kind!r}.")
        item = await create_document(
            owner_agent_id=owner_agent_id,
            title=_document_title(kind, goal_title),
            content=content,
            task_id=None,
            keywords=["goal", kind],
            metadata={
                "goal_id": str(goal_id),
                "goal_document_kind": kind,
            },
            deletion_protected=True,
        )
        return item.id

    async def read(self, document_id: UUID) -> str:
        return (await self.read_many((document_id,)))[document_id]

    async def revision(self, document_id: UUID) -> int:
        item = await service._get_item_record(document_id)  # pyright: ignore[reportPrivateUsage]
        if item is None:
            raise service.DocumentNotFoundError("Goal document not found.")
        return item.revision

    async def read_many(self, document_ids: tuple[UUID, ...]) -> dict[UUID, str]:
        identities = tuple(dict.fromkeys(document_ids))
        if not identities:
            return {}
        # This Goal-owned port already reads administratively, after its caller
        # authorizes the Goal. Current content needs neither grants nor revisions.
        # Read scalar metadata so an existing ORM instance cannot retain an older
        # resource pointer after another writer publishes a revision.
        rows = await get_db().execute(
            select(
                Document.id, Document.node_kind, Document.provider_code,
                Document.resource_id, Document.content_type, Document.media_type,
                Document.content.label("inline_content"),
            ).where(Document.id.in_(identities), Document.deleted_at.is_(None))
        )
        records = {row.id: row for row in rows}
        contents: dict[UUID, str] = {}
        for document_id in identities:
            item = records.get(document_id)
            if item is None:
                raise service.DocumentNotFoundError("Memory not found.")
            if item.node_kind != "document":
                raise service.DocumentConflictError("A Goal Markdown reference is not a document.")
            content = item.inline_content.encode("utf-8") if item.inline_content is not None else await get_storage(item.provider_code).read(item.resource_id)
            if item.content_type != "text" and not item.media_type.startswith("text/"):
                raise service.DocumentConflictError("A Goal document must contain UTF-8 text.")
            contents[document_id] = content.decode("utf-8")
        return contents

    async def update(
        self,
        document_id: UUID,
        *,
        content: str | None = None,
        expected_revision: int | None = None,
        goal_title: str | None = None,
        owner_agent_id: int | None = None,
    ) -> None:
        item = await service._get_item_record(document_id)  # pyright: ignore[reportPrivateUsage]
        if item is None:
            raise service.DocumentNotFoundError("Goal document not found.")
        if item.node_kind != "document" or not item.deletion_protected:
            raise service.DocumentConflictError("The selected item is not a protected Goal document.")
        raw_kind = item.metadata_.get("goal_document_kind")
        if raw_kind == "tracking":
            kind: GoalDocumentKind = "tracking"
        else:
            raise service.DocumentConflictError("A Goal document has an invalid kind.")
        if content is not None or goal_title is not None:
            update_data: dict[str, object] = {"expected_revision": expected_revision or item.revision}
            if content is not None:
                update_data["payload"] = {"text": content}
            if goal_title is not None:
                update_data["title"] = _document_title(kind, goal_title)
            item = await service.update_item(
                document_id,
                DocumentUpdate.model_validate(update_data),
                actor_agent_id=None,
                administrative=True,
                notify_observers=False,
                allow_goal_document_metadata_sync=True,
            )
        if owner_agent_id is not None and owner_agent_id != item.owner_agent_id:
            from .sharing_inheritance import prepare_own_sharing, finish_own_sharing
            await prepare_own_sharing(item)
            item.owner_agent_id = owner_agent_id
            await get_db().execute(
                delete(ShareGrant).where(ShareGrant.share_id == Document.share_for(document_id))
            )
            await finish_own_sharing(item)
            await get_db().commit()

    async def discard(self, document_id: UUID) -> None:
        item = await service._get_item_record(  # pyright: ignore[reportPrivateUsage]
            document_id, include_historized=True
        )
        if item is None:
            return
        if not item.deletion_protected:
            raise service.DocumentConflictError("Refusing to discard an ordinary document.")
        item.deletion_protected = False
        await get_db().commit()
        await service.forget_item_record(  # pyright: ignore[reportPrivateUsage]
            item, forget_kind="retention"
        )

    async def search(self, terms: tuple[str, ...]) -> dict[str, frozenset[UUID]]:
        result: dict[str, frozenset[UUID]] = {}
        for term in terms:
            pattern = f"%{term}%"
            ids = frozenset(
                (
                    await get_db().scalars(
                        select(Document.id).where(
                            Document.node_kind == "document",
                            Document.deletion_protected.is_(True),
                            or_(
                                Document.title.ilike(pattern),
                                Document.search_text.ilike(pattern),
                            ),
                        )
                    )
                ).all()
            )
            result[term] = ids
        return result


def register_goal_document_adapter() -> None:
    register_goal_document_store(DocumentGoalDocumentStore())


__all__ = [
    "DocumentGoalDocumentStore",
    "reconcile_goal_document_paths",
    "register_goal_document_adapter",
]
