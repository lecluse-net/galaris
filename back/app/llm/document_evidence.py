"""Read acquired document evidence without preparing bytes or starting inference."""

from collections.abc import Sequence
from typing import Any, cast as type_cast
from uuid import UUID

from sqlalchemy import Select, String, cast, func, literal, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db
from .document_contracts import AcquiredDocumentEvidence
from .models import LLMDocumentAnalysis


def document_evidence_revision(
    task_ids: Select[tuple[UUID]], file_ids: Select[tuple[UUID]], agent_id: ColumnElement[int]
) -> ColumnElement[str]:
    """A correlated revision for completed evidence in a consumer's owned work."""
    row = LLMDocumentAnalysis
    value = func.concat(row.id, ":", row.updated_at)
    return (
        select(func.coalesce(func.string_agg(value, aggregate_order_by(literal("|"), row.id)), ""))
        .where(
            row.task_id.in_(task_ids),
            row.status == "success",
            row.agent_id == agent_id,
            func.regexp_replace(row.input["uri"].astext, "^.*/", "").in_(
                select(cast(file_ids.subquery().c.file_id, String))
            ),
        )
        .scalar_subquery()
    )


async def acquired_document_evidence(
    agent_id: int,
    task_ids: Sequence[UUID],
    uris: Sequence[str],
    *,
    analysis_ids: Sequence[UUID] | None = None,
) -> list[AcquiredDocumentEvidence]:
    """Only results linked by both work and source URI; recheck current access.

    Unknown provider versions remain explicitly unknown. They are never presented
    as proof that today's bytes are identical to those previously analysed.
    """
    from app.file_share import ResourceContext, resource_info

    if not task_ids or not uris:
        return []
    rows = await get_db().scalars(
        select(LLMDocumentAnalysis)
        .where(
            LLMDocumentAnalysis.agent_id == agent_id,
            LLMDocumentAnalysis.task_id.in_(task_ids),
            LLMDocumentAnalysis.input["uri"].astext.in_(uris),
            LLMDocumentAnalysis.status == "success",
            *((LLMDocumentAnalysis.id.in_(analysis_ids),) if analysis_ids is not None else ()),
        )
        .order_by(LLMDocumentAnalysis.created_at.desc(), LLMDocumentAnalysis.id)
        .limit(len(analysis_ids) if analysis_ids is not None else 16)
        .execution_options(populate_existing=True)
    )
    results: list[AcquiredDocumentEvidence] = []
    for row in rows:
        uri = str(row.input["uri"])
        runtime = str(row.input.get("runtime") or "internal")
        try:
            descriptor = await resource_info(
                ResourceContext(agent_id=agent_id, runtime=runtime, task_id=row.task_id), uri
            )
        except PermissionError, FileNotFoundError, ValueError:
            continue
        version: dict[str, Any] = dict(row.input.get("source_version") or {})
        current = descriptor.model_dump(
            include={"revision", "etag", "checksum", "modified_at", "size"}, exclude_none=True
        )
        if version and version != current:
            continue
        output = row.output or {}
        raw_passages = row.checkpoint.get("source_passages")
        passages: list[dict[str, Any]] = (
            [
                type_cast(dict[str, Any], value)
                for value in type_cast(list[object], raw_passages)
                if isinstance(value, dict)
            ]
            if isinstance(raw_passages, list)
            else []
        )
        results.append(
            AcquiredDocumentEvidence(
                analysis_id=row.id,
                uri=uri,
                version={
                    **version,
                    "sha256": output.get("source_sha256"),
                    "analysis_ref": str(row.id),
                    "task_ref": str(row.task_id),
                    "attestation": "provider_version"
                    if any(
                        key in version for key in ("revision", "etag", "checksum", "modified_at")
                    )
                    else "unknown",
                },
                coverage={
                    **dict(output.get("coverage") or {}),
                    "complete": bool(output.get("complete")),
                    "semantic_accuracy_verified": bool(output.get("semantic_accuracy_verified")),
                    "extracted_text_truncated": bool(
                        row.checkpoint.get("source_passages_truncated")
                    ),
                },
                passages=passages,
                answer=str(output.get("answer") or ""),
            )
        )
    return results


def document_evidence_access_clause(
    part: ColumnElement[Any], agent_id: ColumnElement[int]
) -> ColumnElement[bool]:
    """Local immutable analysis identity; remote access is rechecked at admission."""
    from sqlalchemy import exists

    row = LLMDocumentAnalysis
    return exists(
        select(row.id)
        .where(
            row.agent_id == agent_id,
            row.status == "success",
            cast(row.id, String) == part["version"]["analysis_ref"].astext,
            cast(row.task_id, String) == part["version"]["task_ref"].astext,
            row.input["uri"].astext == part["uri"].astext,
        )
        .correlate_except(row)
    )
