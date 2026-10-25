"""Prepare controller-only tokens and candidate requests before executing any run."""

import json
import secrets
import sys
from pathlib import Path
from typing import Any

from .corpus import save, source_hash


root, private = (Path(value) for value in sys.argv[1:3])
credentials = json.loads((private / "config.json").read_text())
manifest = json.loads((root / "manifest.json").read_text())
manifest["model"] = {key: credentials[key] for key in ("code", "model", "upstream")}
manifest["images"] = dict(backend=sys.argv[3], hermes=sys.argv[4])
manifest["source_revision"] = sys.argv[5]
manifest["experiment_source_sha256"] = source_hash()
if manifest["phase"] == "decision":
    pilots: list[str] = []
    for candidate in root.parent.glob("*-pilot-*/summary.json"):
        summary = json.loads(candidate.read_text())
        frozen = json.loads((candidate.parent / "manifest.json").read_text())
        if (
            summary.get("complete")
            and summary.get("measurement_valid")
            and not summary.get("safety_regression")
            and all(arm["passed"] == arm["runs"] for arm in summary["arms"].values())
            and all(
                frozen.get(key) == manifest[key]
                for key in ("model", "images", "corpus_sha256", "experiment_source_sha256")
            )
        ):
            pilots.append(candidate.parent.name)
    if not pilots:
        raise ValueError("Run a successful matching pilot before freezing a decision campaign")
    manifest["qualified_pilot"] = sorted(pilots)[-1]
save(root / "manifest.json", manifest)
controls: dict[str, str] = {}
for run in manifest["runs"]:
    token = secrets.token_hex(24)
    controls[run["id"]] = token
    request: dict[str, Any] = {
        **run,
        "token": token,
        "limits": manifest["limits"],
        "model": credentials["model"],
    }
    save(private / "requests" / (run["id"] + ".json"), request)
save(private / "tokens.json", controls)
(private / "runs.tsv").write_text(
    "".join(r["id"] + "\t" + r["arm"] + "\n" for r in manifest["runs"])
)
