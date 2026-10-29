"""Optional native graph projection of canonical Document sources.

Document never imports this adapter. Late and repeated jobs read the current
source under its lock, and source ACLs are checked again on every graph read.
"""

import hashlib
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm.attributes import set_committed_value

from app.document import Document, DocumentTag
from core.database import get_db

from .models import MemoryAutomationJob, MemoryItem


async def enqueue(identity: UUID, action: str) -> None:
    db = get_db()
    db.add(MemoryAutomationJob(kind="document_projection",
        idempotency_key=f"document_projection:{identity}:{uuid4()}",
        payload={"identity": str(identity), "folder": action == "folder"}))
    await db.commit()


async def refresh(identity: UUID, *, folder: bool = False) -> None:
    from . import service
    from .document_structure import sync_document_structure, sync_folder_structure
    from .semantic_index import stage_embedding_refresh

    db = get_db()
    if folder:
        tag = await db.get(DocumentTag, identity)
        if tag is not None:
            await sync_folder_structure(tag.user_id)
        return
    source = await db.scalar(select(Document).where(Document.id == identity)
        .execution_options(include_historized=True).with_for_update())
    node = await db.scalar(select(MemoryItem).where(MemoryItem.id == identity)
        .execution_options(include_historized=True))
    if source is None or source.deleted_at is not None:
        await service.forget_resource_memories([f"document://{identity}"], descendants=True)
        if node is not None and node.node_kind == "document":
            await service.forget_document_reference(node, commit=False)
        return
    if node is not None and node.node_kind != "document":
        raise ValueError("Document source identity collides with a personal memory")
    if node is None:
        node = MemoryItem(id=identity, node_kind="document", owner_agent_id=source.owner_agent_id,
            owner_user_id=source.owner_user_id, memory_provider_code="native", memory_resource_id="",
            memory_content="", memory_content_hash=hashlib.sha256(b"").hexdigest(),
            memory_size_bytes=0, memory_content_type="text", memory_media_type="text/html",
            memory_content_profile_version=1, memory_read_only=True,
            search_title=source.title, search_text=source.search_text, keywords=list(source.keywords), metadata_={})
        db.add(node)
    else:
        node.owner_agent_id, node.owner_user_id = source.owner_agent_id, source.owner_user_id
        node.search_title, node.search_text = source.title, source.search_text
        node.keywords, node.temporal = list(source.keywords), source.temporal
        node.valid_from, node.valid_until = source.valid_from, source.valid_until
        node.deleted_at = None
    set_committed_value(node, "document", source)
    node.deletion_protected = source.deletion_protected
    node.metadata_ = {**node.metadata_, "document_source_revision": source.revision,
        "document_summary_hash": source.summary_content_hash}
    stage_embedding_refresh(node)
    await db.flush()
    await sync_document_structure(source)
    topic = await service.projected_topic_item_id(source.topic_id)
    if topic is not None:
        await service.ensure_topic_memory_link(topic_item_id=topic, memory_item_id=node.id)
