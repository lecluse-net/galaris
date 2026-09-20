"""Command-line surface for the only Galaris database synchronization flow."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence

from loguru import logger

from core import settings

from .contracts import DbAdminMode
from .journal import latest_summary
from .orchestrator import synchronize_database


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m core.dbadmin")
    subparsers = parser.add_subparsers(dest="command")
    synchronize = subparsers.add_parser("synchronize")
    synchronize.add_argument("--dry-run", action="store_true")
    synchronize.add_argument(
        "--mode",
        choices=tuple(mode.value for mode in DbAdminMode),
    )
    status = subparsers.add_parser("status")
    status.add_argument(
        "--latest",
        action="store_true",
        help="display the latest persisted run (the current and only status view)",
    )
    return parser


async def _run(arguments: argparse.Namespace) -> int:
    if arguments.command == "status":
        try:
            summary = await latest_summary()
        except Exception as exc:
            message = str(exc).replace("\x00", "")
            if settings.POSTGRES_PASSWORD:
                message = message.replace(settings.POSTGRES_PASSWORD, "***")
            logger.error("Could not read DbAdmin status: {}", message[-4_000:])
            return 1
        if summary is None:
            logger.warning("No DbAdmin run has been persisted yet")
            return 1
        logger.info("Latest DbAdmin summary:\n{}", json.dumps(summary, indent=2))
        return 0
    mode_value = getattr(arguments, "mode", None)
    mode = DbAdminMode(mode_value) if mode_value is not None else None
    result = await synchronize_database(
        mode=mode,
        dry_run=bool(getattr(arguments, "dry_run", False)),
    )
    return result.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command is None:
        arguments.command = "synchronize"
        arguments.dry_run = False
        arguments.mode = None
    return asyncio.run(_run(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
