"""Personal Goal filing, executed in bounded durable Memory jobs.

Each call uses its caller's transaction. Folder and assignment writes share the
same per-user lock as manual classification; documents themselves are untouched.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.elements import ColumnElement

from app.agent import management_scope_for
from app.goal import Goal
from app.task import Task
from core.authorize import role_id_ctx
from core.database import get_db
from core.i18n import normalize_language, t
from core.user import UserModel

from .access import human_document_clause, readable_item_for_agents_clause
from .document_tags import lock_tree, next_position
from .models import DocumentTag, DocumentTagAssignment, MemoryAutomationJob, MemoryItem, MemorySource


JOB_KIND = "goal_folder_reconcile"
BATCH_SIZE = 50


class GoalFolderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int | None = Field(default=None, gt=0)
    goal_id: UUID | None = None
    after_user: int = Field(default=0, ge=0)
    after_goal: UUID | None = None
    after_document: UUID | None = None


async def enqueue_goal_folder_reconciliation(
    *, user_id: int | None = None, goal_id: UUID | None = None,
) -> UUID:
    """Enqueue/coalesce a pending scope, without committing the caller's transaction.

    Running jobs are deliberately not coalesced: they may have already scanned the
    changed document. A fresh pending request then guarantees a subsequent pass.
    """
    request = GoalFolderRequest(user_id=user_id, goal_id=goal_id)
    payload = request.model_dump(mode="json")
    key = f"{JOB_KIND}:{user_id}:{goal_id}"
    lock = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
    db = get_db()
    await db.execute(select(func.pg_advisory_xact_lock(lock)))
    existing = await db.scalar(select(MemoryAutomationJob.id).where(
        MemoryAutomationJob.kind == JOB_KIND,
        MemoryAutomationJob.status == "pending",
        MemoryAutomationJob.payload == payload,
    ))
    if existing is not None:
        return existing
    job = MemoryAutomationJob(kind=JOB_KIND, idempotency_key=f"{JOB_KIND}:{uuid4()}", payload=payload)
    db.add(job)
    await db.flush()
    return job.id


def _documents_of(goal: Goal | type[Goal]) -> ColumnElement[bool]:
    task_source = select(MemorySource.id).join(Task, Task.id == MemorySource.task_id).where(
        MemorySource.item_id == MemoryItem.id, Task.goal_id == goal.id,
    ).correlate(MemoryItem, Goal)
    return or_(MemoryItem.id.in_((goal.description_document_id, goal.tracking_document_id)), exists(task_source))


async def _visible_documents(user: UserModel) -> tuple[ColumnElement[bool], ...]:
    # This is personal background work, never the role of the event's caller.
    role_token = role_id_ctx.set(None)
    try:
        scope = await management_scope_for(user, get_db())
    finally:
        role_id_ctx.reset(role_token)
    now = datetime.now(timezone.utc)
    return (
        MemoryItem.node_kind == "document",
        or_(readable_item_for_agents_clause(scope.agent_ids), human_document_clause(user.id)),
        or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
        or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
    )


async def _folder(user: UserModel, goal: Goal | None) -> DocumentTag:
    db = get_db()
    condition = DocumentTag.goal_id == goal.id if goal is not None else DocumentTag.system_role == "goals_root"
    folder = await db.scalar(select(DocumentTag).where(DocumentTag.user_id == user.id, condition))
    name = (
        " ".join(goal.title.split())[:100]
        if goal is not None else t("goal_documents.folder", normalize_language(user.language))
    )
    if folder is not None:
        if folder.name == folder.generated_name:
            folder.name = name
            folder.generated_name = name
        return folder
    if goal is None:
        # Reuse an ordinary root already bearing this exact localized name.
        folder = await db.scalar(select(DocumentTag).where(
            DocumentTag.user_id == user.id, DocumentTag.parent_id.is_(None),
            DocumentTag.name == name, DocumentTag.system_role.is_(None), DocumentTag.goal_id.is_(None),
        ).order_by(DocumentTag.position, DocumentTag.id).limit(1))
        if folder is not None:
            folder.system_role = "goals_root"
            folder.generated_name = name
            return folder
    parent = await _folder(user, None) if goal is not None else None
    folder = DocumentTag(
        user_id=user.id, goal_id=goal.id if goal is not None else None,
        system_role=None if goal is not None else "goals_root",
        name=name, generated_name=name, parent_id=parent.id if parent else None,
        position=await next_position(user.id, parent.id if parent else None),
    )
    db.add(folder)
    await db.flush()
    return folder


async def _file_pair(request: GoalFolderRequest) -> tuple[UUID | None, bool]:
    assert request.user_id is not None and request.goal_id is not None
    db = get_db()
    await lock_tree(request.user_id)
    user = await db.get(UserModel, request.user_id)
    goal = await db.get(Goal, request.goal_id)
    if user is None or not user.is_active or goal is None:
        return None, False
    base = (*await _visible_documents(user), _documents_of(goal))
    # Do not expose a renamed Goal to a user who can no longer read any document.
    if await db.scalar(select(MemoryItem.id).where(*base).limit(1)) is None:
        return None, False
    existing = await db.scalar(select(DocumentTag).where(
        DocumentTag.user_id == user.id, DocumentTag.goal_id == goal.id,
    ))
    changed = False
    if existing is not None:
        before = existing.name
        await _folder(user, goal)
        changed = existing.name != before
    assigned = exists(select(DocumentTagAssignment.id).join(DocumentTag).where(
        DocumentTagAssignment.document_id == MemoryItem.id, DocumentTag.user_id == user.id,
    ))
    query = select(MemoryItem.id).where(*base, ~assigned)
    if request.after_document is not None:
        query = query.where(MemoryItem.id > request.after_document)
    documents = list(await db.scalars(query.order_by(MemoryItem.id).limit(BATCH_SIZE + 1)))
    batch = documents[:BATCH_SIZE]
    if batch:
        folder = await _folder(user, goal)
        position = await next_position(user.id, folder.id)
        db.add_all([
            DocumentTagAssignment(tag_id=folder.id, document_id=identity, position=position + offset)
            for offset, identity in enumerate(batch)
        ])
        await db.flush()
        changed = True
    if changed:
        from .document_structure import sync_document_structure, sync_folder_structure
        await sync_folder_structure(user.id)
        for identity in batch:
            item = await db.get(MemoryItem, identity)
            if item is not None:
                await sync_document_structure(item)
    return (batch[-1] if len(documents) > BATCH_SIZE else None), changed


async def process_goal_folder_job(job_id: UUID, request: GoalFolderRequest) -> bool:
    """Process one bounded page and persist its continuation atomically with writes."""
    db = get_db()
    continuation: GoalFolderRequest | None = None
    changed = False
    if request.user_id is None:
        users = list(await db.scalars(select(UserModel.id).where(
            UserModel.is_active.is_(True), UserModel.id > request.after_user,
        ).order_by(UserModel.id).limit(BATCH_SIZE + 1)))
        for identity in users[:BATCH_SIZE]:
            await enqueue_goal_folder_reconciliation(user_id=identity, goal_id=request.goal_id)
        if len(users) > BATCH_SIZE:
            continuation = request.model_copy(update={"after_user": users[BATCH_SIZE - 1]})
    elif request.goal_id is None:
        user = await db.get(UserModel, request.user_id)
        if user is None or not user.is_active:
            return False
        visible = await _visible_documents(user)
        query = select(Goal.id).where(exists(select(MemoryItem.id).where(
            *visible, _documents_of(Goal),
        ).correlate(Goal)))
        if request.after_goal is not None:
            query = query.where(Goal.id > request.after_goal)
        goals = list(await db.scalars(query.order_by(Goal.id).limit(BATCH_SIZE + 1)))
        for identity in goals[:BATCH_SIZE]:
            await enqueue_goal_folder_reconciliation(user_id=request.user_id, goal_id=identity)
        if len(goals) > BATCH_SIZE:
            continuation = request.model_copy(update={"after_goal": goals[BATCH_SIZE - 1]})
    else:
        cursor, changed = await _file_pair(request)
        if cursor is not None:
            continuation = request.model_copy(update={"after_document": cursor})
    if continuation is not None:
        await db.execute(insert(MemoryAutomationJob).values(
            kind=JOB_KIND, idempotency_key=f"{JOB_KIND}:continue:{job_id}",
            payload=continuation.model_dump(mode="json"),
        ).on_conflict_do_nothing(index_elements=[MemoryAutomationJob.idempotency_key]))
    return changed


async def on_goal_change(goal_id: UUID, action: str) -> None:
    if action != "delete":
        await enqueue_goal_folder_reconciliation(goal_id=goal_id)
        await get_db().commit()


async def on_user_change(user_id: int | None) -> None:
    await enqueue_goal_folder_reconciliation(user_id=user_id)
    await get_db().commit()


async def on_access_change() -> None:
    await on_user_change(None)


async def on_document_change(item_id: UUID, _action: str) -> None:
    db = get_db()
    if await db.scalar(select(MemoryItem.id).where(
        MemoryItem.id == item_id, MemoryItem.node_kind == "document",
    )) is None:
        return
    ids = set(await db.scalars(select(Goal.id).where(or_(
        Goal.description_document_id == item_id, Goal.tracking_document_id == item_id,
        Goal.id.in_(select(Task.goal_id).join(MemorySource, MemorySource.task_id == Task.id).where(
            MemorySource.item_id == item_id, Task.goal_id.is_not(None),
        )),
    ))))
    for goal_id in sorted(ids):
        await enqueue_goal_folder_reconciliation(goal_id=goal_id)
    if ids:
        await db.commit()
