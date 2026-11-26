"""Read-only Memory lists and document-library projections with bounded history loading."""

from .models import Document
from collections.abc import Collection
from datetime import datetime, timezone
from itertools import chain
from typing import cast
from uuid import UUID
from pydantic import TypeAdapter
from sqlalchemy import BigInteger, Select, Text, case, false, func, literal, or_, select, true, union_all
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import defer, joinedload, load_only, raiseload
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect
from core.database import get_db
from core.user import UserModel, get_user_record
from app.agent import Agent
from app.share import ShareGrant
from .access import human_document_clause, page_agent_access, readable_item_for_agents_clause, readable_item_clause, team_agent_rights
from .contracts import DocumentAccess
from .models import DocumentListPosition, DocumentNesting, DocumentTag, DocumentTagAssignment, DocumentURL
from .document_library_filters import library_filters
from .schemas import (
    DocumentGrantPublic,
    DocumentLibraryRequest,
    DocumentLibraryPage,
    DocumentLibraryEntry,
    DocumentLibraryRange,
    DocumentOwnerOption,
    DocumentOwnerOptions,
    DocumentTagPublic,
)
from .item_projection import item_to_public
from .query_policy import prepare_document_read

_string_list = TypeAdapter(list[str])
_agent_ids = TypeAdapter(list[int])
_owner_options = TypeAdapter(list[DocumentOwnerOption])
_tag_list = TypeAdapter(list[DocumentTagPublic])
_tree_ranges = TypeAdapter(list[DocumentLibraryRange])
_grant_list = TypeAdapter(list[DocumentGrantPublic])
_team_rights = TypeAdapter(dict[int, bool])


