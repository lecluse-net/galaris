"""Typed canonical targets carried by extensible memory provenance rows."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MemorySourceTargets:
    """Canonical foreign keys represented by one source identity."""

    task_id: UUID | None = None
    conversation_round_id: UUID | None = None


def _uuid_prefix(value: str, prefix: str) -> UUID | None:
    if not value.startswith(prefix):
        return None
    raw = value.removeprefix(prefix).split(":", maxsplit=1)[0]
    try:
        return UUID(raw)
    except ValueError:
        return None


def source_targets(source_kind: str, source_ref: str) -> MemorySourceTargets:
    """Resolve typed links without weakening the open provenance vocabulary."""

    normalized_kind = source_kind.strip()
    normalized_ref = source_ref.strip()
    if normalized_kind in {"task", "task_outcome"}:
        return MemorySourceTargets(task_id=_uuid_prefix(normalized_ref, "task:"))
    if normalized_kind == "conversation_round":
        return MemorySourceTargets(
            conversation_round_id=_uuid_prefix(
                normalized_ref,
                "conversation_round:",
            )
        )
    return MemorySourceTargets()


__all__ = ["MemorySourceTargets", "source_targets"]
