"""Short transactions for private multimedia operations."""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from sqlalchemy import select
from core.database import get_db
from .models import MediaGeneration
from .generation_contracts import MediaGenerationSnapshot

TERMINAL_STATUSES = frozenset({"success", "error", "cancelled"})

def snapshot(row: MediaGeneration) -> MediaGenerationSnapshot:
    return MediaGenerationSnapshot.model_validate({"status": row.status, "output": row.output, "error": row.error})

async def generation_checkpoint(
    identifier: UUID, values: dict[str, Any] | None = None, *,
    claim: str | None = None, immutable_values: dict[str, Any] | None = None,
    preserve_if: dict[str, Any] | None = None,
    expected_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = get_db()
    row = (await db.scalars(select(MediaGeneration).where(MediaGeneration.id == identifier)
        .with_for_update().execution_options(populate_existing=True))).one()
    preserved = row.status in TERMINAL_STATUSES or bool(preserve_if) and any(
        row.checkpoint.get(key) == value for key, value in (preserve_if or {}).items())
    if expected_values is not None and any(
        row.checkpoint.get(key) != value for key, value in expected_values.items()):
        preserved = True
    for key, value in (immutable_values or {}).items():
        if key in row.checkpoint and row.checkpoint[key] != value:
            raise ValueError(f"The durable checkpoint field {key} cannot change")
    claimed = not preserved and claim is not None and not row.checkpoint.get(claim)
    if not preserved:
        row.checkpoint = {**row.checkpoint, **(immutable_values or {}), **(values or {}),
                         **({claim: "started"} if claimed and claim else {})}
        row.updated_at = datetime.now(timezone.utc)
    data: dict[str, Any] = {
        "agent_id": row.agent_id, "task_id": row.task_id, "input": dict(row.input),
        "metadata": dict(row.checkpoint), "terminal": row.status in TERMINAL_STATUSES,
        "status": row.status, "output": row.output, "error": row.error,
        "claimed": claimed, "applied": not preserved, "callback_token": row.callback_token,
    }
    await db.commit()
    return data

async def publish(identifier: UUID, result: MediaGenerationSnapshot) -> MediaGenerationSnapshot:
    db = get_db()
    row = (await db.scalars(select(MediaGeneration).where(MediaGeneration.id == identifier)
        .with_for_update().execution_options(populate_existing=True))).one()
    if row.status not in TERMINAL_STATUSES:
        row.status, row.output = result.status, result.output
        row.error = result.error.model_dump() if result.error else None
        row.updated_at = datetime.now(timezone.utc)
    saved = snapshot(row)
    await db.commit()
    return saved
