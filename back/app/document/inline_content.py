"""Native text and preservation references owned by Documents."""
from collections.abc import Collection
from sqlalchemy import select, union
from core.database import get_db
from core.storage import register_resource_content
from .models import Document, DocumentRevision, DocumentSummaryRevision

async def read_inline_content(pointer: str) -> bytes | None:
    try:
        db=get_db()
    except RuntimeError:
        return None
    for row in (*db.new,*db.dirty):
        if isinstance(row,(Document,DocumentRevision,DocumentSummaryRevision)):
            state=row.__dict__
            if state.get("provider_code")=="native" and state.get("resource_id")==pointer and isinstance(state.get("content"),str):
                return str(state["content"]).encode()
            if isinstance(row,Document) and state.get("summary_provider_code")=="native" and state.get("summary_resource_id")==pointer and isinstance(state.get("summary_content"),str):
                return str(state["summary_content"]).encode()
    with db.no_autoflush:
        for model in (Document,DocumentRevision,DocumentSummaryRevision):
            value=await db.scalar(select(model.content).where(model.provider_code=="native",model.resource_id==pointer).execution_options(include_historized=True))
            if value is not None:
                return value.encode()
        value=await db.scalar(select(Document.summary_content).where(Document.summary_provider_code=="native",Document.summary_resource_id==pointer).execution_options(include_historized=True))
        return value.encode() if value is not None else None

async def resource_referenced(provider: str, pointer: str) -> bool:
    return pointer in await referenced_resources(provider, (pointer,))


async def referenced_resources(provider: str, pointers: Collection[str]) -> set[str]:
    db = get_db()
    referenced = set(await db.scalars(union(
        *(select(model.resource_id).where(model.provider_code==provider,model.resource_id.in_(pointers))
            for model in (Document, DocumentRevision, DocumentSummaryRevision)),
        select(Document.summary_resource_id).where(Document.summary_provider_code==provider,Document.summary_resource_id.in_(pointers)),
    ).execution_options(include_historized=True)))
    from .document_backup import archived_resources
    referenced.update(await archived_resources(db,provider,list(pointers)))
    from .independence import preserved_resources
    referenced.update(await preserved_resources(db,provider,pointers))
    return referenced

def register_content() -> None:
    register_resource_content("document",read_inline_content,resource_referenced,referenced_batch=referenced_resources)