async def list_document_keywords(agent_id: int) -> list[str]:
    """List distinct keywords from documents readable by one agent."""

    now = datetime.now(timezone.utc)
    result = await get_db().scalars(
        select(Document.keywords).where(
            readable_item_clause(agent_id),
            Document.node_kind == "document",
            Document.document_format.not_in(("dataset", "process")),
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
        Document.document_format.not_in(("dataset", "process")),
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
    filters = await library_filters(request, user_id, visible_ids)
    keyword = request.keyword.strip() if request.keyword is not None else ""
    if keyword:
        filters.append(Document.keywords.contains([keyword]))
    normalized = request.query.strip()
    if normalized:
        ts_query = func.websearch_to_tsquery("simple", normalized)
        filters.append(
            or_(
                Document.search_vector.op("@@")(ts_query),
                Document.title.ilike(f"%{normalized}%"),
                Document.search_text.ilike(f"%{normalized}%"),
            )
        )

    filtered_documents = visible_documents
    if filters:
        filtered_documents = (select(Document.id).where(Document.id.in_(visible_ids), *filters)
                              .cte("library_filtered_documents").prefix_with("MATERIALIZED"))
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
        "document_format": Document.document_format,
        "created_at": Document.created_at,
        "updated_at": func.coalesce(Document.updated_at, Document.created_at),
    }[request.sort_by]
    tree_range_query: ScalarSelect[str] | None = None
    if request.include_tree_ranges:
        # Keep counts, endpoints and page entries on one live ACL snapshot.
        # Only the two boundary titles of each range are aggregated, at most 200.
        start = request.offset
        end = func.least(summary.c.total, start + request.tree_range_size) if request.tree_range_size else summary.c.total
        bounds = select(end.label("end"), func.power(100, func.greatest(1,
            func.ceil(func.log(100, func.greatest(end - start, 1))) - 1)).cast(BigInteger).label("size")).cte("library_range_bounds").prefix_with("MATERIALIZED")
        ranked = select(Document.title, (func.row_number().over(order_by=(
            sort_column.desc() if request.sort_desc else sort_column.asc(),
            func.lower(Document.title), Document.id,
        )) - 1).label("offset")).where(Document.id.in_(select(filtered_documents.c.id))).correlate(None).cte("library_range_titles")
        relative = ranked.c.offset - start
        offset = start + (relative // bounds.c.size) * bounds.c.size
        last = func.least(bounds.c.end, offset + bounds.c.size) - 1
        endpoints = select(offset.label("offset"), bounds.c.size,
            func.min(case((ranked.c.offset == offset, ranked.c.title))).label("first_title"),
            func.min(case((ranked.c.offset == last, ranked.c.title))).label("last_title"),
        ).select_from(ranked.join(bounds, true())).where(
            bounds.c.end - start > 100, ranked.c.offset >= start, ranked.c.offset < bounds.c.end,
            or_(relative % bounds.c.size == 0, (relative + 1) % bounds.c.size == 0, ranked.c.offset == bounds.c.end - 1),
        ).group_by(offset, bounds.c.size).subquery("library_range_endpoints")
        tree_range_query = select(func.jsonb_agg(aggregate_order_by(func.jsonb_build_object(
            "offset", endpoints.c.offset, "size", endpoints.c.size,
            "first_title", endpoints.c.first_title, "last_title", endpoints.c.last_title,
        ), endpoints.c.offset)).cast(Text)).scalar_subquery()
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
    direct_grants = select(func.jsonb_agg(aggregate_order_by(func.jsonb_build_object(
        "agent_id", ShareGrant.agent_id, "can_write", ShareGrant.can_write,
    ), ShareGrant.agent_id)).cast(Text)).where(
        ShareGrant.share_id == Document.share_id, ShareGrant.agent_id.is_not(None),
    ).correlate(Document).scalar_subquery()
    has_agent_scope = managed_agent_ids is None or bool(managed_agent_ids)
    human_readable = false()
    if user_id is not None:
        # With only a human scope, the visibility scan already proved this
        # exact permission in the same PostgreSQL snapshot.
        human_readable = human_document_clause(user_id) if has_agent_scope else true()
    detail_query = select(
        page,
        direct_grants.label("direct_grants"),
        parent.label("parent_document_id"), children.label("children_count"),
        (_library_tag_query(user_id) if user_id is not None else literal(None, Text)).label("tags"),
        human_readable.label("human_readable"),
        (human_document_clause(user_id, write=True) if user_id is not None else false()).label("human_writable"),
    ).join(Document, Document.id == page.c.id)
    if has_agent_scope:
        rights = team_agent_rights(select(page.c.id), managed_agent_ids).subquery()
        by_document = select(rights.c.item_id, func.jsonb_object_agg(
            rights.c.agent_id, rights.c.can_write,
        ).cast(Text).label("team_rights")).group_by(rights.c.item_id).subquery()
        detail_query = detail_query.outerjoin(by_document, by_document.c.item_id == Document.id)
        team_rights = by_document.c.team_rights
    else:
        team_rights = literal(None, Text)
    details = detail_query.add_columns(team_rights.label("team_rights")).cte("library_page_details").prefix_with("MATERIALIZED")
    available_agents = (select(func.jsonb_agg(Agent.id).cast(Text)).where(Agent.deleted_at.is_(None))
                        .correlate(None).scalar_subquery() if managed_agent_ids is None else literal(None, Text))
    first_row = func.row_number().over() == 1
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
            case((first_row, tree_range_query if tree_range_query is not None else literal(None, Text))).label("tree_ranges"),
            details.c.tags, details.c.direct_grants, details.c.team_rights,
            select(func.jsonb_agg(DocumentURL.url).cast(Text)).where(DocumentURL.document_id == Document.id).correlate(Document).scalar_subquery().label("urls"),
            case((first_row, available_agents)).label("available_agents"),
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
            raiseload(Document.grants),
            raiseload(Document.url_relations),
            raiseload(Document.revisions),
            defer(Document.content),
            defer(Document.summary_content),
            defer(Document.search_text),
            defer(Document.search_vector),
            defer(Document.summary_source_text),
        )
        .order_by(
            details.c.sort_value.desc() if request.sort_desc else details.c.sort_value.asc(),
            details.c.sort_title, details.c.id,
        )
        .execution_options(populate_existing=True)
    )
    rows = result.all()
    summary_row = next(row for row in rows if row.is_summary)
    page_agent_ids = frozenset(_agent_ids.validate_json(cast(str | None, summary_row.available_agents) or "[]")
                               if managed_agent_ids is None else managed_agent_ids)
    total = cast(int, summary_row.total)
    owner_options = _owner_options.validate_json(cast(str | None, summary_row.owners) or "[]")
    for option in owner_options:
        option.is_current_user = option.kind == "user" and option.id == user_id
    owner_options.sort(key=lambda option: (option.label.casefold(), option.kind, option.id))
    keywords = _string_list.validate_json(cast(str | None, summary_row.keywords) or "[]")
    keywords.sort(key=str.casefold)
    page_size = 0
    entries: list[DocumentLibraryEntry] = []
    for row in rows:
        item = cast(Document | None, row[0])
        if item is None:
            continue
        page_size += 1
        grants = _grant_list.validate_json(cast(str | None, row.direct_grants) or "[]")
        team = _team_rights.validate_json(cast(str | None, row.team_rights) or "{}")
        readable_agent_ids, writable_agent_ids = page_agent_access(
            item, page_agent_ids, chain(((g.agent_id, g.can_write) for g in grants), team.items()),
        )
        human_access = DocumentAccess(
            can_read=bool(row.human_readable), can_write=bool(row.human_writable),
        )
        if not readable_agent_ids and not human_access.can_read:
            continue
        entries.append(
            DocumentLibraryEntry(
                parent_document_id=cast(UUID | None, row.parent_document_id),
                children_count=cast(int, row.children_count),
                position=cast(int, row.position),
                tags=_tag_list.validate_json(cast(str | None, row.tags) or "[]"),
                owner_label=cast(str, row.owner_label),
                item=item_to_public(
                    item,
                    DocumentAccess(
                        can_read=True,
                        can_write=bool(writable_agent_ids) or human_access.can_write,
                    ),
                    urls=_string_list.validate_json(cast(str | None, row.urls) or "[]"),
                    grants=grants,
                ),
                user_access=human_access,
                agent_ids=list(readable_agent_ids),
                writable_agent_ids=list(writable_agent_ids),
            )
        )

    tree_ranges = _tree_ranges.validate_json(cast(str | None, summary_row.tree_ranges) or "[]")

    return DocumentLibraryPage(
        owners=owner_options,
        query=normalized,
        entries=entries,
        keywords=keywords,
        total=total,
        has_more=request.offset + page_size < total,
        tree_ranges=tree_ranges,
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
