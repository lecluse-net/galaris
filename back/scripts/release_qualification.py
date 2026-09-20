"""Bind local qualification evidence to immutable images and the upgrade source."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def image_ids(directory: Path) -> dict[str, str]:
    return {tag: digest for digest, tag in (line.split() for line in (directory / "IMAGE_IDS").read_text().splitlines())}


def validate_upgrade(directory: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = json.loads((directory / "UPGRADE_QUALIFICATION.json").read_text())
    candidates = [digest for tag, digest in image_ids(directory).items() if tag.startswith("galaris-release-back:")]
    if len(candidates) != 1 or evidence.get("candidate_image") != candidates[0]:
        raise ValueError("Upgrade evidence does not match the candidate backend")
    if not evidence.get("previous_image", "").startswith("sha256:"):
        raise ValueError("Upgrade evidence requires the previous immutable image")
    if evidence.get("convergence") != "passed" or evidence.get("restoration") != "passed":
        raise ValueError("Upgrade and coordinated restoration must both have passed")
    if not evidence.get("tests_commit") or not evidence.get("tests_sha256"):
        raise ValueError("Upgrade test provenance is missing")
    return evidence


def validate_promotion(directory: Path, installed: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", (directory / "SOURCE_COMMIT").read_text().strip()) is None:
        raise ValueError("A working-tree qualification is not a committed release")
    upgrade = validate_upgrade(directory)
    qualification = json.loads((directory / "QUALIFICATION.json").read_text())
    if qualification.get("images") != image_ids(directory):
        raise ValueError("Qualification belongs to different images")
    digest = hashlib.sha256((directory / "UPGRADE_QUALIFICATION.json").read_bytes()).hexdigest()
    if qualification.get("upgrade_sha256") != digest:
        raise ValueError("Upgrade evidence changed after qualification")
    if installed and installed not in {upgrade["previous_image"], upgrade["candidate_image"]}:
        raise ValueError("Installed backend differs from the qualified previous image; rehearse this upgrade first")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("record-upgrade", "check-upgrade", "qualify", "promote"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--previous", default="")
    parser.add_argument("--candidate", default="")
    parser.add_argument("--tests-commit", default="")
    parser.add_argument("--tests-sha256", default="")
    parser.add_argument("--installed", default="")
    args = parser.parse_args()
    directory: Path = args.directory
    if args.mode == "record-upgrade":
        evidence = {
            "version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "previous_image": args.previous, "candidate_image": args.candidate,
            "tests_commit": args.tests_commit, "tests_sha256": args.tests_sha256,
            "convergence": "passed", "restoration": "passed",
            "dataset": "restore_probe synthetic nonempty fixture; not a production-volume qualification",
            "backup": "quiescent coordinated database/files/keys", "external_harnesses": "not exercised",
        }
        (directory / "UPGRADE_QUALIFICATION.json").write_text(json.dumps(evidence, indent=2) + "\n")
        validate_upgrade(directory)
        for marker in ("QUALIFICATION.json", "TESTED_IMAGE_IDS"):
            (directory / marker).unlink(missing_ok=True)
        checksums: list[str] = []
        for name in ("SOURCE_COMMIT", "IMAGE_IDS", "compose.release.yaml", "images.tar.gz", "MANAGED_HARNESSES", "UPGRADE_QUALIFICATION.json"):
            with (directory / name).open("rb") as source:
                checksums.append(f"{hashlib.file_digest(source, 'sha256').hexdigest()}  {name}\n")
        (directory / "SHA256SUMS").write_text("".join(checksums))
    elif args.mode == "promote":
        validate_promotion(directory, args.installed)
    else:
        validate_upgrade(directory)
        if args.mode == "qualify":
            evidence = {
                "version": 1, "images": image_ids(directory),
                "tests_commit": args.tests_commit, "tests_sha256": args.tests_sha256,
                "upgrade_sha256": hashlib.sha256((directory / "UPGRADE_QUALIFICATION.json").read_bytes()).hexdigest(),
                "browser_workflows": "passed", "image_checks": "passed",
                "managed_harnesses": (directory / "MANAGED_HARNESSES").read_text(),
            }
            (directory / "QUALIFICATION.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
