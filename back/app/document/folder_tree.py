"""Paged hierarchy metadata; content and permissions stay with each Document."""

from hashlib import md5
from uuid import UUID

from sqlalchemy import Text, String, any_, case, cast, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import array

from core.database import get_db
from core.user import HumanActor

from .access import human_item_clause, readable_item_clause
from .folder_resources import require_folder, folder_uri, readable_folder_clause
from .models import Document, DocumentNesting, DocumentTag, DocumentTagAssignment

TREE_PAGE_SIZE = 200


async def read_folder_tree(identity: UUID, actor: int | HumanActor, *, offset: int = 0) -> dict[str, object]:
    """Return at most 200 visible placements, in stable depth-first order.

    SQL filters before counting and pagination. Unreadable ancestors never appear
    in the result: their readable descendants attach to the nearest visible one.
    Placement keys distinguish the same Document classified in several folders.
    """
    if offset < 0:
        raise ValueError("Folder tree offset must be non-negative")
    folder = await require_folder(identity, actor)
    uri = folder_uri(identity)
    root_key = md5(uri.encode(), usedforsecurity=False).hexdigest()
    folder_reference = cast(literal("document://folders/") + cast(DocumentTag.id, String) + "/", Text)
    document_reference = cast(literal("document://") + cast(Document.id, String), Text)
    parent_folder_reference = cast(literal("document://folders/") + cast(DocumentTag.parent_id, String) + "/", Text)
    parent_document_reference = cast(literal("document://") + cast(DocumentNesting.parent_document_id, String), Text)
    acl = human_item_clause(actor.user_id) if isinstance(actor, HumanActor) else readable_item_clause(actor)

    folder_edges = select(folder_reference.label("uri"), parent_folder_reference.label("parent_uri"),
        cast(DocumentTag.name, Text).label("name"), cast(literal("folder"), Text).label("kind"),
        DocumentTag.position.label("position"), readable_folder_clause(actor).label("visible")).where(
        DocumentTag.user_id == folder.user_id, DocumentTag.deleted_at.is_(None))
    assigned_edges = select(document_reference.label("uri"), folder_reference.label("parent_uri"),
        cast(Document.title, Text).label("name"), cast(literal("document"), Text).label("kind"),
        DocumentTagAssignment.position.label("position"), acl.label("visible")).select_from(DocumentTagAssignment).join(
        Document, Document.id == DocumentTagAssignment.document_id).join(
        DocumentTag, DocumentTag.id == DocumentTagAssignment.tag_id).where(
        DocumentTag.user_id == folder.user_id, DocumentTag.deleted_at.is_(None),
        Document.deleted_at.is_(None), Document.document_type == "html")
    nested_edges = select(document_reference.label("uri"), parent_document_reference.label("parent_uri"),
        cast(Document.title, Text).label("name"), cast(literal("document"), Text).label("kind"),
        DocumentNesting.position.label("position"), acl.label("visible")).select_from(DocumentNesting).join(
        Document, Document.id == DocumentNesting.document_id).where(DocumentNesting.user_id == folder.user_id,
        Document.deleted_at.is_(None), Document.document_type == "html")
    edges = union_all(folder_edges, assigned_edges, nested_edges).cte("folder_tree_edges")
    tree = select(cast(literal(uri), Text).label("uri"), cast(literal(folder.name), Text).label("name"),
        cast(literal("folder"), Text).label("kind"), literal(True).label("visible"),
        cast(literal(root_key), Text).label("key"), cast(literal(None), Text).label("parent_key"),
        cast(literal(None), Text).label("parent_uri"),
        array([cast(literal(uri), Text)]).label("visited"),
        array([cast(literal(""), Text)]).label("sort_path")).cte("folder_tree", recursive=True)
    order_key = (cast(func.lpad(cast(edges.c.position, String), 20, "0"), Text)
        + ":" + func.lower(edges.c.name) + ":" + edges.c.kind + ":" + edges.c.uri)
    tree = tree.union_all(select(edges.c.uri, edges.c.name, edges.c.kind, edges.c.visible,
        cast(func.md5(tree.c.key + "\n" + edges.c.uri), Text),
        case((tree.c.visible, tree.c.key), else_=tree.c.parent_key),
        case((tree.c.visible, tree.c.uri), else_=tree.c.parent_uri),
        tree.c.visited + array([edges.c.uri]), tree.c.sort_path + array([order_key]),
    ).select_from(tree).join(edges, edges.c.parent_uri == tree.c.uri).where(~(edges.c.uri == any_(tree.c.visited))))
    visible = select(tree.c.uri, tree.c.name, tree.c.kind, tree.c.key, tree.c.parent_key,
        tree.c.parent_uri, tree.c.sort_path).where(tree.c.visible, tree.c.key != root_key).cte("visible_folder_tree")
    db = get_db()
    rows = (await db.execute(select(visible, func.count().over().label("total")).order_by(
        visible.c.sort_path).offset(offset).limit(TREE_PAGE_SIZE))).mappings().all()
    total = int(rows[0]["total"]) if rows else int(await db.scalar(select(func.count()).select_from(visible)) or 0)
    children: dict[str, list[dict[str, object]]] = {root_key: []}
    nodes: dict[str, dict[str, object]] = {}
    for row in rows:
        key = str(row["key"])
        children[key] = []
        nodes[key] = dict(key=key, uri=row["uri"], name=row["name"], kind=row["kind"],
            parent_key=row["parent_key"], parent_uri=row["parent_uri"], children=children[key])
    continuations: dict[str, dict[str, object]] = {}
    for row in rows:
        key, parent_key = str(row["key"]), str(row["parent_key"])
        if parent_key not in children:
            children[parent_key] = []
            continuations[parent_key] = dict(parent_key=parent_key, parent_uri=row["parent_uri"],
                children=children[parent_key])
        children[parent_key].append(nodes[key])
    start = min(offset, total)
    end = start + len(rows)
    # Recheck collection access before publishing the hierarchy assembled above.
    await require_folder(identity, actor)
    return dict(key=root_key, uri=uri, name=folder.name, kind="folder", children=children[root_key],
        continuations=list(continuations.values()), pagination=dict(offset=start, limit=TREE_PAGE_SIZE,
            returned=len(rows), total=total, next_offset=end if end < total else None))
