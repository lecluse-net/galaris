"""Read-only collections over shared personal folders, with live source ACLs."""

from uuid import UUID
import re

from sqlalchemy import and_, exists, false, func, literal, or_, select, true, union_all
from sqlalchemy.sql.elements import ColumnElement

from app.agent import sharing_principals, sharing_owner_teams
from app.share import sharing_permission_clause
from core.database import get_db
from core.user import HumanActor, UserModel

from .access import human_item_clause, readable_item_clause
from .models import Document, DocumentNesting, DocumentTag, DocumentTagAssignment


def folder_uri(identity: UUID | None = None) -> str:
    return "document://folders/" + (f"{identity}/" if identity else "")


async def scope_collection_contains(collection: str, target: str, actor: int) -> bool:
    """Check current placement and read access; mutations still enforce native write ACLs."""
    folder_match = re.fullmatch(r"document://folders/([0-9a-fA-F-]{36})/?", collection)
    target_match = re.fullmatch(r"(document|data)://([0-9a-fA-F-]{36})", target)
    if folder_match is None or target_match is None:
        return False
    try:
        folder_identity, document_identity = UUID(folder_match[1]), UUID(target_match[2])
    except ValueError:
        return False
    try:
        folder = await require_folder(folder_identity, actor)
    except FileNotFoundError:
        return False
    branch = select(DocumentTag.id).where(DocumentTag.id == folder_identity,
        DocumentTag.deleted_at.is_(None)).cte("scope_folder_branch", recursive=True)
    branch = branch.union(select(DocumentTag.id).join(branch, DocumentTag.parent_id == branch.c.id).where(
        DocumentTag.user_id == folder.user_id, DocumentTag.deleted_at.is_(None)))
    members = select(DocumentTagAssignment.document_id.label("id")).where(
        DocumentTagAssignment.tag_id.in_(select(branch.c.id))).cte("scope_folder_members", recursive=True)
    members = members.union(select(DocumentNesting.document_id).join(members,
        DocumentNesting.parent_document_id == members.c.id).where(DocumentNesting.user_id == folder.user_id))
    return bool(await get_db().scalar(select(exists(select(Document.id).where(
        Document.id == document_identity, Document.id.in_(select(members.c.id)),
        Document.deleted_at.is_(None), readable_item_clause(actor),
        Document.document_type.in_(("data",) if target_match[1] == "data" else ("text", "data")),
    )))))


def readable_folder_clause(actor: int | HumanActor) -> ColumnElement[bool]:
    owner = DocumentTag.user_id == actor.user_id if isinstance(actor, HumanActor) else false()
    active = exists(select(UserModel.id).where(UserModel.id == actor.user_id,
        UserModel.is_active.is_(True))) if isinstance(actor, HumanActor) else true()
    return and_(active, or_(owner, sharing_permission_clause(DocumentTag.share_id,
        sharing_principals(actor), sharing_owner_teams(None, DocumentTag.user_id))))


async def require_folder(identity: UUID, actor: int | HumanActor) -> DocumentTag:
    folder = await get_db().scalar(select(DocumentTag).where(DocumentTag.id == identity,
        DocumentTag.deleted_at.is_(None), readable_folder_clause(actor)).execution_options(populate_existing=True))
    if folder is None:
        raise FileNotFoundError("Folder unavailable")
    return folder


async def describe_folder(identity: UUID | None, actor: int | HumanActor) -> dict[str, object]:
    folder = await require_folder(identity, actor) if identity else None
    return dict(uri=folder_uri(identity), name=folder.name if folder else "Folders", is_collection=True,
        media_type="inode/directory", size=None, capabilities=["info", "list", "read"] if folder else ["info", "list"],
        metadata={"document_folder": True, "icon": folder.icon if folder else None,
            **({"offset_unit": "item", "read_page_size": 200} if folder else {})})


async def list_folder(identity: UUID | None, actor: int | HumanActor, *,
    limit: int = 50, offset: int = 0, query: str = "") -> dict[str, object]:
    """List subfolders and readable documents throughout the selected branch.

    The directory root discovers every authorized folder, including one whose
    private ancestors cannot be disclosed. Counts and pages follow source ACLs.
    """
    if not 1 <= limit <= 500 or offset < 0:
        raise ValueError("Invalid folder pagination")
    folder = await require_folder(identity, actor) if identity else None
    folder_query = select(DocumentTag.id.label("id"), DocumentTag.name.label("name"),
        DocumentTag.icon.label("icon"), literal(True).label("is_collection"),
        literal("inode/directory").label("media_type")).where(
        DocumentTag.deleted_at.is_(None), readable_folder_clause(actor))
    if folder is not None:
        folder_query = folder_query.where(DocumentTag.parent_id == identity, DocumentTag.user_id == folder.user_id)
    if query.strip():
        pattern = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        folder_query = folder_query.where(DocumentTag.name.ilike(pattern, escape="\\"))
    else:
        pattern = "%"
    if folder is not None:
        branch = select(DocumentTag.id).where(DocumentTag.id == identity,
            DocumentTag.deleted_at.is_(None)).cte("folder_branch", recursive=True)
        branch = branch.union(select(DocumentTag.id).join(branch, DocumentTag.parent_id == branch.c.id).where(
            DocumentTag.user_id == folder.user_id, DocumentTag.deleted_at.is_(None)))
        documents = select(DocumentTagAssignment.document_id.label("id")).where(
            DocumentTagAssignment.tag_id.in_(select(branch.c.id))).cte("folder_documents", recursive=True)
        documents = documents.union(select(DocumentNesting.document_id).join(documents,
            DocumentNesting.parent_document_id == documents.c.id).where(DocumentNesting.user_id == folder.user_id))
        acl = human_item_clause(actor.user_id) if isinstance(actor, HumanActor) else readable_item_clause(actor)
        document_query = select(Document.id.label("id"), Document.title.label("name"),
            literal(None).label("icon"), literal(False).label("is_collection"), Document.media_type).where(
            Document.id.in_(select(documents.c.id)), Document.deleted_at.is_(None),
            Document.document_type == "html", acl, Document.title.ilike(pattern, escape="\\"))
        entries = union_all(folder_query, document_query).subquery()
    else:
        entries = folder_query.subquery()
    db = get_db()
    total = int(await db.scalar(select(func.count()).select_from(entries)) or 0)
    rows = (await db.execute(select(entries).order_by(entries.c.is_collection.desc(),
        func.lower(entries.c.name), entries.c.id).offset(offset).limit(limit))).mappings().all()
    values: list[dict[str, object]] = []
    for row in rows:
        collection = bool(row["is_collection"])
        values.append(dict(uri=folder_uri(row["id"]) if collection else f"document://{row['id']}",
            name=row["name"], is_collection=collection, media_type=row["media_type"], size=None,
            capabilities=["info", "list", "read"] if collection else ["info", "read", "copy"],
            metadata={"document_folder": True, "icon": row["icon"], "offset_unit": "item", "read_page_size": 200} if collection else {}))
    more = offset + len(values) < total
    return dict(uri=folder_uri(identity), entries=values, total=total, truncated=more,
        next_cursor=str(offset + len(values)) if more else None)
