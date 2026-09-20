"""Isolated calendar calculation entrypoint, executed by file path."""

import json
import resource
import sys
import importlib
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
            result = parser.events_between(content, start, end)
        else:
            result = parser.due_actions(
                content,
                start,
                end,
                trigger_on_start=sys.argv[4] == "1",
                trigger_on_alarm=sys.argv[5] == "1",
            )
        sys.stdout.write(json.dumps([asdict(item) for item in result], default=str))
    except ValueError, MemoryError:
        sys.exit(2)


if __name__ == "__main__":
    main()
