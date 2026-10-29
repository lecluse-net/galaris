"""Current Document summary eligibility and guarded Dream writes."""

from html import escape
from uuid import UUID

from sqlalchemy import Select, func, select

from core.database import get_db
from core.params import runtime_settings
from core.storage import get_storage
from core.user import HumanActor
from core.util import needs_resource_summary as needs_summary, normalize_summary_source as normalize_source

from .models import Document


async def normalized_content(item: Document, content: bytes | None = None) -> str:
    if content is None:
        content = await get_storage(item.provider_code).read(item.resource_id)
    return normalize_source(content.decode("utf-8"), "html")


async def refresh_pending(item: Document, content: bytes | None = None) -> None:
    if item.document_type != "html":
        item.summary_pending = False
        return
    item.summary_pending = needs_summary(
        await normalized_content(item, content),
        summary_present=bool(normalize_source(item.summary_content, "html")) if item.summary_content is not None else bool(item.summary_size_bytes),
        generated=bool(item.summary_generated), baseline=item.summary_source_text,
        min_chars=runtime_settings.DREAM_RESOURCE_SUMMARY_MIN_CHARS,
        threshold=runtime_settings.DREAM_RESOURCE_SUMMARY_CHANGE_PERCENT,
    )


def pending(handled: Select[tuple[str]]) -> Select[tuple[Document]]:
    return select(Document).where(Document.summary_pending.is_(True),
        Document.document_type == "html", ~func.concat(Document.id, ":", Document.lock_version).in_(handled))


async def count_pending(handled: Select[tuple[str]]) -> int:
    return int(await get_db().scalar(select(func.count()).select_from(pending(handled).subquery())) or 0)


async def claim_one(handled: Select[tuple[str]]) -> str | None:
    item = await get_db().scalar(pending(handled).order_by(Document.created_at, Document.id)
        .limit(1).with_for_update(skip_locked=True))
    return f"{item.id}:{item.lock_version}" if item else None


async def source(identity: str) -> tuple[str, str, int | None] | None:
    item = await get_db().scalar(select(Document).where(
        func.concat(Document.id, ":", Document.lock_version) == identity, Document.summary_pending.is_(True)))
    if item is None:
        return None
    await refresh_pending(item)
    if not item.summary_pending:
        return None
    return item.title, await normalized_content(item), item.owner_agent_id


async def apply(identity: str, description: str, keywords: list[str]) -> bool:
    from .resource_service import update_summary
    from .schemas import DocumentPayload, DocumentUpdate

    item = await get_db().scalar(select(Document).where(
        func.concat(Document.id, ":", Document.lock_version) == identity,
        Document.summary_pending.is_(True)).with_for_update())
    if item is None:
        return False
    await refresh_pending(item)
    if not item.summary_pending:
        return False
    baseline = await normalized_content(item)
    actor = item.owner_agent_id if item.owner_agent_id is not None else HumanActor(item.owner_user_id or 0)
    # The source lock also protects a manual summary edit while inference ran.
    html = f"<p>{escape(description)}</p><ul>" + "".join(f"<li>{escape(word)}</li>" for word in keywords) + "</ul>"
    await update_summary(item.id, DocumentUpdate(payload=DocumentPayload(text=html), keywords=keywords,
        expected_lock_version=item.lock_version), actor_agent_id=actor,
        generated=True, source_text=baseline)
    return True


async def reconcile() -> None:
    """Re-evaluate existing resources after schema or summary-policy changes."""
    cursor: UUID | None = None
    while True:
        query = select(Document).where(Document.document_type == "html")
        if cursor is not None:
            query = query.where(Document.id > cursor)
        items = list(await get_db().scalars(query.order_by(Document.id).limit(100)
            .with_for_update().execution_options(populate_existing=True)))
        if not items:
            return
        for item in items:
            await refresh_pending(item)
        cursor = items[-1].id
        await get_db().flush()
