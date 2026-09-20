"""Bounded, replayable editorial conversion owned by DbAdmin.

Sources and immutable revisions are never rewritten. Unsupported legacy images
remain explicit exceptions, keeping the action deferred until repaired.
"""

from __future__ import annotations

from hashlib import sha256

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from core.util import RichTextError, convert_legacy_to_html, visible_text

from .models import MemoryItem
from .service import _revision_for  # pyright: ignore[reportPrivateUsage]
from .semantic_index import semantic_fingerprint
from .storage import get_storage


def needs_html_conversion(transitions: SchemaTransitionSet) -> bool:
    return transitions.column_added("memory_items", "content_profile_version")


def _pending() -> tuple[ColumnElement[bool], ...]:
    return (
        MemoryItem.content_type == "text",
        MemoryItem.media_type.in_(("text/markdown", "text/plain", "text/html")),
        MemoryItem.content_profile_version.is_(None),
    )


async def html_conversion_complete(
    session: AsyncSession, _transitions: SchemaTransitionSet
) -> bool:
    count = await session.scalar(select(func.count()).select_from(MemoryItem).where(*_pending()))
    return int(count or 0) == 0


async def convert_html_batch(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    items = (
        await session.scalars(
            select(MemoryItem)
            .where(*_pending())
            .order_by(MemoryItem.id)
            .limit(500)
            .with_for_update(skip_locked=True)
        )
    ).all()
    converted, exceptions = 0, 0
    for item in items:
        provider = get_storage(item.provider_code)
        source = await provider.read(item.resource_id)
        try:
            html, warnings = convert_legacy_to_html(
                source.decode("utf-8"), item.media_type, profile=item.content_profile
            )
            if warnings:
                item.metadata_ = {**item.metadata_, "html_conversion_warnings": list(warnings)}
                logger.warning(
                    "Editorial conversion retained invalid links as text: memory={} count={}",
                    item.id,
                    len(warnings),
                )
        except (RichTextError, UnicodeError) as exc:
            exceptions += 1
            logger.warning(
                "Editorial conversion requires review: memory={} format={} reason={}",
                item.id,
                item.media_type,
                str(exc),
            )
            continue
        content = html.encode("utf-8")
        # The prior revision remains the rollback source. A distinct new immutable
        # resource guarantees that old readers and historical views retain it.
        item.resource_id = await provider.create(content)
        item.content_hash = sha256(content).hexdigest()
        item.size_bytes = len(content)
        item.search_text = visible_text(html)
        item.media_type = "text/html"
        item.content_profile_version = 1
        item.revision += 1
        item.semantic_fingerprint = semantic_fingerprint(item)
        session.add(
            _revision_for(
                item,
                author_agent_id=None,
                document_content_version=item.node_kind == "document",
            )
        )
        converted += 1
    await session.flush()
    logger.info(
        "Editorial HTML conversion batch: scanned={} converted={} exceptions={}",
        len(items),
        converted,
        exceptions,
    )


def register_html_conversion(registry: DbAdminRegistry) -> None:
    registry.register_action(
        DbAdminAction(
            key="app.memory.editorial_html",
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="editorial-html-profile-1-preserve-sources",
            predicate=needs_html_conversion,
            handler=convert_html_batch,
            postcondition=html_conversion_complete,
        )
    )


async def rebuild_html_text(session: AsyncSession) -> None:
    """Rebuild the versioned text projection in bounded reads, without new revisions."""
    while True:
        rows = (
            await session.scalars(
                select(MemoryItem)
                .where(
                    MemoryItem.content_type == "text",
                    MemoryItem.media_type == "text/html",
                    MemoryItem.content_profile_version == 1,
                    MemoryItem.metadata_["html_text_version"].as_integer().is_distinct_from(1),
                )
                .order_by(MemoryItem.id)
                .limit(250)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not rows:
            return
        for item in rows:
            body = await get_storage(item.provider_code).read(item.resource_id)
            item.search_text = visible_text(body.decode("utf-8"))
            item.semantic_fingerprint = semantic_fingerprint(item)
            item.metadata_ = {**item.metadata_, "html_text_version": 1}
        await session.flush()


async def preview_conversion(session: AsyncSession, *, limit: int = 500) -> dict[str, object]:
    """Read-only inventory and deterministic conversion sample, without model calls."""
    groups = (
        await session.execute(
            select(MemoryItem.memory_type, MemoryItem.media_type, func.count()).group_by(
                MemoryItem.memory_type, MemoryItem.media_type
            )
        )
    ).all()
    pending = int(
        await session.scalar(select(func.count()).select_from(MemoryItem).where(*_pending())) or 0
    )
    rows = (
        await session.scalars(
            select(MemoryItem)
            .where(*_pending())
            .order_by(MemoryItem.id)
            .limit(max(1, min(limit, 500)))
        )
    ).all()
    exceptions: list[dict[str, str]] = []
    warnings: list[dict[str, object]] = []
    for row in rows:
        try:
            source = await get_storage(row.provider_code).read(row.resource_id)
            _, notices = convert_legacy_to_html(
                source.decode("utf-8"), row.media_type, profile=row.content_profile
            )
            if notices:
                warnings.append({"item": str(row.id), "warnings": list(notices)})
        except (RichTextError, UnicodeError) as exc:
            exceptions.append({"item": str(row.id), "reason": str(exc)})
    return {
        "inventory": [
            {"memory_type": kind, "media_type": media, "count": count}
            for kind, media, count in groups
        ],
        "pending": pending,
        "sampled": len(rows),
        "exceptions": exceptions,
        "warnings": warnings,
    }


if __name__ == "__main__":
    import asyncio
    import json
    from core.database import get_db_session, load_models

    async def audit() -> None:
        load_models()
        async with get_db_session() as session:
            logger.info(
                "Editorial conversion audit: {}",
                json.dumps(await preview_conversion(session), ensure_ascii=False),
            )

    asyncio.run(audit())
