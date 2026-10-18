"""Catalogue counts stay scoped without loading runtime payloads or N+1 reads."""

import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.agent import Agent
from app.harnesses import service
from app.harnesses.models import AgentHarness, Harness
from app.agent.models import Title


@pytest.mark.asyncio
async def test_catalogue_counts_are_bounded_scoped_and_fresh(db):
    title_id = await db.scalar(select(Title.id).limit(1))
    agents = [Agent(title_id=title_id, code=f"catalogue-{index}",
                    first_name="Synthetic", last_name=str(index)) for index in range(120)]
    first = Harness(name="Synthetic active", provider_code="openai_messages",
                    driver_code="openai_messages", enabled=True)
    db.add_all([first, *agents])
    await db.flush()
    first_id = first.id
    agent_ids = [agent.id for agent in agents]
    db.add_all([AgentHarness(agent_id=agent_id, harness_id=first_id,
                            provider_code="openai_messages",
                            provider_metadata={"payload": "synthetic " * 8192})
                for agent_id in agent_ids[:-2]])
    db.add(AgentHarness(agent_id=agent_ids[-2], provider_code="codex"))
    await db.commit()
    connection = await db.connection()
    reports = []

    async def measure(label, read):
        db.expunge_all()
        statements = []
        loaded = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        def loaded_row(_session, instance):
            if isinstance(instance, AgentHarness):
                loaded.append(instance.id)

        event.listen(connection.sync_connection, "before_cursor_execute", capture)
        event.listen(db.sync_session, "loaded_as_persistent", loaded_row)
        started = perf_counter()
        try:
            result = await read()
        finally:
            elapsed = perf_counter() - started
            event.remove(connection.sync_connection, "before_cursor_execute", capture)
            event.remove(db.sync_session, "loaded_as_persistent", loaded_row)
        reports.append({"scenario": label, "queries": len(statements),
                        "runtime_rows_loaded": len(loaded), "seconds": elapsed})
        return result

    # Hydrate the configuration cache before comparing the two corpus sizes.
    await service.list_catalogue()
    small = await measure("list_1_configuration", service.list_catalogue)
    assert next(row for row in small if row.id == first_id).assigned_agents == 118

    extra = [Harness(name=f"Synthetic extra {index:02d}", provider_code="openai_messages",
                     driver_code="openai_messages", enabled=False) for index in range(40)]
    deleted = Harness(name="Synthetic deleted", provider_code="openai_messages",
                      driver_code="openai_messages", enabled=True)
    db.add_all([*extra, deleted])
    await db.flush()
    disabled_id, deleted_id = extra[0].id, deleted.id
    deleted.soft_delete()
    db.add(AgentHarness(agent_id=agent_ids[-1], harness_id=disabled_id,
                        provider_code="openai_messages"))
    await db.commit()

    large = await measure("list_41_configurations", service.list_catalogue)
    assert [row.name.lower() for row in large] == sorted(row.name.lower() for row in large)
    assert deleted_id not in {row.id for row in large}
    counts = {row.id: row.assigned_agents for row in large}
    assert counts[first_id] == 118 and counts[disabled_id] == 1
    codex_id = service._bridge_catalogue_id("codex")
    assert counts[codex_id] == 1
    assert sum(counts.values()) == 120

    detail = await measure("detail_118_assignments", lambda: service.get_catalogue_harness(first_id))
    assert detail == next(row for row in large if row.id == first_id)
    for scope in ({agent_ids[0], agent_ids[-2]}, set()):
        scoped = await service.list_catalogue(agent_ids=scope)
        scoped_counts = {row.id: row.assigned_agents for row in scoped}
        assert scoped_counts[first_id] == int(bool(scope))
        assert scoped_counts[codex_id] == int(bool(scope))
        assert scoped_counts[disabled_id] == 0
        assert (await service.get_catalogue_harness(first_id, agent_ids=scope)).assigned_agents == int(bool(scope))
        assert (await service.get_catalogue_harness(codex_id, agent_ids=scope)).assigned_agents == int(bool(scope))
    enabled = await service.list_catalogue(enabled_only=True)
    assert enabled == [row for row in large if row.enabled]
    with pytest.raises(LookupError):
        await service.get_catalogue_harness(deleted_id)
    with pytest.raises(LookupError):
        await service.get_catalogue_harness(uuid4())

    # Re-read in the same session after a change: no cached count may leak across requests.
    assignment = await db.scalar(select(AgentHarness).where(AgentHarness.agent_id == agent_ids[0]))
    assignment.harness_id = disabled_id
    await db.commit()
    refreshed = {row.id: row.assigned_agents for row in await service.list_catalogue()}
    assert refreshed[first_id] == 117 and refreshed[disabled_id] == 2
    assert (await service.get_catalogue_harness(first_id)).assigned_agents == 117

    destination = Path(__file__).resolve().parents[4] / "artifacts/harness-catalogue-performance.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(reports, indent=2) + "\n")
    assert all(report["runtime_rows_loaded"] == 0 for report in reports), reports
    assert all(report["queries"] <= 2 for report in reports), reports
