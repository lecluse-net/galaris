"""Provider-neutral managed runtime sources, kept in one canonical module."""

from pathlib import Path


def managed_runtime_files() -> dict[str, str]:
    return {name: Path(__file__).with_name(name).read_text(encoding="utf-8")
            for name in ("runtime_support.py", "runtime_web.py")}
