"""Read-only Memory lists and document-library projections with bounded history loading."""

from collections.abc import Collection
from datetime import datetime, timezone
from typing import cast
from uuid import UUID
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import raiseload, selectinload
from sqlalchemy.sql.elements import ColumnElement
from core.database import get_db
from core.user import UserModel, get_user_record, list_user_records
from app.agent import Agent, list_agent_records
from .access import human_document_clause, document_team_agent_access
from .access import readable_item_for_agents_clause, readable_item_clause, managed_item_agent_ids
from .contracts import MemoryAccess
from .models import DocumentListPosition, DocumentTag, DocumentTagAssignment, MemoryItem
from .document_library_filters import library_filters
from .schemas import (
    DocumentLibraryRequest,
    DocumentLibraryPage,
    DocumentLibraryEntry,
    DocumentOwnerOption,
    DocumentOwnerOptions,
    DocumentTagPublic,
    MemoryType,
    RecentMemoryItem,
)
from .item_projection import item_to_public


async def list_recent_memories(
    *,
    managed_agent_ids: Collection[int] | None,
    limit: int,
) -> list[RecentMemoryItem]:
    """Return recent readable memories without loading their governed payloads."""

    now = datetime.now(timezone.utc)
    rows = list(
        (
            await get_db().scalars(
                select(MemoryItem)
                .where(
                    readable_item_for_agents_clause(managed_agent_ids),
                    MemoryItem.node_kind == "memory",
                    or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
                    or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
                )
                .order_by(MemoryItem.created_at.desc(), MemoryItem.id.desc())
                .limit(limit)
            )
        ).all()
    )
    return [
        RecentMemoryItem(
            id=item.id,
            title=item.title,
            memory_type=cast(MemoryType, item.memory_type),
            created_at=item.created_at,
        )
        for item in rows
    ]


async def list_document_keywords(agent_id: int) -> list[str]:
    """List distinct keywords from documents readable by one agent."""

    now = datetime.now(timezone.utc)
    result = await get_db().scalars(
        select(MemoryItem.keywords).where(
            readable_item_clause(agent_id),
            MemoryItem.node_kind == "document",
            or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
            or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
        )
    )
    keywords = {
        keyword.strip()
        for item_keywords in result.all()
        for keyword in item_keywords
        if keyword.strip()
    }
    return sorted(keywords, key=str.casefold)


async def list_document_owner_options(
    *,
    current_user_id: int,
    include_all_users: bool,
    managed_agent_ids: Collection[int] | None,
    search: str = "",
) -> DocumentOwnerOptions:
    """Return owner choices without leaking users outside the caller's scope."""

    normalized = search.strip().casefold()
    agents = await list_agent_records(
        limit=500,
        agent_ids=(frozenset(managed_agent_ids) if managed_agent_ids is not None else None),
    )
    agent_options: list[DocumentOwnerOption] = []
    for agent in agents:
        label = f"{agent.first_name} {agent.last_name}".strip() or agent.code
        searchable = f"{label} {agent.code}".casefold()
        if normalized and normalized not in searchable:
            continue
        agent_options.append(
            DocumentOwnerOption(
                kind="agent",
                id=agent.id,
                label=label,
                subtitle=agent.code,
            )
        )

    if include_all_users:
        users = await list_user_records(limit=500, search=search or None)
    else:
        current_user = await get_user_record(current_user_id)
        users = [current_user] if current_user is not None else []
    user_options = [
        DocumentOwnerOption(
            kind="user",
            id=user.id,
            label=(user.display_name or "").strip() or user.email,
            subtitle=user.email,
            avatar_url=user.avatar_url,
            is_current_user=user.id == current_user_id,
        )
        for user in users
        if user.is_active
        and (not normalized or normalized in f"{user.display_name or ''} {user.email}".casefold())
    ]
    user_options.sort(
        key=lambda option: (
            not option.is_current_user,
            option.label.casefold(),
            option.id,
        )
    )
    agent_options.sort(key=lambda option: (option.label.casefold(), option.id))
    return DocumentOwnerOptions(agents=agent_options, users=user_options)


