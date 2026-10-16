"""The sole authority for Dataset content and revisions, including legacy callers."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import defer

from app.agent import AgentManagementScope
from core.database import get_db
from core.user import HumanActor

from .access import accessible_clause, access, is_administrator
from .contracts import DataActor, DatasetAccess, DatasetConflictError, DatasetNotFoundError, DatasetPermissionError, DatasetWriteLimitError
from .models import Dataset, DatasetGrant, DatasetRevision, DatasetWriteBudget

MAX_BYTES = 2_000_000
MAX_WRITES = 30
MAX_WRITE_BYTES = 4_000_000
WINDOW_SECONDS = 60


def parse_json(content: str, *, historical: bool = False) -> Any:
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Dataset content exceeds 2,000,000 bytes")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in items:
            if name in result and not historical:
                raise ValueError("Dataset JSON contains duplicate object keys")
            result[name] = value
        return result

    def constant(_value: str) -> Any:
        raise ValueError("Dataset JSON requires finite numbers")

    try:
        value: Any = json.loads(content, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError, UnicodeError):
        raise ValueError("Dataset requires valid UTF-8 JSON") from None
    stack: list[tuple[Any, int]] = [(value, 0)]
    count = 0
    while stack:
        current, depth = stack.pop()
        count += 1
        if depth > 32 or count > 20_000:
            raise ValueError("Dataset exceeds the depth or item limit")
        if isinstance(current, float) and not math.isfinite(current):
            raise ValueError("Dataset JSON requires finite numbers")
        if isinstance(current, dict):
            stack.extend((child, depth + 1) for child in cast(dict[str, Any], current).values())
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in cast(list[Any], current))
    return value


def encode(value: Any) -> str:
    try:
        content = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
    except (ValueError, TypeError, RecursionError):
        raise ValueError("Dataset requires finite JSON values") from None
    parse_json(content)
    return content


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
    permissions = await access(dataset, actor)
    return _description(dataset, permissions, content=content)


def _description(dataset: Dataset, permissions: DatasetAccess, *, content: bool,
                 size_checksum: tuple[int, str] | None = None) -> dict[str, Any]:
    size, checksum = size_checksum if size_checksum is not None else (
        len(dataset.content.encode()), hashlib.sha256(dataset.content.encode()).hexdigest())
    result: dict[str, Any] = {
        "id": str(dataset.id), "uri": f"data://{dataset.id}", "title": dataset.title,
        "revision": dataset.revision, "lock_version": dataset.lock_version,
        "owner_agent_id": dataset.owner_agent_id, "owner_user_id": dataset.owner_user_id,
        "global_access": dataset.global_access, "group_access": dataset.group_access,
        "keywords": dataset.keywords, "metadata": dataset.metadata_, "read_only": dataset.read_only,
        "size": size, "checksum": checksum,
        "can_write": permissions.can_write and not dataset.metadata_.get("engine_managed", False),
        "can_manage": permissions.can_manage, "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "can_delete": permissions.can_manage and not dataset.metadata_.get("engine_dataset") and not dataset.metadata_.get("engine_managed"),
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }
    if content:
        result["content"] = dataset.content
    return result


async def create(actor: DataActor, *, title: str, content: str = "[]", owner_agent_id: int | None = None,
                 creation_key: str | None = None, metadata: dict[str, Any] | None = None,
                 identity: UUID | None = None, engine_managed: bool = False) -> Dataset:
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
        "owner_user": owner_user_id, "metadata": metadata or {}, "engine_managed": engine_managed})
    if creation_key:
        await get_db().execute(select(func.pg_advisory_xact_lock(int.from_bytes(hashlib.sha256(creation_key.encode()).digest()[:8], "big", signed=True))))
        existing = await get_db().scalar(select(Dataset).where(Dataset.creation_key == creation_key).with_for_update())
        if existing is not None:
            if existing.creation_fingerprint != requested:
                raise DatasetConflictError("Dataset creation key already has another request")
            if (existing.owner_agent_id, existing.owner_user_id, existing.metadata_.get("engine_managed", False)) != (owner_agent_id, owner_user_id, engine_managed):
                raise DatasetConflictError("Dataset creation key already belongs to another request")
            await record(existing.id, actor)
            return existing
    controlled = dict(metadata or {})
    if any(key in controlled for key in ("engine_managed", "engine_agent", "workflow_integrations", "creation_command")):
        raise ValueError("Dataset engine metadata is server-owned")
    if engine_managed:
        if not isinstance(actor, int):
            raise DatasetPermissionError("An engine Dataset requires its execution Agent")
        controlled.update(engine_managed=True, engine_agent=actor)
    dataset = Dataset(id=identity or uuid4(), owner_agent_id=owner_agent_id, owner_user_id=owner_user_id,
        title=title.strip(), content=content, revision=1, lock_version=1,
        global_access=0, group_access=0, read_only=False, keywords=[], metadata_=controlled, creation_key=creation_key, creation_fingerprint=requested)
    get_db().add(dataset)
    await get_db().flush()
    get_db().add(DatasetRevision(dataset_id=dataset.id, revision=1, content=content, **actor_keys(actor)))
    await get_db().flush()
    return dataset


async def replace(identity: UUID, actor: DataActor, *, content: str, expected_revision: int | None,
                  engine: bool = False, consume_budget: bool = False) -> Dataset:
    dataset = await record(identity, actor, write=True, lock=True)
    if expected_revision is None or dataset.revision != expected_revision:
        raise DatasetConflictError("Read the current Dataset revision before writing")
    if dataset.metadata_.get("engine_managed") and not (engine and actor == dataset.metadata_.get("engine_agent")):
        raise DatasetPermissionError("Run data is integrated by the workflow engine; submit the activity output instead")
    parse_json(content)
    if dataset.content == content:
        return dataset
    if consume_budget and not isinstance(actor, int):
        await reserve_budget(actor.user_id, dataset.id, len(content.encode()))
    dataset.content, dataset.revision = content, dataset.revision + 1
    dataset.lock_version += 1
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
    revisions = list(await get_db().scalars(select(DatasetRevision).where(DatasetRevision.dataset_id == identity)
        .order_by(DatasetRevision.revision.desc()).limit(page_size).offset((page - 1) * page_size)))
    return {"total": total or 0, "items": [{"revision": item.revision, "size": len(item.content.encode()),
        "created_at": item.created_at.isoformat(), "author_user_id": item.author_user_id, "author_agent_id": item.author_agent_id} for item in revisions]}


async def revision(identity: UUID, actor: DataActor, number: int) -> DatasetRevision:
    await record(identity, actor)
    item = await get_db().scalar(select(DatasetRevision).where(DatasetRevision.dataset_id == identity, DatasetRevision.revision == number))
    if item is None:
        raise DatasetNotFoundError("Dataset revision not found")
    return item


async def restore(identity: UUID, actor: DataActor, *, number: int, expected_revision: int) -> Dataset:
    snapshot = await revision(identity, actor, number)
    return await replace(identity, actor, content=snapshot.content, expected_revision=expected_revision, consume_budget=True)


async def set_grant(identity: UUID, actor: DataActor, *, kind: Literal["agent", "user", "team"],
                    principal: int, can_write: bool | None, expected_lock_version: int) -> Dataset:
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
    column = {"agent": DatasetGrant.agent_id, "user": DatasetGrant.user_id, "team": DatasetGrant.team_id}[kind]
    grant = await get_db().scalar(select(DatasetGrant).where(DatasetGrant.dataset_id == identity, column == principal))
    if grant is not None and can_write is None:
        await get_db().delete(grant)
    elif grant is not None:
        grant.can_write = bool(can_write)
    elif can_write is not None:
        get_db().add(DatasetGrant(dataset_id=identity, can_write=can_write, **{kind + "_id": principal}))
    dataset.lock_version += 1
    await get_db().flush()
    from .projection import changed
    await changed(dataset)
    return dataset


async def metadata(identity: UUID, actor: DataActor, *, expected_lock_version: int,
                   values: dict[str, Any], engine: bool = False) -> Dataset:
    dataset = await record(identity, actor, lock=True)
    permissions = await access(dataset, actor)
    if not permissions.can_write and not (permissions.can_manage and set(values) <= {"read_only"}):
        raise DatasetPermissionError("Dataset is read only")
    if dataset.lock_version != expected_lock_version:
        raise DatasetConflictError("Dataset changed; reload its metadata")
    if set(values) - {"title", "keywords", "metadata", "global_access", "group_access", "read_only"}:
        raise ValueError("Unsupported Dataset metadata field")
    if any(key in values for key in ("global_access", "group_access", "read_only")):
        await record(identity, actor, manage=True)
    if dataset.metadata_.get("engine_managed") and not (engine and actor == dataset.metadata_.get("engine_agent")):
        if set(values) - {"title", "keywords"}:
            raise DatasetPermissionError("Run Dataset metadata belongs to its engine")
    if "metadata" in values:
        updated: dict[str, Any] = values["metadata"]
        protected = {"engine_managed", "engine_dataset", "engine_agent", "creation_command", "workflow_integrations", "process_code", "workflow_attachments"}
        if not engine and any(updated.get(key) != dataset.metadata_.get(key) for key in protected):
            raise DatasetPermissionError("Dataset engine metadata is server-owned")
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
    global_access, group_access = values.get("global_access", dataset.global_access), values.get("group_access", dataset.group_access)
    if type(global_access) is not int or type(group_access) is not int or global_access not in {0, 1, 2} or group_access not in {0, 1, 2} or global_access and group_access:
        raise ValueError("Choose global or owner-team access with level 0, 1 or 2")
    dataset.global_access, dataset.group_access = global_access, group_access
    if "read_only" in values:
        if type(values["read_only"]) is not bool:
            raise ValueError("read_only requires a boolean")
        dataset.read_only = values["read_only"]
    dataset.lock_version += 1
    await get_db().flush()
    from .projection import changed
    await changed(dataset)
    return dataset


async def list_datasets(actor: DataActor, *, page: int = 1, page_size: int = 50,
                        query: str = "", tag_id: UUID | None = None) -> dict[str, Any]:
    from .models import DatasetTagAssignment
    statement = select(Dataset).where(accessible_clause(actor))
    if query.strip():
        statement = statement.where(Dataset.title.icontains(query.strip(), autoescape=True))
    if tag_id is not None:
        from .models import DatasetTag
        if isinstance(actor, int) or await get_db().scalar(select(DatasetTag.id).where(DatasetTag.id == tag_id, DatasetTag.user_id == actor.user_id)) is None:
            raise DatasetNotFoundError("Personal Dataset tag not found")
        statement = statement.where(Dataset.id.in_(select(DatasetTagAssignment.dataset_id).where(DatasetTagAssignment.tag_id == tag_id)))
    total = await get_db().scalar(select(func.count()).select_from(statement.subquery())) or 0
    # One page snapshot contains both metadata and the live permissions. Large
    # JSON values stay in PostgreSQL; checksum/size retain their exact UTF-8 contract.
    administrator = await is_administrator(actor)
    rows = await get_db().execute(statement.add_columns(
        accessible_clause(actor, write=True).label("can_write"),
        accessible_clause(actor, manage=True).label("can_manage"),
        func.octet_length(func.convert_to(Dataset.content, "UTF8")).label("size"),
        func.encode(func.sha256(func.convert_to(Dataset.content, "UTF8")), "hex").label("checksum"),
    ).options(defer(Dataset.content, raiseload=True))
        .order_by(Dataset.updated_at.desc().nulls_last(), Dataset.created_at.desc(), Dataset.id)
        .limit(page_size).offset((page - 1) * page_size))
    return {"total": total, "items": [_description(dataset,
        DatasetAccess(True, bool(write), bool(manage) or administrator), content=False,
        size_checksum=(int(size), str(checksum))) for dataset, write, manage, size, checksum in rows]}


async def sharing(identity: UUID, actor: DataActor) -> dict[str, Any]:
    dataset = await record(identity, actor)
    grants = await get_db().scalars(select(DatasetGrant).where(DatasetGrant.dataset_id == identity))
    permissions = await access(dataset, actor)
    return {"lock_version": dataset.lock_version, "global_access": dataset.global_access,
        "group_access": dataset.group_access, "can_manage": permissions.can_manage,
        "grants": [{"id": str(entry.id), "agent_id": entry.agent_id, "user_id": entry.user_id,
            "team_id": entry.team_id, "can_write": entry.can_write} for entry in grants]}


async def remove(identity: UUID, actor: DataActor, *, expected_lock_version: int) -> None:
    dataset = await record(identity, actor, manage=True, lock=True)
    if dataset.lock_version != expected_lock_version:
        raise DatasetConflictError("Dataset changed; reload before deleting")
    if dataset.metadata_.get("engine_dataset") or dataset.metadata_.get("engine_managed"):
        raise DatasetPermissionError("The Process domain owns this Dataset lifecycle")
    dataset.soft_delete()
    await get_db().flush()
    from .projection import changed
    await changed(dataset)
