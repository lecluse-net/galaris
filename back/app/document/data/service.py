"""The sole authority for Dataset content and revisions, including legacy callers."""

from __future__ import annotations

from app.share import ShareGrant

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, update, inspect
from sqlalchemy.orm import defer

from app.agent import AgentManagementScope
from core.database import get_db
from core.user import HumanActor

from .access import accessible_clause, access, is_administrator
from .contracts import DataActor, DatasetAccess, DatasetConflictError, DatasetNotFoundError, DatasetPermissionError, DatasetWriteLimitError
from .models import Dataset, DatasetRevision, DatasetWriteBudget
from .library import LibraryFilters

MAX_BYTES = 2_000_000
MAX_WRITES = 30
MAX_WRITE_BYTES = 4_000_000
WINDOW_SECONDS = 60


from .content import parse_json as parse_json, encode as encode


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def actor_keys(actor: DataActor) -> dict[str, int | None]:
    return {"author_agent_id": actor if isinstance(actor, int) else None,
            "author_user_id": None if isinstance(actor, int) else actor.user_id}


async def record(identity: UUID, actor: DataActor, *, write: bool = False, manage: bool = False, lock: bool = False) -> Dataset:
    owner_only = manage and not await is_administrator(actor)
    query = select(Dataset).where(Dataset.id == identity, accessible_clause(actor, write=write, manage=owner_only))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    dataset = await get_db().scalar(query)
    if dataset is None:
        raise DatasetNotFoundError("Dataset not found or unavailable")
    return dataset


async def describe(dataset: Dataset, actor: DataActor, *, content: bool = True) -> dict[str, Any]:
    if "updated_at" in inspect(dataset).expired_attributes:
        await get_db().refresh(dataset, attribute_names=["updated_at"])
    permissions = await access(dataset, actor)
    return _description(dataset, permissions, content=content)


