"""Memory implementation of the Goal-owned Markdown document port."""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent
from app.goal import (
    Goal,
    GoalDocumentKind,
    GoalDocumentStore,
    register_goal_document_store,
)
from core.database import get_db
from core.i18n import normalize_language, t
from core.user import UserModel

from . import service
from .document_service import create_document
from .models import MemoryItem, MemoryItemGrant
from .schemas import MemoryItemUpdate


def _document_title(kind: GoalDocumentKind, goal_title: str) -> str:
    label = "Description" if kind == "description" else "Suivi"
    return f"{goal_title} — {label}"


def _goal_folder(goal_title: str, language: object) -> str:
    """Return the localized, hierarchy-safe folder owned by one Goal."""

    lang = normalize_language(language)
    sanitized_title = re.sub(
        r"\s+",
        " ",
        goal_title.replace("/", " ").replace("\\", " "),
    ).strip()
    if sanitized_title in {"", ".", ".."}:
        sanitized_title = t("goal_documents.untitled", lang)
    root = t("goal_documents.folder", lang)
    return f"{root}/{sanitized_title}"[:500].rstrip()


async def _owner_language(owner_agent_id: int) -> object:
    return await get_db().scalar(
        select(UserModel.language)
        .join(Agent, Agent.user_id == UserModel.id)
        .where(Agent.id == owner_agent_id)
    )


async def reconcile_goal_document_paths(session: AsyncSession) -> int:
    """Repair every stored Goal document title and path from its owning Goal."""

    rows = (
        await session.execute(
            select(MemoryItem, Goal.title, UserModel.language)
            .join(
                Goal,
                or_(
                    Goal.description_document_id == MemoryItem.id,
                    Goal.tracking_document_id == MemoryItem.id,
                ),
            )
            .join(Agent, Agent.id == Goal.agent_id)
            .join(UserModel, UserModel.id == Agent.user_id)
        )
    ).all()
    changed = 0
    for item, goal_title, language in rows:
        expected_path = _goal_folder(str(goal_title), language)
        raw_kind = item.metadata_.get("goal_document_kind")
        if raw_kind == "description":
            kind: GoalDocumentKind = "description"
        elif raw_kind == "tracking":
            kind = "tracking"
        else:
            continue
        expected_title = _document_title(kind, str(goal_title))
        if (
            item.title == expected_title
            and item.metadata_.get("document_path") == expected_path
        ):
            continue
        item.title = expected_title
        item.metadata_ = {**item.metadata_, "document_path": expected_path}
        changed += 1
    await session.flush()
    return changed


class MemoryGoalDocumentStore(GoalDocumentStore):
    async def create(
        self,
        *,
        goal_id: UUID,
        owner_agent_id: int,
        kind: GoalDocumentKind,
        goal_title: str,
        content: str,
    ) -> UUID:
        if kind not in {"description", "tracking"}:
            raise ValueError(f"Unsupported Goal document kind: {kind!r}.")
        language = await _owner_language(owner_agent_id)
        item = await create_document(
            owner_agent_id=owner_agent_id,
            title=_document_title(kind, goal_title),
            content=content,
            task_id=None,
            folder=_goal_folder(goal_title, language),
            keywords=["goal", kind],
            metadata={
                "goal_id": str(goal_id),
                "goal_document_kind": kind,
            },
            deletion_protected=True,
        )
        return item.id

    async def read(self, document_id: UUID) -> str:
        item, content, _access, content_type, media_type = await service.get_item(
            document_id,
            agent_id=None,
            administrative=True,
        )
        if item.node_kind != "document":
            raise service.MemoryConflictError("A Goal Markdown reference is not a document.")
        if content_type != "text" and not media_type.startswith("text/"):
            raise service.MemoryConflictError("A Goal document must contain UTF-8 text.")
        return content.decode("utf-8")

    async def revision(self, document_id: UUID) -> int:
        item = await service._get_item_record(document_id)  # pyright: ignore[reportPrivateUsage]
        if item is None:
            raise service.MemoryNotFoundError("Goal document not found.")
        return item.revision

    async def read_many(self, document_ids: tuple[UUID, ...]) -> dict[UUID, str]:
        contents: dict[UUID, str] = {}
        for document_id in dict.fromkeys(document_ids):
            contents[document_id] = await self.read(document_id)
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
            raise service.MemoryNotFoundError("Goal document not found.")
        if item.node_kind != "document" or not item.deletion_protected:
            raise service.MemoryConflictError("The selected item is not a protected Goal document.")
        raw_kind = item.metadata_.get("goal_document_kind")
        if raw_kind == "description":
            kind: GoalDocumentKind = "description"
        elif raw_kind == "tracking":
            kind = "tracking"
        else:
            raise service.MemoryConflictError("A Goal document has an invalid kind.")
        if content is not None or goal_title is not None:
            update_data: dict[str, object] = {"expected_revision": expected_revision or item.revision}
            if content is not None:
                update_data["payload"] = {"text": content}
            if goal_title is not None:
                update_data["title"] = _document_title(kind, goal_title)
                effective_owner_agent_id = (
                    owner_agent_id
                    if owner_agent_id is not None
                    else item.owner_agent_id
                )
                if effective_owner_agent_id is None:
                    raise service.MemoryConflictError(
                        "A Goal document must belong to an Agent."
                    )
                update_data["metadata"] = {
                    **item.metadata_,
                    "document_path": _goal_folder(
                        goal_title,
                        await _owner_language(effective_owner_agent_id),
                    ),
                }
            item = await service.update_item(
                document_id,
                MemoryItemUpdate.model_validate(update_data),
                actor_agent_id=None,
                administrative=True,
                notify_observers=False,
                allow_goal_document_metadata_sync=True,
            )
        if owner_agent_id is not None and owner_agent_id != item.owner_agent_id:
            item.owner_agent_id = owner_agent_id
            await get_db().execute(
                delete(MemoryItemGrant).where(MemoryItemGrant.item_id == document_id)
            )
            await get_db().commit()

    async def discard(self, document_id: UUID) -> None:
        item = await service._get_item_record(  # pyright: ignore[reportPrivateUsage]
            document_id, include_historized=True
        )
        if item is None:
            return
        if not item.deletion_protected:
            raise service.MemoryConflictError("Refusing to discard an ordinary document.")
        item.deletion_protected = False
        await get_db().commit()
        await service._forget_item_record(  # pyright: ignore[reportPrivateUsage]
            item, forget_kind="retention"
        )

    async def search(self, terms: tuple[str, ...]) -> dict[str, frozenset[UUID]]:
        result: dict[str, frozenset[UUID]] = {}
        for term in terms:
            pattern = f"%{term}%"
            ids = frozenset(
                (
                    await get_db().scalars(
                        select(MemoryItem.id).where(
                            MemoryItem.node_kind == "document",
                            MemoryItem.deletion_protected.is_(True),
                            or_(
                                MemoryItem.title.ilike(pattern),
                                MemoryItem.search_text.ilike(pattern),
                            ),
                        )
                    )
                ).all()
            )
            result[term] = ids
        return result


def register_goal_document_adapter() -> None:
    register_goal_document_store(MemoryGoalDocumentStore())


__all__ = [
    "MemoryGoalDocumentStore",
    "reconcile_goal_document_paths",
    "register_goal_document_adapter",
]
