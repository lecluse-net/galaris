from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent
from app.memory import service
from app.memory.process_projection import (
    sync_process_definition_projection,
    sync_process_run_projection,
)
from app.process.models import ProcessDefinition, ProcessRun
from app.tools.models import Tool


@pytest.mark.asyncio
async def test_process_projection_is_private_bounded_and_source_managed(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    tool = Tool(
        code=f"process-memory-{uuid4().hex[:8]}",
        label="Process memory engine",
        description="",
        connection_schema={},
    )
    db.add(tool)
    await db.flush()
    definition = ProcessDefinition(
        agent_id=owner.id,
        tool_id=tool.id,
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
    assert run_item.memory_type == "episodic"
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
