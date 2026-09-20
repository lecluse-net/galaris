"""Bounded private projections of canonical Process definitions and results."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select

from app.process import (
    ProcessDefinition,
    ProcessRun,
    sanitize_process_payload,
)
from core.database import get_db

from .contracts import SourceMemoryDocument
from .models import MemoryItem
from .safety import redact_secrets
from .service import (
    ensure_source_managed_link,
    forget_source_managed_item,
    upsert_source_managed_item,
)


PROCESS_RUN_PROJECTION_LIMIT = 20
PROCESS_RESULT_MAX_CHARS = 12_000


def _safe_json(value: object) -> str:
    sanitized = sanitize_process_payload(
        value,
        max_bytes=PROCESS_RESULT_MAX_CHARS,
    )
    serialized = json.dumps(
        sanitized,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    )
    redacted = redact_secrets(serialized)
    safe = redacted if redacted is not None else "[sensitive output omitted]"
    if len(safe) <= PROCESS_RESULT_MAX_CHARS:
        return safe
    return f"{safe[: PROCESS_RESULT_MAX_CHARS - 1].rstrip()}…"


async def _definition(
    definition_id: int,
    *,
    include_historized: bool = False,
) -> ProcessDefinition | None:
    query = select(ProcessDefinition).where(
        ProcessDefinition.id == definition_id
    )
    if include_historized:
        query = query.execution_options(include_historized=True)
    return await get_db().scalar(query)


async def sync_process_definition_projection(
    definition_id: int,
) -> MemoryItem | None:
    """Project an assigned procedure or remove its projection after deletion."""

    definition = await _definition(
        definition_id,
        include_historized=True,
    )
    source_ref = f"process_definition:{definition_id}"
    if (
        definition is None
        or definition.deleted_at is not None
        or definition.agent_id is None
    ):
        await forget_source_managed_item(
            source_kind="process_definition",
            source_ref=source_ref,
        )
        return None
    description = str(definition.description or "").strip()
    content = (
        f"# {definition.label.strip()}\n\n"
        "> Cette procédure Process reste pilotée par sa définition canonique.\n"
        + (f"\n## Description\n\n{description}\n" if description else "")
    )
    return await upsert_source_managed_item(
        SourceMemoryDocument(
            source_kind="process_definition",
            source_ref=source_ref,
            owner_agent_id=definition.agent_id,
            memory_item_id=None,
            title=f"Procédure · {definition.label}"[:500],
            memory_type="procedural",
            content=content,
            filename=f"process-definition-{definition.id}.md",
            keywords=(
                "process",
                "procedure",
                str(definition.id),
                definition.label,
            ),
            metadata={
                "projection_version": 1,
                "process_definition_id": definition.id,
            },
        )
    )


async def _forget_process_runs_outside_window(
    *,
    launcher_agent_id: int,
    process_id: int,
) -> None:
    keep_ids = set(
        (
            await get_db().scalars(
                select(ProcessRun.id)
                .where(
                    ProcessRun.launcher_agent_id == launcher_agent_id,
                    ProcessRun.process_id == process_id,
                    ProcessRun.status == "success",
                )
                .order_by(
                    ProcessRun.finished_at.desc().nullslast(),
                    ProcessRun.created_at.desc(),
                    ProcessRun.id.desc(),
                )
                .limit(PROCESS_RUN_PROJECTION_LIMIT)
            )
        ).all()
    )
    projected = list(
        (
            await get_db().scalars(
                select(MemoryItem)
                .where(
                    MemoryItem.source_managed.is_(True),
                    MemoryItem.owner_agent_id == launcher_agent_id,
                    MemoryItem.managed_source_kind == "process_run",
                )
                .order_by(MemoryItem.created_at)
                .limit(100)
            )
        ).all()
    )
    for item in projected:
        if int(item.metadata_.get("process_definition_id") or 0) != process_id:
            continue
        raw_run_id = str(item.metadata_.get("process_run_id") or "")
        try:
            run_id = UUID(raw_run_id)
        except ValueError:
            run_id = UUID(int=0)
        if run_id in keep_ids:
            continue
        await forget_source_managed_item(
            source_kind="process_run",
            source_ref=f"process_run:{raw_run_id}",
            item_id=item.id,
        )


async def sync_process_run_projection(run_id: UUID) -> MemoryItem | None:
    """Project only successful, sanitized terminal output in a bounded window."""

    run = await get_db().scalar(
        select(ProcessRun)
        .where(ProcessRun.id == run_id)
        .execution_options(include_historized=True)
    )
    source_ref = f"process_run:{run_id}"
    if (
        run is None
        or run.deleted_at is not None
        or run.status != "success"
        or run.output is None
    ):
        await forget_source_managed_item(
            source_kind="process_run",
            source_ref=source_ref,
        )
        return None
    definition = await _definition(run.process_id)
    label = (
        str(run.launch_snapshot.get("process_label") or "").strip()
        or (definition.label if definition is not None else f"Process {run.process_id}")
    )
    output = _safe_json(run.output)
    content = (
        f"# Résultat Process · {label}\n\n"
        "> Résultat privé issu d’une exécution canonique réussie.\n\n"
        f"Exécution : `{run.id}`\n\n"
        f"## Sortie\n\n```json\n{output}\n```\n"
    )
    item = await upsert_source_managed_item(
        SourceMemoryDocument(
            source_kind="process_run",
            source_ref=source_ref,
            owner_agent_id=run.launcher_agent_id,
            memory_item_id=None,
            title=f"Résultat Process · {label}"[:500],
            memory_type="episodic",
            content=content,
            filename=f"process-run-{run.id}.md",
            keywords=(
                "process",
                "result",
                "success",
                label,
                str(run.process_id),
            ),
            metadata={
                "projection_version": 1,
                "process_definition_id": run.process_id,
                "process_run_id": str(run.id),
            },
        )
    )
    definition_item = await sync_process_definition_projection(run.process_id)
    if (
        definition_item is not None
        and definition_item.owner_agent_id == item.owner_agent_id
    ):
        await ensure_source_managed_link(
            source_item_id=item.id,
            target_item_id=definition_item.id,
            relation_type="result_of",
        )
    await _forget_process_runs_outside_window(
        launcher_agent_id=run.launcher_agent_id,
        process_id=run.process_id,
    )
    return item


__all__ = [
    "PROCESS_RESULT_MAX_CHARS",
    "PROCESS_RUN_PROJECTION_LIMIT",
    "sync_process_definition_projection",
    "sync_process_run_projection",
]
