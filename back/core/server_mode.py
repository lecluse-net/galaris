"""Validate the explicitly supported single-worker application topology."""

from collections.abc import Sequence


def validate_worker_count(arguments: Sequence[str]) -> None:
    if not arguments or arguments[0] != "uvicorn":
        return
    for index, argument in enumerate(arguments[1:], start=1):
        if argument.startswith("--workers="):
            workers = argument.partition("=")[2]
        elif argument == "--workers" and index + 1 < len(arguments):
            workers = arguments[index + 1]
        else:
            continue
        if workers != "1":
            raise ValueError(
                "Galaris supports one Uvicorn worker per instance: parameter caches, "
                "realtime connections and runtime listeners are process-local. Use --workers 1."
            )


if __name__ == "__main__":
    import sys

    validate_worker_count(sys.argv[1:])
