"""Isolated calendar calculation entrypoint, executed by file path."""

import json
import resource
import sys
import importlib
import traceback
from pathlib import Path
from typing import Any
from dataclasses import asdict
from datetime import datetime


def main() -> None:
    # Apply before importing the parser. This child never imports app bootstrap.
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    parser: Any = importlib.import_module("ical")

    content = sys.stdin.buffer.read(5 * 1024 * 1024 + 1)
    start, end = datetime.fromisoformat(sys.argv[2]), datetime.fromisoformat(sys.argv[3])
    try:
        if sys.argv[1] == "events":
            result = parser.events_between(content, start, end, sys.argv[4] if len(sys.argv) > 4 else "UTC",
                compact=len(sys.argv) > 5 and sys.argv[5] == "compact")
        else:
            result = parser.due_actions(
                content,
                start,
                end,
            )
        sys.stdout.write(json.dumps([asdict(item) for item in result], default=str))
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        location = f"{Path(frames[-1].filename).name}:{frames[-1].lineno}:{frames[-1].name}" if frames else "worker"
        sys.stdout.write(json.dumps({"error_category": type(exc).__name__, "error_location": location}))
        sys.exit(2)


if __name__ == "__main__":
    main()
