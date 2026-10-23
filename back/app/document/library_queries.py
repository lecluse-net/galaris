"""Read-only Memory lists and document-library projections with bounded history loading."""

from .models import Document
from collections.abc import Collection
from datetime import datetime, timezone
from typing import cast
from uuid import UUID
from pydantic import TypeAdapter
from sqlalchemy import Select, Text, case, false, func, literal, or_, select, true, union_all
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import defer, joinedload, load_only, raiseload, selectinload
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect
from core.database import get_db
from core.user import UserModel, get_user_record
from app.agent import Agent
from .access import human_document_clause, document_team_agent_access
from .access import readable_item_for_agents_clause, readable_item_clause, managed_item_agent_ids
from .contracts import DocumentAccess
from .models import DocumentListPosition, DocumentNesting, DocumentTag, DocumentTagAssignment, DocumentURL
from .document_library_filters import library_filters
from .schemas import (
    DocumentLibraryRequest,
    DocumentLibraryPage,
    DocumentLibraryEntry,
    DocumentOwnerOption,
    DocumentOwnerOptions,
    DocumentTagPublic,
)
from .item_projection import item_to_public
from .query_policy import prepare_document_read


async def list_document_keywords(agent_id: int) -> list[str]:
    """List distinct keywords from documents readable by one agent."""

    now = datetime.now(timezone.utc)
    result = await get_db().scalars(
        select(Document.keywords).where(
            readable_item_clause(agent_id),
            Document.node_kind == "document",
            Document.document_type == "html",
            or_(Document.valid_from.is_(None), Document.valid_from <= now),
            or_(Document.valid_until.is_(None), Document.valid_until > now),
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
    current_user: UserModel | None = None,
) -> DocumentOwnerOptions:
    """Return owner choices without leaking users outside the caller's scope."""

    normalized = search.strip().casefold()
    # The shared picker paginates each type locally. Do not truncate its catalogue,
    # otherwise later owners silently disappear from both browsing and search.
    agent_query = select(Agent.id, Agent.first_name, Agent.last_name, Agent.code,
        Agent.avatar.is_not(None).label("has_avatar")).order_by(Agent.id)
    if managed_agent_ids is not None:
        agent_query = agent_query.where(Agent.id.in_(managed_agent_ids))
    agents = await get_db().execute(agent_query)
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
                has_avatar=agent.has_avatar,
            )
        )

    if include_all_users:
        users = list(await get_db().scalars(select(UserModel).options(load_only(
            UserModel.id, UserModel.display_name, UserModel.email, UserModel.is_active,
            UserModel.avatar_key, UserModel.avatar_mime_type, raiseload=True,
        )).where(UserModel.is_active.is_(True)).order_by(UserModel.id)))
    else:
        if current_user is None or current_user.id != current_user_id:
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

    # Counts and personal classification can cross PostgreSQL's JIT threshold
    # even for small libraries. Keep compilation out of this interactive read,
    # just as for Memory search and graph queries; all live ACLs still apply.
    await prepare_document_read()
    db = get_db()
    now = datetime.now(timezone.utc)
    scope_clause = readable_item_for_agents_clause(managed_agent_ids)
    if user_id is not None:
        scope_clause = or_(scope_clause, human_document_clause(user_id))
    base_filters: list[ColumnElement[bool]] = [
        scope_clause,
        Document.node_kind == "document",
        Document.document_type == "html",
        or_(Document.valid_from.is_(None), Document.valid_from <= now),
        or_(Document.valid_until.is_(None), Document.valid_until > now),
    ]
    # Count, classification, facets and page metadata share one live ACL scan
    # in the same statement, including when the requested page has no rows.
    visible_documents = (
        select(Document.id).where(*base_filters).correlate(None)
        .cte("library_visible_documents").prefix_with("MATERIALIZED")
    )
    visible_ids = select(visible_documents.c.id)
    base_filters = [Document.id.in_(visible_ids)]
    base_filters.extend(await library_filters(request, user_id, visible_ids))
    keyword = request.keyword.strip() if request.keyword is not None else ""
    if keyword:
        base_filters.append(Document.keywords.contains([keyword]))
    normalized = request.query.strip()
    if normalized:
        ts_query = func.websearch_to_tsquery("simple", normalized)
        base_filters.append(
            or_(
                Document.search_vector.op("@@")(ts_query),
                Document.title.ilike(f"%{normalized}%"),
                Document.search_text.ilike(f"%{normalized}%"),
            )
        )

    filtered_documents = select(Document.id).where(*base_filters).cte("library_filtered_documents").prefix_with("MATERIALIZED")
    summary = select(
        select(func.count()).select_from(filtered_documents).scalar_subquery().label("total"),
        (_library_owner_query(visible_ids, user_id) if request.include_owners else literal(None, Text)).label("owners"),
        (_library_keyword_query(visible_ids) if request.include_keywords else literal(None, Text)).label("keywords"),
    ).cte("library_summary").prefix_with("MATERIALIZED")
    position = func.coalesce(
        (
            select(DocumentNesting.position).where(
                DocumentNesting.user_id == user_id,
                DocumentNesting.document_id == Document.id,
                DocumentNesting.parent_document_id == request.parent_document_id,
            ).scalar_subquery()
            if request.parent_document_id is not None
            else select(DocumentTagAssignment.position)
            .where(
                DocumentTagAssignment.document_id == Document.id,
                DocumentTagAssignment.tag_id == request.tag_id,
            )
            .scalar_subquery()
            if request.tag_id is not None
            else select(DocumentListPosition.position)
            .where(
                DocumentListPosition.document_id == Document.id,
                DocumentListPosition.user_id == user_id,
            )
            .scalar_subquery()
        ),
        0,
    )
    sort_column = {
        "position": position,
        "title": func.lower(Document.title),
        "document_type": Document.document_type,
        "created_at": Document.created_at,
        "updated_at": func.coalesce(Document.updated_at, Document.created_at),
    }[request.sort_by]
    page = select(
        Document.id, position.label("position"), sort_column.label("sort_value"),
        func.lower(Document.title).label("sort_title"),
    ).where(Document.id.in_(select(filtered_documents.c.id))).order_by(
        sort_column.desc() if request.sort_desc else sort_column.asc(),
        func.lower(Document.title), Document.id,
    ).offset(request.offset).limit(request.limit).cte("library_page")
    parent = select(DocumentNesting.parent_document_id).where(
        DocumentNesting.user_id == user_id, DocumentNesting.document_id == Document.id,
        DocumentNesting.parent_document_id.in_(visible_ids),
    ).correlate(Document).scalar_subquery()
    children = select(func.count()).select_from(DocumentNesting).where(
        DocumentNesting.user_id == user_id, DocumentNesting.parent_document_id == Document.id,
        DocumentNesting.document_id.in_(visible_ids),
    ).correlate(Document).scalar_subquery()
    # Evaluate these once per page document, before URL/tag joins can multiply
    # rows. Never load content or revisions to build the navigation list.
    details = select(
        page,
        parent.label("parent_document_id"), children.label("children_count"),
        (_library_tag_query(user_id) if user_id is not None else literal(None, Text)).label("tags"),
        (human_document_clause(user_id) if user_id is not None else false()).label("human_readable"),
        (human_document_clause(user_id, write=True) if user_id is not None else false()).label("human_writable"),
    ).join(Document, Document.id == page.c.id).cte("library_page_details").prefix_with("MATERIALIZED")
    first_row = func.row_number().over() == 1
    first_document_row = func.row_number().over(partition_by=Document.id) == 1
    result = await db.execute(
        select(
            Document,
            details.c.position, details.c.parent_document_id, details.c.children_count,
            details.c.human_readable, details.c.human_writable, summary.c.total,
            first_row.label("is_summary"),
            # Send potentially large filter catalogues once, rather than once
            # per document. Text keeps ORM row deduplication hashable.
            case((first_row, summary.c.owners)).label("owners"),
            case((first_row, summary.c.keywords)).label("keywords"),
            case((first_document_row, details.c.tags)).label("tags"),
            select(func.jsonb_agg(DocumentURL.url).cast(Text)).where(DocumentURL.document_id == Document.id).correlate(Document).scalar_subquery().label("urls"),
            case((first_row, select(func.jsonb_agg(Agent.id).cast(Text)).where(Agent.deleted_at.is_(None)).correlate(None).scalar_subquery())).label("available_agents"),
            case(
                (
                    Document.owner_agent_id.is_not(None),
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
        .select_from(summary)
        .outerjoin(details, true())
        .outerjoin(Document, Document.id == details.c.id)
        .outerjoin(Agent, Document.owner_agent_id == Agent.id)
        .outerjoin(UserModel, Document.owner_user_id == UserModel.id)
        .options(
            # The summary must survive even when there is no page document.
            joinedload(Document.share, innerjoin=False),
            selectinload(Document.grants),
            raiseload(Document.url_relations),
            raiseload(Document.revisions),
            defer(Document.content),
            defer(Document.summary_content),
        )
        .order_by(
            details.c.sort_value.desc() if request.sort_desc else details.c.sort_value.asc(),
            details.c.sort_title, details.c.id,
        )
        .execution_options(populate_existing=True)
    )
    rows = result.unique().all()
    summary_row = next(row for row in rows if row.is_summary)
    available_agents = TypeAdapter(list[int]).validate_json(cast(str | None, summary_row.available_agents) or "[]")
    page_agent_ids = tuple(available_agents) if managed_agent_ids is None else tuple(managed_agent_ids)
    total = cast(int, summary_row.total)
    owner_options = TypeAdapter(list[DocumentOwnerOption]).validate_json(cast(str | None, summary_row.owners) or "[]")
    for option in owner_options:
        option.is_current_user = option.kind == "user" and option.id == user_id
    owner_options.sort(key=lambda option: (option.label.casefold(), option.kind, option.id))
    keywords = TypeAdapter(list[str]).validate_json(cast(str | None, summary_row.keywords) or "[]")
    keywords.sort(key=str.casefold)
    items: dict[UUID, Document] = {}
    owner_labels: dict[UUID, str] = {}
    positions: dict[UUID, int] = {}
    personal_tags: dict[UUID, list[DocumentTagPublic]] = {}
    document_urls: dict[UUID, list[str]] = {}
    parents: dict[UUID, UUID] = {}
    child_counts: dict[UUID, int] = {}
    human_readable: set[UUID] = set()
    human_writable: set[UUID] = set()
    tag_adapter = TypeAdapter(list[DocumentTagPublic])
    for row in rows:
        item = cast(Document | None, row[0])
        if item is None:
            continue
        items[item.id] = item
        document_urls[item.id] = TypeAdapter(list[str]).validate_json(cast(str | None, row.urls) or "[]")
        owner_labels[item.id] = cast(str, row.owner_label)
        positions[item.id] = cast(int, row.position)
        if row.parent_document_id is not None:
            parents[item.id] = cast(UUID, row.parent_document_id)
        child_counts[item.id] = cast(int, row.children_count)
        if row.human_readable:
            human_readable.add(item.id)
        if row.human_writable:
            human_writable.add(item.id)
        if row.tags is not None:
            personal_tags[item.id] = tag_adapter.validate_json(cast(str, row.tags))
    has_more = request.offset + len(items) < total
    team_access = await document_team_agent_access(list(items)) if items else {}
    entries: list[DocumentLibraryEntry] = []
    for item in items.values():
        readable_agent_ids, writable_agent_ids = await managed_item_agent_ids(
            item,
            page_agent_ids,
            team_access=team_access.get(item.id, {}),
        )
        human_access = DocumentAccess(
            can_read=item.id in human_readable, can_write=item.id in human_writable
        )
        if not readable_agent_ids and not human_access.can_read:
            continue
        entries.append(
            DocumentLibraryEntry(
                parent_document_id=parents.get(item.id),
                children_count=child_counts.get(item.id, 0),
                position=positions.get(item.id, 0),
                tags=personal_tags.get(item.id, []),
                owner_label=owner_labels.get(item.id, ""),
                item=item_to_public(
                    item,
                    DocumentAccess(
                        can_read=True,
                        can_write=bool(writable_agent_ids) or human_access.can_write,
                    ),
                    urls=document_urls[item.id],
                ),
                user_access=human_access,
                agent_ids=list(readable_agent_ids),
                writable_agent_ids=list(writable_agent_ids),
            )
        )

    return DocumentLibraryPage(
        owners=owner_options,
        query=normalized,
        entries=entries,
        keywords=keywords,
        total=total,
        has_more=has_more,
    )


def _library_tag_query(user_id: int) -> ScalarSelect[str]:
    # Aggregate before joining URLs: a document with N tags and M locations
    # must not produce N * M copies of its metadata.
    value = func.jsonb_build_object(
        "id", DocumentTag.id, "name", DocumentTag.name, "parent_id", DocumentTag.parent_id,
        "icon", DocumentTag.icon, "position", DocumentTag.position, "memory_item_id", DocumentTag.memory_item_id,
    )
    return select(func.jsonb_agg(aggregate_order_by(value, func.lower(DocumentTag.name), DocumentTag.id)).cast(Text)).select_from(
        DocumentTagAssignment,
    ).join(DocumentTag).where(
        DocumentTagAssignment.document_id == Document.id, DocumentTag.user_id == user_id,
    ).correlate(Document).scalar_subquery()


def _library_owner_query(visible_ids: Select[tuple[UUID]], user_id: int | None) -> ScalarSelect[str]:
    agents = select(
        literal("agent").label("kind"), Agent.id,
        func.coalesce(func.nullif(func.trim(func.concat(Agent.first_name, " ", Agent.last_name)), ""), Agent.code).label("label"),
        literal(None, Text).label("avatar_url"), Agent.avatar.is_not(None).label("has_avatar"),
    ).join(Document, Document.owner_agent_id == Agent.id).where(Document.id.in_(visible_ids)).distinct().correlate(None)
    users = select(
        literal("user").label("kind"), UserModel.id,
        func.coalesce(func.nullif(UserModel.display_name, ""), UserModel.email).label("label"),
        case((UserModel.avatar_key.is_not(None) & UserModel.avatar_mime_type.is_not(None),
            func.concat("/api/auth/avatars/", UserModel.avatar_key)), else_=None).label("avatar_url"),
        literal(False).label("has_avatar"),
    ).where(or_(
        UserModel.id.in_(select(Document.owner_user_id).where(Document.id.in_(visible_ids))),
        UserModel.id == user_id,
    )).correlate(None)
    owners = union_all(agents, users).subquery("library_owners")
    return select(func.jsonb_agg(func.jsonb_build_object(
        "kind", owners.c.kind, "id", owners.c.id, "label", owners.c.label, "subtitle", "",
        "avatar_url", owners.c.avatar_url, "has_avatar", owners.c.has_avatar,
    )).cast(Text)).scalar_subquery()


def _library_keyword_query(visible_ids: Select[tuple[UUID]]) -> ScalarSelect[str]:
    keyword_query = (
        select(func.jsonb_array_elements_text(Document.keywords).label("keyword"))
        .where(Document.id.in_(visible_ids)).correlate(None)
        .subquery()
    )
    keyword_value = func.trim(keyword_query.c.keyword)
    return select(func.jsonb_agg(keyword_value.distinct()).cast(Text)).where(keyword_value != "").scalar_subquery()
