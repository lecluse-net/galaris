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


_REFRESH_TIMEOUT_SECONDS = 120


async def _refresh(expected_revision: str | None) -> dict[str, object]:
    # Keep database dependencies lazy: check/revision also run in the offline image.
    from sqlalchemy.exc import DBAPIError

    from core.database import get_db_session

    async with asyncio.timeout(_REFRESH_TIMEOUT_SECONDS):
        corpus = await asyncio.to_thread(load_corpus)
        while True:
            try:
                async with get_db_session():
                    result = await refresh_and_check(corpus, expected_revision=expected_revision)
                    # A source edit while checking must not produce a successful readiness report.
                    check_corpus(await asyncio.to_thread(load_corpus), expected_revision=result.content_revision)
                return asdict(result)
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) not in {"55P03", "40P01"}:
                    raise
                # A background embedding batch or another refresh may still own
                # the inserted fingerprints. The failed transaction has rolled
                # back; retry the complete readiness check in a fresh session.
                # All attempts and waits share the original deployment deadline.
                sys.stderr.write("Documentation index is locked by another transaction; retrying...\n")
                await asyncio.sleep(0.5)


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
    except TimeoutError:
        sys.stderr.write(f"Documentation check failed: refresh exceeded {_REFRESH_TIMEOUT_SECONDS} seconds.\n")
        return 1
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(f"Documentation check failed: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
