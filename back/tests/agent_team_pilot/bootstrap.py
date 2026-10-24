"""Seed once, then restart only the same disposable pilot without resetting it."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .evidence import digest, write_json
from .seed import main as seed_main, require_isolated_database


def bootstrap(directory: Path, storage: Path, run_id: str, config: dict, seed: Callable[[], None]) -> None:
    if not run_id:
        raise ValueError("A unique pilot run identity is required")
    marker = storage / "team-pilot-bootstrap.json"
    manifest_path = directory / "manifest.json"
    expected = {"run_id": run_id, "configuration_sha256": digest(config)}
    resumed = marker.exists()
    if resumed:
        previous = json.loads(marker.read_text())
        if any(previous.get(key) != value for key, value in expected.items()):
            raise RuntimeError("Restart identity or configuration differs from the seeded pilot")
        if not manifest_path.exists() or previous.get("manifest_sha256") != digest(json.loads(manifest_path.read_text())):
            raise RuntimeError("Restart requires the original immutable pilot manifest")
    else:
        if manifest_path.exists():
            raise RuntimeError("Incomplete or foreign pilot bootstrap; do not reseed an existing run")
        seed()
        write_json(marker, {**expected, "manifest_sha256": digest(json.loads(manifest_path.read_text()))})
    with (directory / "boots.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"run_id": run_id, "seeded": not resumed,
            "started_at": datetime.now(timezone.utc).isoformat()}) + "\n")


def main() -> None:
    from core.settings import settings
    require_isolated_database(settings.APP_ENV, settings.POSTGRES_HOST, settings.POSTGRES_DB)
    bootstrap(Path("/artifacts"), Path("/data"), os.environ.get("TEAM_PILOT_RUN_ID", ""),
              json.loads(Path("/run/pilot/config.json").read_text()), seed_main)


if __name__ == "__main__":
    main()
