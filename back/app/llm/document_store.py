"""Short transactions for private document-analysis state."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.database import get_db
from .document_contracts import DocumentAnalysisSnapshot
from .models import LLMDocumentAnalysis
from .contracts import ProtocolInferenceRequest

TERMINAL_STATUSES = frozenset({"success", "error", "cancelled", "unknown"})


async def submit_batch(analysis_id: UUID, inference_id: UUID,
                       request: ProtocolInferenceRequest, *, completed: int) -> dict[str, Any]:
    """Serialize admission with cancellation; persist the pending identity before unlocking."""
    from .facade import start_inference

    db = get_db()
    row = (await db.scalars(select(LLMDocumentAnalysis).where(
        LLMDocumentAnalysis.id == analysis_id,
    ).with_for_update().execution_options(populate_existing=True))).one()
    if (row.status not in TERMINAL_STATUSES and not row.checkpoint.get("cancelled")
            and int(row.checkpoint.get("completed_batches", 0)) == completed):
        await start_inference(request, inference_id=inference_id)
        row.checkpoint = {**row.checkpoint, "pending_inference": str(inference_id)}
    result: dict[str, Any] = {"terminal": row.status in TERMINAL_STATUSES, "metadata": dict(row.checkpoint)}
    await db.commit()
    return result


def snapshot(row: LLMDocumentAnalysis) -> DocumentAnalysisSnapshot:
    return DocumentAnalysisSnapshot.model_validate({
        "status": row.status, "output": row.output, "error": row.error,
    })


async def document_checkpoint(
    analysis_id: UUID, values: dict[str, Any] | None = None, *,
    immutable_values: dict[str, Any] | None = None,
    expected_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = get_db()
    row = (await db.scalars(select(LLMDocumentAnalysis).where(
        LLMDocumentAnalysis.id == analysis_id,
    ).with_for_update().execution_options(populate_existing=True))).one()
    terminal = row.status in TERMINAL_STATUSES
    preserved = terminal or bool(row.checkpoint.get("cancelled") and values != {"cancelled": True})
    if expected_values is not None and any(
        row.checkpoint.get(key) != value for key, value in expected_values.items()
    ):
        preserved = True
    if not preserved:
        for key, value in (immutable_values or {}).items():
            if key in row.checkpoint and row.checkpoint[key] != value:
                raise ValueError(f"The durable checkpoint field {key} cannot change")
        row.checkpoint = {**row.checkpoint, **(immutable_values or {}), **(values or {})}
        if values == {"cancelled": True}:
            row.status = "cancelling"
    result: dict[str, Any] = {
        "agent_id": row.agent_id, "task_id": row.task_id, "input": dict(row.input),
        "metadata": dict(row.checkpoint), "status": row.status, "output": row.output,
        "error": row.error, "terminal": terminal, "applied": not preserved,
    }
    await db.commit()
    return result


async def publish(analysis_id: UUID, result: DocumentAnalysisSnapshot) -> DocumentAnalysisSnapshot:
    db = get_db()
    row = (await db.scalars(select(LLMDocumentAnalysis).where(
        LLMDocumentAnalysis.id == analysis_id,
    ).with_for_update().execution_options(populate_existing=True))).one()
    if row.status not in TERMINAL_STATUSES:
        if row.checkpoint.get("cancelled") and result.status in {"queued", "running", "success"}:
            result = DocumentAnalysisSnapshot(status="cancelling", output={"complete": False})
        row.status, row.output = result.status, result.output
        row.error = result.error.model_dump() if result.error else None
        row.updated_at = datetime.now(timezone.utc)
    saved = snapshot(row)
    await db.commit()
    return saved
