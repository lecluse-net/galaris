"""Dataset-owned current summaries and guarded background maintenance."""

from uuid import UUID

from sqlalchemy import Select, func, select

from core.database import get_db
from core.params import runtime_settings
from core.util import needs_resource_summary as needs_summary, normalize_summary_source as normalize_source

from .models import Dataset


def refresh_pending(item: Dataset) -> None:
    item.summary_pending = needs_summary(normalize_source(item.content, "json"),
        summary_present=bool(item.summary_content and item.summary_content.strip()),
        generated=bool(item.summary_generated), baseline=item.summary_source_text,
        min_chars=runtime_settings.DREAM_RESOURCE_SUMMARY_MIN_CHARS,
        threshold=runtime_settings.DREAM_RESOURCE_SUMMARY_CHANGE_PERCENT)


def pending(handled: Select[tuple[str]]) -> Select[tuple[Dataset]]:
    return select(Dataset).where(Dataset.summary_pending.is_(True),
        ~func.concat(Dataset.id, ":", Dataset.lock_version).in_(handled))


async def count_pending(handled: Select[tuple[str]]) -> int:
    return int(await get_db().scalar(select(func.count()).select_from(pending(handled).subquery())) or 0)


async def claim_one(handled: Select[tuple[str]]) -> str | None:
    item = await get_db().scalar(pending(handled).order_by(Dataset.created_at, Dataset.id)
        .limit(1).with_for_update(skip_locked=True))
    return f"{item.id}:{item.lock_version}" if item else None


async def source(identity: str) -> tuple[str, str, int | None] | None:
    item = await get_db().scalar(select(Dataset).where(
        func.concat(Dataset.id, ":", Dataset.lock_version) == identity, Dataset.summary_pending.is_(True)))
    if item is None:
        return None
    refresh_pending(item)
    return (item.title, normalize_source(item.content, "json"), item.owner_agent_id) if item.summary_pending else None


async def apply(identity: str, description: str, keywords: list[str]) -> bool:
    item = await get_db().scalar(select(Dataset).where(
        func.concat(Dataset.id, ":", Dataset.lock_version) == identity,
        Dataset.summary_pending.is_(True)).with_for_update())
    if item is None:
        return False
    refresh_pending(item)
    if not item.summary_pending:
        return False
    item.summary_content = description + "\n\n" + ", ".join(keywords)
    item.keywords = keywords
    item.summary_generated = True
    item.summary_source_text = normalize_source(item.content, "json")
    item.summary_pending = False
    item.lock_version += 1
    await get_db().flush()
    from .projection import changed
    await changed(item)
    return True


async def reconcile() -> None:
    cursor: UUID | None = None
    while True:
        query = select(Dataset)
        if cursor is not None:
            query = query.where(Dataset.id > cursor)
        items = list(await get_db().scalars(query.order_by(Dataset.id).limit(100)
            .with_for_update().execution_options(populate_existing=True)))
        if not items:
            return
        for item in items:
            previous = item.summary_pending
            refresh_pending(item)
            if previous != item.summary_pending:
                item.lock_version += 1
        cursor = items[-1].id
        await get_db().flush()
