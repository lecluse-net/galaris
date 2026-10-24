"""Persist service stderr/stdout with credential redaction, including failed preparation."""

import json
import sys
from pathlib import Path

from .evidence import redact


def main() -> None:
    directory = Path("/artifacts")
    secrets = ["isolated-team-pilot-only", "isolated-team-pilot-encryption-key-0001"]
    session_path = directory / "_session.json"
    if session_path.exists():
        secrets.append(json.loads(session_path.read_text())["password"])
    key = Path("/run/pilot/api-key")
    if key.is_file():
        secrets.append(key.read_text().strip())
    with (directory / "services.log").open("w", encoding="utf-8") as output:
        for line in sys.stdin:
            output.write(redact(line, tuple(secrets)))


if __name__ == "__main__":
    main()
