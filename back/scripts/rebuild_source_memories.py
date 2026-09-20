"""Rebuild deterministic Agent, Goal, and GoalCycle memory projections."""

from __future__ import annotations

import argparse
import asyncio

from loguru import logger

from core.database import get_db_session, load_models


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build source-managed memory projections. By default only sources "
            "without a memory UUID are processed."
        )
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Refresh every projection, including sources that already have an UUID.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help=(
            "Forget and recreate every source projection with fresh UUIDs. "
            "Use this when changing resource provider."
        ),
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Resource-storage provider code used for new or recreated projections.",
    )
    return parser.parse_args()


async def main() -> None:
    args = _arguments()
    load_models()
    from app.memory.source_projection import rebuild_source_memories

    async with get_db_session():
        result = await rebuild_source_memories(
            missing_only=not args.all and not args.recreate,
            recreate=bool(args.recreate),
            provider_code=args.provider,
        )
    logger.info("Source-memory rebuild: {}", result.model_dump())
    if result.failures:
        raise RuntimeError(
            "Source-memory rebuild failed for: " + ", ".join(result.failures)
        )
    logger.success(
        "Source-memory rebuild complete: agents={} goals={} stale_cycles_removed={}",
        result.agents_synced,
        result.goals_synced,
        result.stale_cycles_removed,
    )


if __name__ == "__main__":
    asyncio.run(main())
