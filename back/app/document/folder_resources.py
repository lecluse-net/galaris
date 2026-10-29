"""Read-only collections over shared personal folders, with live source ACLs."""

from uuid import UUID
import re

from sqlalchemy import and_, exists, false, func, literal, or_, select, true, union_all
from sqlalchemy.sql.elements import ColumnElement

from app.agent import sharing_principals, sharing_owner_teams
from app.share import sharing_permission_clause
from core.database import get_db
from core.user import HumanActor, UserModel

from .access import human_item_clause, readable_item_clause, writable_item_clause
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
        Document.document_type.in_(("data",) if target_match[1] == "data" else ("html", "text", "data")),
    )))))


def navigable_folder_clause(actor: int | HumanActor) -> ColumnElement[bool]:
    """A user's placement is discoverable when it leads to a readable Document.

    Walk upward from authorized documents, including personal document nesting,
    without granting access to any other document in the same directories.
    UNION bounds traversal even if legacy placement data contains a cycle.
    """
    acl = human_item_clause(actor.user_id) if isinstance(actor, HumanActor) else readable_item_clause(actor)
    assigned = select(Document.id.label("id"), DocumentTag.user_id).join(
        DocumentTagAssignment, DocumentTagAssignment.document_id == Document.id).join(
        DocumentTag, DocumentTag.id == DocumentTagAssignment.tag_id).where(
        Document.deleted_at.is_(None), Document.document_type == "html",
        DocumentTag.deleted_at.is_(None), acl)
    nested = select(Document.id.label("id"), DocumentNesting.user_id).join(
        DocumentNesting, DocumentNesting.document_id == Document.id).where(Document.deleted_at.is_(None),
            Document.document_type == "html", acl)
    seeds = assigned.union(nested).subquery()
    documents = select(seeds.c.id, seeds.c.user_id).cte(recursive=True)
    documents = documents.union(select(DocumentNesting.parent_document_id, DocumentNesting.user_id).join(
        documents, and_(DocumentNesting.document_id == documents.c.id,
            DocumentNesting.user_id == documents.c.user_id)))
    folders = select(DocumentTag.id, DocumentTag.parent_id, DocumentTag.user_id).join(
        DocumentTagAssignment, DocumentTagAssignment.tag_id == DocumentTag.id).join(documents,
        and_(documents.c.id == DocumentTagAssignment.document_id, documents.c.user_id == DocumentTag.user_id)
    ).where(DocumentTag.deleted_at.is_(None)).cte(recursive=True)
    folders = folders.union(select(DocumentTag.id, DocumentTag.parent_id, DocumentTag.user_id).join(
        folders, and_(DocumentTag.id == folders.c.parent_id, DocumentTag.user_id == folders.c.user_id)
    ).where(DocumentTag.deleted_at.is_(None)))
    return DocumentTag.id.in_(select(folders.c.id))


