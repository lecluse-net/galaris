from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent
from app.dream.mechanisms.process_memory import process_memory_mechanism
from app.dream.models import DreamReceipt
from app.memory import service
from app.memory.process_projection import (
    sync_process_definition_projection,
    sync_process_run_projection,
)
from app.process.models import ProcessDefinition, ProcessRun
from app.services.models import Service


@pytest.mark.asyncio
async def test_process_projection_is_private_bounded_and_source_managed(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    tool = Service(
        code=f"process-memory-{uuid4().hex[:8]}",
        label="Process memory engine",
        description="",
        connection_schema={},
    )
    db.add(tool)
    await db.flush()
    definition = ProcessDefinition(
        agent_id=owner.id,
        service_id=tool.id,
        engine_process_id=f"workflow-{uuid4().hex}",
        label="Publication quotidienne",
        description="Publier le rapport quotidien validé.",
    )
    db.add(definition)
    await db.flush()
    now = datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)
    run = ProcessRun(
        process_id=definition.id,
        launcher_agent_id=owner.id,
        launch_snapshot={"process_label": definition.label},
        engine_code=tool.code,
        correlation_id=f"correlation-{uuid4().hex}",
        callback_token=uuid4().hex,
        status="success",
        input={"private": "never projected"},
        output={
            "report": "Rapport publié.",
            "api_key": "sk-test-secret-value-that-must-be-redacted",
        },
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    await db.commit()

    definition_item = await sync_process_definition_projection(definition.id)
    run_item = await sync_process_run_projection(run.id)

    assert definition_item is not None
    assert run_item is not None
    assert definition_item.source_managed
    assert run_item.source_managed
    assert run_item.visibility == "private"
    detail = await service.get_item(
        run_item.id,
        agent_id=owner.id,
        record_llm_access=False,
    )
    content = detail[1].decode("utf-8")
    assert "Rapport publié" in content
    assert "never projected" not in content
    assert "sk-test-secret" not in content
    links = await service.list_links(
        run_item.id,
        actor_agent_id=owner.id,
    )
    assert any(
        link.target_item_id == definition_item.id
        and link.relation_type == "result_of"
        for link in links
    )


@pytest.mark.asyncio
async def test_dream_process_scan_preserves_claim_order_and_bounds_reads(
    db: AsyncSession, agents: tuple[Agent, Agent],
) -> None:
    owner, _ = agents
    engine = Service(code="synthetic-dream-process", label="Synthetic process engine", connection_schema={})
    db.add(engine)
    await db.flush()

    history_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deleted_at = history_start + timedelta(days=1)
    definitions = [
        ProcessDefinition(
            agent_id=owner.id, service_id=engine.id, engine_process_id=f"workflow-{index}",
            label="Synthetic process", created_at=history_start + timedelta(seconds=index),
            deleted_at=deleted_at if index == 104 else None,
        )
        for index in range(105)
    ]
    db.add_all(definitions)
    await db.flush()
    runs = [
        ProcessRun(
            process_id=definitions[0].id, launcher_agent_id=owner.id, engine_code=engine.code,
            correlation_id=f"synthetic-dream-{index}", callback_token="synthetic",
            status=("success", "error", "cancelled")[index % 3] if index < 105 else "running",
            created_at=history_start + timedelta(seconds=index),
            deleted_at=deleted_at if index == 104 else None,
        )
        for index in range(106)
    ]
    db.add_all(runs)
    await db.flush()

    definition_ids = [
        f"definition:{definition.id}:-:{deleted_at.isoformat() if definition.deleted_at else '-'}"
        for definition in definitions
    ]
    run_ids = [
        f"run:{run.id}:{run.status}:-:{deleted_at.isoformat() if run.deleted_at else '-'}"
        for run in runs[:-1]
    ]
    mechanism = process_memory_mechanism
    # Leave one historized definition and one historized terminal run unprocessed.
    db.add_all(
        DreamReceipt(
            mechanism_key=mechanism.key, subject_kind="process_projection",
            subject_id=subject, status="success",
        )
        for subject in [*definition_ids[:-1], *run_ids[1:-1]]
    )
    # A crash lease takes precedence over both fresh subjects.
    retry = DreamReceipt(
        mechanism_key=mechanism.key, subject_kind="process_projection",
        subject_id=run_ids[0],
        status="running", attempts=1, lease_token=uuid4(), lease_expires_at=history_start,
        prepared_payload={"source_kind": "run", "source_id": str(runs[0].id)},
    )
    db.add(retry)
    await db.commit()

    recovered = await mechanism.claim_one()
    assert recovered is not None
    assert recovered.receipt_id == retry.id
    assert recovered.attempts == 2
    assert recovered.prepared_payload == retry.prepared_payload

    for subject in (definition_ids[-1], run_ids[-1]):
        claim = await mechanism.claim_one()
        assert claim is not None
        assert claim.subject_id == subject
    assert await mechanism.count_pending() == 0

    connection = (await db.connection()).sync_connection
    reads = 0

    def count_reads(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal reads
        if statement.lstrip().upper().startswith("SELECT"):
            reads += 1

    event.listen(connection, "before_cursor_execute", count_reads)
    try:
        assert await mechanism.claim_one() is None
    finally:
        event.remove(connection, "before_cursor_execute", count_reads)
    assert reads <= 12
