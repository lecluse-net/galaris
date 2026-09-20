"""Preview native orphan files, or apply a reviewed inventory while writers are stopped."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from core.database import get_db_session
from core.database.model_loader import load_models
from app.memory.storage_reconciliation import OrphanCandidate, preview_native_orphans, remove_reviewed_orphans


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--after", default="")
    parser.add_argument("--apply", type=Path)
    parser.add_argument("--quiescent", action="store_true")
    args = parser.parse_args()
    load_models()
    async with get_db_session():
        if args.apply:
            payload = json.loads(args.apply.read_text())
            candidates = [OrphanCandidate(**item) for item in payload["candidates"]]
            removed = await remove_reviewed_orphans(candidates, quiescent=args.quiescent)
            result = {"removed": removed}
        else:
            candidates, cursor = await preview_native_orphans(after=args.after)
            result = {"candidates": [asdict(item) for item in candidates], "next_cursor": cursor}
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
