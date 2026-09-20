"""Check incident-to-test links against actual JUnit and mutation results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from defusedxml.ElementTree import parse

from pydantic import BaseModel, Field, TypeAdapter


class Regression(BaseModel):
    id: str = Field(min_length=1)
    guarantee: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    test: str = Field(min_length=1)
    mutation: str = Field(min_length=1)


def check(manifest: Path, junit: Path, mutations: Path) -> dict[str, object]:
    entries = TypeAdapter(list[Regression]).validate_json(manifest.read_text())
    if not entries or len({entry.id for entry in entries}) != len(entries):
        raise ValueError("Regression evidence needs unique, nonempty identities")
    root = parse(junit).getroot()
    assert root is not None
    cases = root.findall(".//testcase")
    passed = {row.attrib.get("classname", "").replace(".", "/") + ".py::" + row.attrib["name"]
              for row in cases if not any(row.find(tag) is not None for tag in ("failure", "error", "skipped"))}
    report = json.loads(mutations.read_text())
    detected = {row["name"] for row in report["mutations"] if row["detected"] is True}
    if len(detected) != report["expected"]:
        raise ValueError("The mutation campaign is incomplete")
    missing = [entry.id for entry in entries if entry.test not in passed or entry.mutation not in detected]
    if missing:
        raise ValueError("Regression evidence missing: " + ", ".join(missing))
    return {"linked_regressions": len(entries), "mutations_detected": len(detected),
            "tests": len(cases), "failed": sum(row.find("failure") is not None or row.find("error") is not None for row in cases),
            "skipped": sum(row.find("skipped") is not None for row in cases),
            "test_seconds": sum(float(row.get("time", "0")) for row in cases)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("/repo/project/regressions.json"))
    parser.add_argument("--junit", type=Path, default=Path("/repo/artifacts/backend-junit.xml"))
    parser.add_argument("--mutations", type=Path, default=Path("/repo/artifacts/mutations.json"))
    parser.add_argument("--output", type=Path, default=Path("/repo/artifacts/regression-evidence.json"))
    args = parser.parse_args()
    result = check(args.manifest, args.junit, args.mutations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if result["failed"]:
        raise SystemExit("Backend failures remain; linked regression tests alone do not qualify the suite")


if __name__ == "__main__":
    main()
