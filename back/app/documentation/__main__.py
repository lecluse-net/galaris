"""Container CLI used by documentation preparation and deployment gates."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .corpus import load_corpus
from .readiness import check_corpus, refresh_and_check


async def _refresh(expected_revision: str | None) -> dict[str, object]:
    from core.database import get_db_session

    async with asyncio.timeout(120):
        corpus = await asyncio.to_thread(load_corpus)
        async with get_db_session():
            result = await refresh_and_check(corpus, expected_revision=expected_revision)
            # A source edit while checking must not produce a successful readiness report.
            check_corpus(await asyncio.to_thread(load_corpus), expected_revision=result.content_revision)
        return asdict(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "revision", "refresh"))
    parser.add_argument("--root", type=Path, help="Source tree for offline checks only")
    parser.add_argument("--expected-revision", help="Expected documentation content fingerprint")
    args = parser.parse_args()
    if args.command == "refresh" and args.root is not None:
        parser.error("refresh always checks the running container's corpus; --root is not allowed")
    try:
        if args.command == "refresh":
            report = asyncio.run(_refresh(args.expected_revision))
        else:
            corpus = load_corpus(root=args.root)
            revision = check_corpus(corpus, expected_revision=args.expected_revision)
            if args.command == "revision":
                sys.stdout.write(revision + "\n")
                return 0
            report = {"content_revision": revision, "pages": len(corpus.pages), "passages": len(corpus.passages)}
        sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
        return 0
    except (FileNotFoundError, ValueError, TimeoutError) as exc:
        sys.stderr.write(f"Documentation check failed: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
