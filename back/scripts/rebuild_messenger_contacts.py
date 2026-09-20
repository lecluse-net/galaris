"""Rebuild private social-memory projections from the Messenger journal."""

from __future__ import annotations

import asyncio

from loguru import logger

from core.database import get_db_session, load_models


async def main() -> None:
    load_models()
    from app.messenger.contact_memory import rebuild_messenger_contacts

    async with get_db_session():
        result = await rebuild_messenger_contacts()
    logger.info("Messenger-contact rebuild: {}", result.model_dump())
    if result.failures:
        raise RuntimeError(
            "Messenger-contact rebuild failed for: "
            + ", ".join(result.failures)
        )
    logger.success(
        "Messenger-contact rebuild complete: rows={} contacts={} "
        "ai_senders={} invalid_senders={}",
        result.rows_scanned,
        result.contacts_synced,
        result.ai_senders_skipped,
        result.invalid_senders_skipped,
    )


if __name__ == "__main__":
    asyncio.run(main())
