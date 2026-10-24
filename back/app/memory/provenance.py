"""Typed canonical targets carried by extensible memory provenance rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, literal
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement


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


def source_origin_expression(
    source_kind: InstrumentedAttribute[str], source_ref: InstrumentedAttribute[str],
    metadata: InstrumentedAttribute[dict[str, Any]] | None = None,
) -> ColumnElement[str]:
    """Group canonical source revisions/receipts without inventing corroboration.

    A late transcription and the first extraction of the same round count once.
    Task and task-outcome references also share the same origin. Unknown source
    vocabularies retain their exact identity rather than guessing equivalence.
    """
    normalized = func.regexp_replace(source_ref, r"^document_summary:", "document:")
    canonical = func.regexp_replace(normalized,
        r"^((task|conversation_round|document):[0-9a-fA-F-]{36})(:.*)?$", r"\1")
    fallback = case((source_kind.in_(("task", "task_outcome", "conversation_round", "document", "document_summary")),
                     canonical), else_=source_kind + ":" + source_ref)
    if metadata is None:
        return fallback
    # Interpretations and passages of one file remain one source, even when
    # acquired in different rounds. Mixed-source evidence stays conservative:
    # it is not split into a fabricated number of independent confirmations.
    evidence = case((func.jsonb_typeof(metadata["source_evidence"]) == "array", metadata["source_evidence"]),
                    else_=literal([], type_=JSONB))
    origin = func.jsonb_extract_path_text(evidence, "0", "uri")
    mixed = func.jsonb_path_exists(evidence,
        literal('$[*] ? (!exists(@.uri) || @.uri != $origin)', type_=JSONPATH),
        func.jsonb_build_object("origin", origin))
    return case((origin.is_not(None) & ~mixed, "resource:" + origin), else_=fallback)


__all__ = ["MemorySourceTargets", "source_targets", "source_origin_expression"]
