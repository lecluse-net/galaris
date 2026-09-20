"""Queue rebuilds for the governed-memory semantic index."""

from __future__ import annotations

import argparse
import asyncio

from loguru import logger

from core.database import get_db_session, load_models


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Queue semantic memory projections for the model selected by "
            "the vector field of the current LLM profile. Existing current projections are skipped by default."
        )
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Queue every active memory even when its current projection exists.",
    )
    return parser.parse_args()


async def main() -> None:
    args = _arguments()
    load_models()
    from app.memory.semantic_index import reconcile_embedding_index

    async with get_db_session():
        result = await reconcile_embedding_index(missing_only=not args.all)
    if not result.model_configured:
        logger.warning(
            "No vector model is selected; no semantic memory jobs were queued."
        )
        return
    logger.success(
        "Semantic memory rebuild queued: model={} scanned={} queued={} current={}",
        result.model_code,
        result.scanned,
        result.queued,
        result.current,
    )


if __name__ == "__main__":
    asyncio.run(main())