async def browse_document_library(
    request: DocumentLibraryRequest,
    *,
    managed_agent_ids: Collection[int] | None,
    user_id: int | None = None,
) -> DocumentLibraryPage:
    """Browse every document visible to at least one managed Agent."""

    db = get_db()
    now = datetime.now(timezone.utc)
    scope_clause = readable_item_for_agents_clause(managed_agent_ids)
    if user_id is not None:
        scope_clause = or_(scope_clause, human_document_clause(user_id))
    base_filters: list[ColumnElement[bool]] = [
        scope_clause,
        MemoryItem.node_kind == "document",
        or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
        or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
    ]
    owner_options: list[DocumentOwnerOption] = []
    if request.include_owners:
        agent_rows = await db.execute(
            select(Agent.id, Agent.first_name, Agent.last_name, Agent.code)
            .join(MemoryItem, MemoryItem.owner_agent_id == Agent.id)
            .where(*base_filters)
            .distinct()
        )
        for identity, first, last, code in agent_rows:
            owner_options.append(
                DocumentOwnerOption(
                    kind="agent", id=identity, label=f"{first} {last}".strip() or code, subtitle=""
                )
            )
        user_rows = await db.execute(
            select(UserModel.id, UserModel.display_name, UserModel.email)
            .join(MemoryItem, MemoryItem.owner_user_id == UserModel.id)
            .where(*base_filters)
            .distinct()
        )
        for identity, name, email in user_rows:
            owner_options.append(
                DocumentOwnerOption(kind="user", id=identity, label=name or email, subtitle="")
            )
    owner_options.sort(key=lambda option: (option.label.casefold(), option.kind, option.id))
    base_filters.extend(await library_filters(request, user_id))
    keyword = request.keyword.strip() if request.keyword is not None else ""
    if keyword:
        base_filters.append(MemoryItem.keywords.contains([keyword]))
    normalized = request.query.strip()
    if normalized:
        ts_query = func.websearch_to_tsquery("simple", normalized)
        base_filters.append(
            or_(
                MemoryItem.search_vector.op("@@")(ts_query),
                MemoryItem.title.ilike(f"%{normalized}%"),
                MemoryItem.search_text.ilike(f"%{normalized}%"),
            )
        )

    total = int(await db.scalar(select(func.count(MemoryItem.id)).where(*base_filters)) or 0)
    position = func.coalesce(
        (
            select(DocumentTagAssignment.position)
            .where(
                DocumentTagAssignment.document_id == MemoryItem.id,
                DocumentTagAssignment.tag_id == request.tag_id,
            )
            .scalar_subquery()
            if request.tag_id is not None
            else select(DocumentListPosition.position)
            .where(
                DocumentListPosition.document_id == MemoryItem.id,
                DocumentListPosition.user_id == user_id,
            )
            .scalar_subquery()
        ),
        0,
    )
    sort_column = {
        "position": position,
        "title": func.lower(MemoryItem.title),
        "document_type": MemoryItem.document_type,
        "created_at": MemoryItem.created_at,
        "updated_at": func.coalesce(MemoryItem.updated_at, MemoryItem.created_at),
    }[request.sort_by]
    result = await db.execute(
        select(
            MemoryItem,
            position.label("position"),
            case(
                (
                    MemoryItem.owner_agent_id.is_not(None),
                    func.coalesce(
                        func.nullif(
                            func.trim(func.concat(Agent.first_name, " ", Agent.last_name)), ""
                        ),
                        Agent.code,
                        "",
                    ),
                ),
                else_=func.coalesce(func.nullif(UserModel.display_name, ""), UserModel.email, ""),
            ).label("owner_label"),
        )
        .outerjoin(Agent, MemoryItem.owner_agent_id == Agent.id)
        .outerjoin(UserModel, MemoryItem.owner_user_id == UserModel.id)
        .options(selectinload(MemoryItem.grants), raiseload(MemoryItem.revisions))
        .where(*base_filters)
        .order_by(
            sort_column.desc() if request.sort_desc else sort_column.asc(),
            func.lower(MemoryItem.title),
            MemoryItem.id,
        )
        .offset(request.offset)
        .limit(request.limit + 1)
        .execution_options(populate_existing=True)
    )
    rows = result.unique().all()
    items = [row[0] for row in rows]
    owner_labels = {row[0].id: cast(str, row.owner_label) for row in rows}
    positions = {row[0].id: cast(int, row.position) for row in rows}
    has_more = len(items) > request.limit
    items = items[: request.limit]
    personal_tags: dict[UUID, list[DocumentTagPublic]] = {}
    if user_id is not None and items:
        tag_rows = await db.execute(
            select(DocumentTagAssignment.document_id, DocumentTag)
            .join(DocumentTag)
            .where(
                DocumentTag.user_id == user_id,
                DocumentTagAssignment.document_id.in_([item.id for item in items]),
            )
            .order_by(func.lower(DocumentTag.name), DocumentTag.id)
        )
        for document_id, tag in tag_rows:
            personal_tags.setdefault(document_id, []).append(DocumentTagPublic.model_validate(tag))

    team_access = await document_team_agent_access([item.id for item in items])
    human_readable: set[UUID] = (
        set(
            await db.scalars(
                select(MemoryItem.id).where(
                    MemoryItem.id.in_([item.id for item in items]), human_document_clause(user_id)
                )
            )
        )
        if user_id is not None
        else set()
    )
    human_writable: set[UUID] = (
        set(
            await db.scalars(
                select(MemoryItem.id).where(
                    MemoryItem.id.in_([item.id for item in items]),
                    human_document_clause(user_id, write=True),
                )
            )
        )
        if user_id is not None
        else set()
    )
    entries: list[DocumentLibraryEntry] = []
    for item in items:
        readable_agent_ids, writable_agent_ids = await managed_item_agent_ids(
            item,
            managed_agent_ids,
            team_access=team_access.get(item.id, {}),
        )
        human_access = MemoryAccess(
            can_read=item.id in human_readable, can_write=item.id in human_writable
        )
        if not readable_agent_ids and not human_access.can_read:
            continue
        entries.append(
            DocumentLibraryEntry(
                position=positions.get(item.id, 0),
                tags=personal_tags.get(item.id, []),
                owner_label=owner_labels.get(item.id, ""),
                item=item_to_public(
                    item,
                    MemoryAccess(
                        can_read=True,
                        can_write=bool(writable_agent_ids) or human_access.can_write,
                    ),
                ),
                user_access=human_access,
                agent_ids=list(readable_agent_ids),
                writable_agent_ids=list(writable_agent_ids),
            )
        )

    keyword_query = (
        select(func.jsonb_array_elements_text(MemoryItem.keywords).label("keyword"))
        .where(
            scope_clause,
            MemoryItem.node_kind == "document",
            or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
            or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
        )
        .subquery()
    )
    keyword_value = func.trim(keyword_query.c.keyword)
    keyword_rows = await db.scalars(select(keyword_value).where(keyword_value != "").distinct())
    keywords = sorted(keyword_rows.all(), key=str.casefold)
    return DocumentLibraryPage(
        owners=owner_options,
        query=normalized,
        entries=entries,
        keywords=keywords,
        total=total,
        has_more=has_more,
    )