def readable_folder_clause(actor: int | HumanActor) -> ColumnElement[bool]:
    owner = DocumentTag.user_id == actor.user_id if isinstance(actor, HumanActor) else false()
    active = exists(select(UserModel.id).where(UserModel.id == actor.user_id,
        UserModel.is_active.is_(True))) if isinstance(actor, HumanActor) else true()
    return and_(active, or_(owner, navigable_folder_clause(actor), sharing_permission_clause(DocumentTag.share_id,
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
    limit: int = 50, offset: int = 0, query: str = "", navigation: bool = False) -> dict[str, object]:
    """List subfolders and readable documents throughout the selected branch.

    Navigation lists a single directory level and unfiled documents at its root.
    Collection discovery and branch search retain their exhaustive projections.
    Counts and pages follow source ACLs.
    """
    if not 1 <= limit <= 500 or offset < 0:
        raise ValueError("Invalid folder pagination")
    folder = await require_folder(identity, actor) if identity else None
    folder_acl = navigable_folder_clause(actor) if navigation else readable_folder_clause(actor)
    folder_query = select(DocumentTag.id.label("id"), DocumentTag.name.label("name"),
        DocumentTag.icon.label("icon"), literal(True).label("is_collection"),
        literal("inode/directory").label("media_type"), literal("folder").label("document_type"),
        literal(False).label("can_write"), literal(None).label("size"), literal(None).label("revision"),
        literal(None).label("checksum"), literal(None).label("updated_at"), literal(None).label("temporal")).where(
        DocumentTag.deleted_at.is_(None), folder_acl)
    if folder is not None:
        folder_query = folder_query.where(DocumentTag.parent_id == identity, DocumentTag.user_id == folder.user_id)
    elif navigation:
        # A missing or deleted parent must not strand an otherwise visible folder.
        parents = select(DocumentTag.id).where(DocumentTag.deleted_at.is_(None),
            folder_acl).subquery()
        visible_parent = exists(select(parents.c.id).where(parents.c.id == DocumentTag.parent_id))
        folder_query = folder_query.where(~visible_parent)
    if query.strip():
        pattern = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        folder_query = folder_query.where(DocumentTag.name.ilike(pattern, escape="\\"))
    else:
        pattern = "%"
    if folder is not None or navigation:
        branch = select(DocumentTag.id, DocumentTag.user_id).where(DocumentTag.deleted_at.is_(None))
        branch = branch.where(DocumentTag.id == identity) if folder else branch.where(folder_acl)
        locations = branch.cte("folder_branch", recursive=True)
        if not navigation:
            locations = locations.union(select(DocumentTag.id, DocumentTag.user_id).join(
                locations, DocumentTag.parent_id == locations.c.id).where(
                    DocumentTag.user_id == locations.c.user_id, DocumentTag.deleted_at.is_(None)))
        documents = select(DocumentTagAssignment.document_id.label("id"), locations.c.user_id).join(
            locations, DocumentTagAssignment.tag_id == locations.c.id).cte("folder_documents", recursive=True)
        documents = documents.union(select(DocumentNesting.document_id, documents.c.user_id).join(documents,
            DocumentNesting.parent_document_id == documents.c.id).where(DocumentNesting.user_id == documents.c.user_id))
        acl = human_item_clause(actor.user_id) if isinstance(actor, HumanActor) else readable_item_clause(actor)
        write_acl = human_item_clause(actor.user_id, write=True) if isinstance(actor, HumanActor) else writable_item_clause(actor)
        membership = Document.id.in_(select(documents.c.id))
        document_query = select(Document.id.label("id"), Document.title.label("name"),
            literal(None).label("icon"), literal(False).label("is_collection"), Document.media_type,
            Document.document_type, write_acl.label("can_write"), Document.size_bytes.label("size"),
            Document.revision, Document.content_hash.label("checksum"), Document.updated_at, Document.temporal).where(
            membership if folder else ~membership, Document.deleted_at.is_(None),
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
        scheme = "data" if navigation and row["document_type"] == "data" else "document"
        capabilities = ["info", "read", "copy"]
        if navigation:
            capabilities.append("search")
            if row["can_write"]:
                capabilities.extend(["write", "append", "edit"])
        values.append(dict(uri=folder_uri(row["id"]) if collection else f"{scheme}://{row['id']}",
            name=row["name"], is_collection=collection, media_type=row["media_type"], size=row["size"],
            **({"revision": row["revision"], "checksum": row["checksum"],
                "modified_at": row["updated_at"].isoformat() if row["updated_at"] is not None else None}
                if navigation and not collection else {}),
            capabilities=["info", "list", "read"] if collection else capabilities,
            metadata={"document_folder": True, "icon": row["icon"], "offset_unit": "item", "read_page_size": 200} if collection
                else {"document_type": row["document_type"], "temporal": row["temporal"]} if navigation else {}))
    more = offset + len(values) < total
    return dict(uri=folder_uri(identity), entries=values, total=total, truncated=more,
        **({"ancestors": await navigation_ancestors(folder, actor)} if navigation else {}),
        next_cursor=str(offset + len(values)) if more else None)


async def navigation_ancestors(folder: DocumentTag | None, actor: int | HumanActor) -> list[dict[str, object]]:
    """Readable directory lineage, independent of opaque, stable folder URIs."""
    result: list[dict[str, object]] = []
    if folder is not None:
        lineage = select(DocumentTag.id, DocumentTag.parent_id, DocumentTag.name,
            readable_folder_clause(actor).label("visible")).where(DocumentTag.id == folder.id).cte(
                "navigation_lineage", recursive=True)
        lineage = lineage.union(select(DocumentTag.id, DocumentTag.parent_id, DocumentTag.name,
            readable_folder_clause(actor)).join(lineage, DocumentTag.id == lineage.c.parent_id).where(
                DocumentTag.deleted_at.is_(None), DocumentTag.user_id == folder.user_id))
        rows = {row.id: row for row in (await get_db().execute(select(lineage))).all()}
        current: UUID | None = folder.id
        seen: set[UUID] = set()
        while current is not None and current in rows and current not in seen:
            row = rows[current]
            if not row.visible:
                break
            seen.add(current)
            result.insert(0, dict(uri=folder_uri(current), name=row.name, is_collection=True,
                media_type="inode/directory", capabilities=["info", "list", "read"]))
            current = row.parent_id
    return [dict(uri="document://", name="Documents", is_collection=True,
        media_type="inode/directory", capabilities=["info", "list"]), *result]
