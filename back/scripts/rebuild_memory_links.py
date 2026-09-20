"""Reconcile every derived Memory link globally or around one node."""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from loguru import logger

from core.database import get_db_session, load_models


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--item-id", type=UUID)
    parser.add_argument("--without-suggestions", action="store_true")
    return parser.parse_args()


async def main() -> None:
    load_models()
    from app.memory.link_reconciliation import (
        MemoryLinkFamily,
        reconcile_memory_links,
    )

    arguments = _arguments()
    families: frozenset[MemoryLinkFamily] | None = (
        frozenset({"canonical"}) if arguments.without_suggestions else None
    )
    async with get_db_session():
        result = await reconcile_memory_links(
            item_id=arguments.item_id,
            families=families,
        )
    logger.success("Memory links reconciled: {}", result.model_dump())


if __name__ == "__main__":
    asyncio.run(main())