def _description(dataset: Dataset, permissions: DatasetAccess, *, content: bool,
                 size_checksum: tuple[int, str] | None = None) -> dict[str, Any]:
    size, checksum = size_checksum if size_checksum is not None else (
        len(dataset.content.encode()), hashlib.sha256(dataset.content.encode()).hexdigest())
    result: dict[str, Any] = {
        "id": str(dataset.id), "uri": f"data://{dataset.id}", "title": dataset.title,
        "topic_id": str(dataset.topic_id) if dataset.topic_id is not None else None,
        "revision": dataset.revision, "lock_version": dataset.lock_version,
        "owner_agent_id": dataset.owner_agent_id, "owner_user_id": dataset.owner_user_id,
        "global_access": dataset.global_access, "group_access": dataset.group_access,
        "keywords": dataset.keywords, "metadata": dataset.metadata_, "read_only": dataset.read_only,
        "size": size, "checksum": checksum, "summary_content": dataset.summary_content, "summary_pending": dataset.summary_pending,
        "summary_media_type": dataset.summary_media_type,
        "can_write": permissions.can_write,
        "can_manage": permissions.can_manage, "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "can_delete": permissions.can_manage,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }
    if content:
        result["content"] = dataset.content
    return result


async def create(actor: DataActor, *, title: str, content: str = "[]", owner_agent_id: int | None = None,
                 creation_key: str | None = None, metadata: dict[str, Any] | None = None,
                 identity: UUID | None = None, keywords: list[str] | None = None) -> Dataset:
    parse_json(content)
    if not title.strip() or len(title) > 500:
        raise ValueError("A Dataset requires a title of at most 500 characters")
    owner_user_id = None if isinstance(actor, int) or owner_agent_id is not None else actor.user_id
    owner_agent_id = actor if isinstance(actor, int) else owner_agent_id
    if isinstance(actor, AgentManagementScope) and owner_agent_id is not None:
        actor.require(owner_agent_id)
    if isinstance(actor, HumanActor) and owner_agent_id is not None:
        raise DatasetPermissionError("An Agent management scope is required")
    requested = fingerprint({"title": title.strip(), "content": content, "owner_agent": owner_agent_id,
        "owner_user": owner_user_id, "metadata": metadata or {}, **({"keywords": keywords} if keywords is not None else {})})
    if creation_key:
        await get_db().execute(select(func.pg_advisory_xact_lock(int.from_bytes(hashlib.sha256(creation_key.encode()).digest()[:8], "big", signed=True))))
        existing = await get_db().scalar(select(Dataset).where(Dataset.creation_key == creation_key).with_for_update())
        if existing is not None:
            if existing.creation_fingerprint != requested:
                raise DatasetConflictError("Dataset creation key already has another request")
            if (existing.owner_agent_id, existing.owner_user_id) != (owner_agent_id, owner_user_id):
                raise DatasetConflictError("Dataset creation key already belongs to another request")
            await record(existing.id, actor)
            return existing
    controlled = dict(metadata or {})
    if "creation_command" in controlled:
        raise ValueError("Dataset creation identity is server-owned")
    dataset = Dataset(id=identity or uuid4(), owner_agent_id=owner_agent_id, owner_user_id=owner_user_id,
        title=title.strip(), content=content, revision=1, lock_version=1,
        global_access=0, group_access=0, read_only=False, keywords=keywords or [], metadata_=controlled, creation_key=creation_key, creation_fingerprint=requested)
    get_db().add(dataset)
    await get_db().flush()
    from .resource_summaries import refresh_pending
    refresh_pending(dataset)
    get_db().add(DatasetRevision(dataset_id=dataset.id, revision=1, content=content, **actor_keys(actor)))
    await get_db().flush()
    from .projection import changed
    await changed(dataset)
    return dataset


async def replace(identity: UUID, actor: DataActor, *, content: str, expected_revision: int | None,
                  consume_budget: bool = False) -> Dataset:
    dataset = await record(identity, actor, write=True, lock=True)
    if expected_revision is None or dataset.revision != expected_revision:
        raise DatasetConflictError("Read the current Dataset revision before writing")
    parse_json(content)
    if dataset.content == content:
        return dataset
    if consume_budget and not isinstance(actor, int):
        await reserve_budget(actor.user_id, dataset.id, len(content.encode()))
    dataset.content, dataset.revision = content, dataset.revision + 1
    dataset.lock_version += 1
    dataset.content_hash = hashlib.sha256(content.encode()).hexdigest()
    dataset.size_bytes = len(content.encode())
    dataset.resource_id = str(uuid4())
    dataset.search_text = content
    dataset.thumbnail_id = None
    from .resource_summaries import refresh_pending
    refresh_pending(dataset)
    get_db().add(DatasetRevision(dataset_id=dataset.id, revision=dataset.revision, content=content,
        **actor_keys(actor)))
    await get_db().flush()
    from .projection import changed
    await changed(dataset)
    return dataset


async def reserve_budget(user_id: int, identity: UUID, size: int) -> None:
    """Caller holds the Dataset lock; aliases and all write surfaces share this row."""
    db = get_db()
    now: datetime = (await db.execute(select(func.clock_timestamp()))).scalar_one()
    budget = await db.scalar(select(DatasetWriteBudget).where(DatasetWriteBudget.dataset_id == identity,
        DatasetWriteBudget.user_id == user_id).execution_options(populate_existing=True))
    if budget is None:
        budget = DatasetWriteBudget(dataset_id=identity, user_id=user_id, window_start=now, writes=0, bytes_written=0)
        db.add(budget)
    if (now - budget.window_start).total_seconds() >= WINDOW_SECONDS:
        budget.window_start, budget.writes, budget.bytes_written = now, 0, 0
    if budget.writes >= MAX_WRITES or budget.bytes_written + size > MAX_WRITE_BYTES:
        raise DatasetWriteLimitError("Dataset write budget exhausted; retry after one minute")
    budget.writes += 1
    budget.bytes_written += size


async def history(identity: UUID, actor: DataActor, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    await record(identity, actor)
    total = await get_db().scalar(select(func.count()).select_from(DatasetRevision).where(DatasetRevision.dataset_id == identity))
    revisions = await get_db().execute(select(
        DatasetRevision.revision,
        func.octet_length(func.convert_to(DatasetRevision.content, "UTF8")),
        DatasetRevision.created_at, DatasetRevision.author_user_id, DatasetRevision.author_agent_id,
    ).where(DatasetRevision.dataset_id == identity)
        .order_by(DatasetRevision.revision.desc()).limit(page_size).offset((page - 1) * page_size))
    return {"total": total or 0, "items": [{"revision": number, "size": size,
        "created_at": created_at.isoformat(), "author_user_id": user_id, "author_agent_id": agent_id}
        for number, size, created_at, user_id, agent_id in revisions]}


async def revision(identity: UUID, actor: DataActor, number: int) -> DatasetRevision:
    await record(identity, actor)
    item = await get_db().scalar(select(DatasetRevision).where(DatasetRevision.dataset_id == identity, DatasetRevision.revision == number))
    if item is None:
        raise DatasetNotFoundError("Dataset revision not found")
    return item


async def restore(identity: UUID, actor: DataActor, *, number: int, expected_revision: int) -> Dataset:
    snapshot = await revision(identity, actor, number)
    return await replace(identity, actor, content=snapshot.content or "", expected_revision=expected_revision, consume_budget=True)


async def set_grant(identity: UUID, actor: DataActor, *, kind: Literal["agent", "user", "team"],
                    principal: int, can_write: bool | None, expected_lock_version: int) -> Dataset:
    from .. import sharing_inheritance
    await sharing_inheritance.lock_sharing()
    dataset = await record(identity, actor, manage=True, lock=True)
    if dataset.read_only:
        raise DatasetPermissionError("A read-only Dataset cannot be reshared")
    if (kind == "agent" and principal == dataset.owner_agent_id) or (kind == "user" and principal == dataset.owner_user_id):
        raise ValueError("The owner already has access")
    if dataset.lock_version != expected_lock_version:
        raise DatasetConflictError("Dataset sharing changed; reload before updating")
    if can_write is not None:
        from app.agent import Agent
        from core.team import TeamModel
        from core.user import UserModel
        target = await get_db().scalar({
            "agent": select(Agent.id).where(Agent.id == principal),
            "user": select(UserModel.id).where(UserModel.id == principal, UserModel.is_active.is_(True)),
            "team": select(TeamModel.id).where(TeamModel.id == principal),
        }[kind])
        if target is None:
            raise DatasetNotFoundError("Collaborator not found")
    from app.share import set_grant as set_share_grant
    await sharing_inheritance.prepare_own_sharing(dataset)
    await set_share_grant(dataset.share_id, kind, principal, can_write)
    has_grants = await get_db().scalar(select(ShareGrant.id).where(ShareGrant.share_id == dataset.share_id).limit(1))
    dataset.visibility = "shared" if dataset.global_access or dataset.group_access or has_grants else "private"
    dataset.lock_version += 1
    await sharing_inheritance.finish_own_sharing(dataset)
    await get_db().flush()
    from .projection import changed
    await changed(dataset)
    return dataset


async def metadata(identity: UUID, actor: DataActor, *, expected_lock_version: int,
                   values: dict[str, Any]) -> Dataset:
    from .. import sharing_inheritance
    sharing_change = bool(set(values) & {"global_access", "group_access"})
    if sharing_change:
        await sharing_inheritance.lock_sharing()
    dataset = await record(identity, actor, lock=True)
    permissions = await access(dataset, actor)
    if not permissions.can_write and not (permissions.can_manage and set(values) <= {"read_only"}):
        raise DatasetPermissionError("Dataset is read only")
    if dataset.lock_version != expected_lock_version:
        raise DatasetConflictError("Dataset changed; reload its metadata")
    if set(values) - {"title", "keywords", "summary_content", "metadata", "global_access", "group_access", "read_only"}:
        raise ValueError("Unsupported Dataset metadata field")
    if any(key in values for key in ("global_access", "group_access", "read_only")):
        await record(identity, actor, manage=True)
    if sharing_change:
        await sharing_inheritance.prepare_own_sharing(dataset)
    if "metadata" in values:
        updated: dict[str, Any] = values["metadata"]
        if any(updated.get(key) != dataset.metadata_.get(key) for key in ("creation_command", "topic_assignment")):
            raise DatasetPermissionError("Dataset creation identity is server-owned")
        dataset.metadata_ = deepcopy(updated)
    if "title" in values:
        title = str(values["title"]).strip()
        if not title or len(title) > 500:
            raise ValueError("Dataset requires a title of at most 500 characters")
        dataset.title = title
    if "keywords" in values:
        raw_keywords: object = values["keywords"]
        if not isinstance(raw_keywords, list):
            raise ValueError("Invalid Dataset keywords")
        keywords = cast(list[object], raw_keywords)
        if len(keywords) > 100 or any(not isinstance(word, str) or len(word) > 200 for word in keywords):
            raise ValueError("Invalid Dataset keywords")
        dataset.keywords = cast(list[str], keywords)
    if "summary_content" in values:
        summary = values["summary_content"]
        if summary is not None and (not isinstance(summary, str) or len(summary) > 8000):
            raise ValueError("A Dataset summary must contain at most 8000 characters")
        from core.util import normalize_summary_source as normalize_source
        dataset.summary_content = str(summary).strip() if summary else None
        dataset.summary_media_type = "text/plain"
        from .resource_summaries import sync_summary_metadata
        sync_summary_metadata(dataset)
        dataset.summary_generated = False
        dataset.summary_source_text = normalize_source(dataset.content, "json")
        from .resource_summaries import refresh_pending
        refresh_pending(dataset)
    global_access, group_access = values.get("global_access", dataset.global_access), values.get("group_access", dataset.group_access)
    if type(global_access) is not int or type(group_access) is not int or global_access not in {0, 1, 2} or group_access not in {0, 1, 2} or global_access and group_access:
        raise ValueError("Choose global or owner-team access with level 0, 1 or 2")
    dataset.global_access, dataset.group_access = global_access, group_access
    if "read_only" in values:
        if type(values["read_only"]) is not bool:
            raise ValueError("read_only requires a boolean")
        dataset.read_only = values["read_only"]
    dataset.lock_version += 1
    if sharing_change:
        await sharing_inheritance.finish_own_sharing(dataset)
    await get_db().flush()
    from .projection import changed
    await changed(dataset)
    return dataset


async def list_datasets(actor: DataActor, *, page: int = 1, page_size: int = 50,
                        query: str = "", tag_id: UUID | None = None,
                        owner_agent_id: int | None = None, filters: LibraryFilters | None = None) -> dict[str, Any]:
    from .models import DatasetTagAssignment
    statement = select(Dataset).where(accessible_clause(actor))
    from .library import filter_statement, placement, decorate
    filters = filters or LibraryFilters()
    statement = await filter_statement(statement, actor, filters)
    if owner_agent_id is not None:
        statement = statement.where(Dataset.owner_agent_id == owner_agent_id)
    if query.strip():
        from .search_predicates import text_search_clause
        statement = statement.where(text_search_clause(query.strip()))
    if tag_id is not None:
        from .models import DatasetTag
        if isinstance(actor, int) or await get_db().scalar(select(DatasetTag.id).where(DatasetTag.id == tag_id, DatasetTag.user_id == actor.user_id)) is None:
            raise DatasetNotFoundError("Personal Dataset tag not found")
        statement = statement.where(Dataset.id.in_(select(DatasetTagAssignment.dataset_id).where(DatasetTagAssignment.tag_id == tag_id)))
    total = await get_db().scalar(select(func.count()).select_from(statement.subquery())) or 0
    # One page snapshot contains both metadata and the live permissions. Large
    # JSON values stay in PostgreSQL; checksum/size retain their exact UTF-8 contract.
    administrator = await is_administrator(actor)
    column = {"position": placement(actor, tag_id), "title": func.lower(Dataset.title),
        "created_at": Dataset.created_at, "updated_at": func.coalesce(Dataset.updated_at, Dataset.created_at)}[filters.sort_by]
    rows = await get_db().execute(statement.add_columns(
        accessible_clause(actor, write=True).label("can_write"),
        accessible_clause(actor, manage=True).label("can_manage"),
        func.octet_length(func.convert_to(Dataset.content, "UTF8")).label("size"),
        func.encode(func.sha256(func.convert_to(Dataset.content, "UTF8")), "hex").label("checksum"),
    ).options(defer(Dataset.content, raiseload=True))
        .order_by((column.desc() if filters.sort_desc else column.asc()).nulls_last(), Dataset.id)
        .limit(page_size).offset((page - 1) * page_size))
    items = [_description(dataset,
        DatasetAccess(True, bool(write), bool(manage) or administrator), content=False,
        size_checksum=(int(size), str(checksum))) for dataset, write, manage, size, checksum in rows]
    if not isinstance(actor, int):
        await decorate(items, actor)
    return {"total": total, "items": items}


async def sharing(identity: UUID, actor: DataActor) -> dict[str, Any]:
    dataset = await record(identity, actor)
    grants = await get_db().scalars(select(ShareGrant).where(ShareGrant.share_id == Dataset.share_for(identity)))
    permissions = await access(dataset, actor)
    return {"lock_version": dataset.lock_version, "global_access": dataset.global_access,
        "group_access": dataset.group_access, "can_manage": permissions.can_manage,
        "grants": [{"id": str(entry.id), "agent_id": entry.agent_id, "user_id": entry.user_id,
            "team_id": entry.team_id, "can_write": entry.can_write} for entry in grants]}


async def remove(identity: UUID, actor: DataActor, *, expected_lock_version: int) -> None:
    dataset = await record(identity, actor, manage=True, lock=True)
    if dataset.deletion_protected:
        raise DatasetPermissionError("A managed Document cannot be deleted")
    if dataset.lock_version != expected_lock_version:
        raise DatasetConflictError("Dataset changed; reload before deleting")
    dataset.soft_delete()
    # Dataset owns its copied history; release migration pointers before Memory
    # erases the obsolete legacy revisions, without changing canonical content.
    await get_db().execute(update(DatasetRevision).where(DatasetRevision.dataset_id == identity)
        .values(document_source_revision_id=None))
    from app.memory import forget_resource_memories
    await forget_resource_memories([f"data://{identity}"], descendants=True)
    await get_db().flush()
    from .projection import changed
    await changed(dataset)
