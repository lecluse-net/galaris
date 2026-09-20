from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent
from app.goal.models import (
    Goal,
    GoalCycle,
    GoalCycleStatus,
    GoalReferrerType,
    GoalStatus,
    GoalVerdict,
)
from app.goal.tests.factories import make_goal
from app.memory import service, source_projection
from app.memory.dbadmin import _reconcile_source_projections
from app.memory.models import MemoryItem, MemoryLink
from app.memory.schemas import MemoryGrantUpdate, MemoryItemUpdate, MemorySearchRequest
from app.memory.source_projection import (
    agent_to_markdown,
    rebuild_source_memories,
    sync_agent_source,
    sync_goal_source,
)
from app.task.models import Task, TaskStatus
from app.agent.contracts import ExecutionResult
from core.util import normalize_html, visible_text


async def _goal_with_cycle(
    db: AsyncSession, owner: Agent, referrer: Agent
) -> tuple[Goal, GoalCycle]:
    goal = await make_goal(
        agent_id=owner.id,
        referrer_type=GoalReferrerType.AGENT,
        referrer_agent_id=referrer.id,
        referrer_display_name=f"{referrer.first_name} {referrer.last_name}",
        title="Stabiliser la production",
        description="Réduire durablement les erreurs de déploiement.",
        tracking_content="- Baseline mesurée",
        cycle_delay_seconds=60,
        status=GoalStatus.ACTIVE,
    )
    db.add(goal)
    await db.flush()
    task = Task(
        label="Analyser les incidents",
        objective="Identifier les erreurs récurrentes.",
        status=TaskStatus.SUCCESS,
        ai=True,
        agent_id=owner.id,
        goal_id=goal.id,
    )
    task.set_execution_result(
        ExecutionResult(
            prompt="analyse",
            result="Trois erreurs récurrentes ont été identifiées.",
            tools_used=["search", "console"],
            success=True,
        )
    )
    db.add(task)
    await db.flush()
    cycle = GoalCycle(
        goal_id=goal.id,
        sequence=1,
        task_id=task.id,
        status=GoalCycleStatus.DECIDED,
        verdict=GoalVerdict.CONTINUE,
        reason="Les correctifs restent à appliquer.",
        progress_changed=True,
        progress_summary="Les causes principales sont maintenant connues.",
        evidence=["Trois signatures d’erreur regroupées"],
        continuation_context="Appliquer les correctifs au prochain cycle.",
        task_cost=0.12,
        judge_cost=0.03,
    )
    db.add(cycle)
    await db.commit()
    return goal, cycle


@pytest.mark.asyncio
async def test_agent_markdown_is_deterministic_and_excludes_runtime_secrets(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
) -> None:
    owner, _peer = agents
    owner.personality = "Pragmatique et précis."
    owner.job_title = "Responsable SRE"
    owner.job_description = "Pilote la fiabilité; password=hunter2"
    owner.hermes_api_key = "must-never-appear"
    owner.hermes_mcp_token = "also-private"
    await db.commit()
    loaded = await db.scalar(
        select(Agent)
        .where(Agent.id == owner.id)
        .execution_options(populate_existing=True)
    )
    assert loaded is not None
    await db.refresh(loaded, attribute_names=["title"])

    first = agent_to_markdown(loaded)
    second = agent_to_markdown(loaded)

    assert first == second
    assert f"ID Galaris :** {owner.id}" in first
    assert "Responsable SRE" in first
    assert "Pragmatique et précis" in first
    assert "password=[redacted]" in first
    assert "must-never-appear" not in first
    assert "also-private" not in first


@pytest.mark.asyncio
async def test_source_projection_links_rebuilds_updates_and_deletes_with_source(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    owner.personality = "Calme, analytique et orienté fiabilité."
    owner.job_title = "Responsable SRE"
    await db.commit()
    goal, cycle = await _goal_with_cycle(db, owner, peer)

    agent_memory_id = await sync_agent_source(owner.id)
    goal_memory_id = await sync_goal_source(goal.id)
    assert agent_memory_id is not None
    assert goal_memory_id is not None
    await db.refresh(owner)
    await db.refresh(goal)
    await db.refresh(cycle)
    assert owner.memory_item_id == agent_memory_id
    assert goal.memory_item_id == goal_memory_id
    assert cycle.memory_item_id is not None

    projected = list(
        (
            await db.scalars(
                select(MemoryItem)
                .where(MemoryItem.id.in_([agent_memory_id, goal_memory_id, cycle.memory_item_id]))
                .order_by(MemoryItem.managed_source_kind)
            )
        ).all()
    )
    assert len(projected) == 3
    assert all(item.source_managed for item in projected)
    assert all(item.read_only and item.visibility == "private" for item in projected)
    assert {item.managed_source_kind for item in projected} == {
        "agent",
        "goal",
        "goal_cycle",
    }
    unfiltered_core = await service.search_items(
        MemorySearchRequest(agent_id=owner.id, memory_types=["core"])
    )
    assert agent_memory_id in {hit.item.id for hit in unfiltered_core.hits}
    automatic_core = await service.search_items(
        MemorySearchRequest(
            agent_id=owner.id,
            memory_types=["core"],
            exclude_agent_projections=True,
        )
    )
    assert agent_memory_id not in {hit.item.id for hit in automatic_core.hits}
    link = await db.scalar(
        select(MemoryLink).where(
            MemoryLink.source_item_id == cycle.memory_item_id,
            MemoryLink.target_item_id == goal_memory_id,
            MemoryLink.relation_type == "cycle_of",
        )
    )
    assert link is not None

    cycle_item, cycle_content, access, _content_type, _media_type = await service.get_item(
        cycle.memory_item_id,
        agent_id=owner.id,
    )
    assert not access.can_write
    assert b"Compte rendu de progression" in cycle_content
    assert "goal-cycle:" + str(cycle.id) in cycle_item.keywords
    with pytest.raises(service.MemoryPermissionError, match="source data"):
        await service.update_item(
            cycle_item.id,
            MemoryItemUpdate(title="Modification interdite"),
            actor_agent_id=None,
            administrative=True,
        )
    with pytest.raises(service.MemoryPermissionError, match="source data"):
        await service.forget_item(
            cycle_item.id,
            actor_agent_id=owner.id,
        )
    with pytest.raises(service.MemoryPermissionError, match="source data"):
        await service.set_item_grant(
            cycle_item.id,
            peer.id,
            MemoryGrantUpdate(can_write=False),
        )

    # Losing source pointers does not duplicate memory: the deterministic source
    # identity reattaches the exact existing UUIDs.
    old_cycle_memory_id = cycle.memory_item_id
    owner.memory_item_id = None
    goal.memory_item_id = None
    cycle.memory_item_id = None
    await db.commit()
    rebuilt = await rebuild_source_memories(missing_only=True)
    assert rebuilt.failures == ()
    assert rebuilt.agents_synced == 2
    assert rebuilt.goals_synced == 1
    await db.refresh(owner)
    await db.refresh(goal)
    await db.refresh(cycle)
    assert owner.memory_item_id == agent_memory_id
    assert goal.memory_item_id == goal_memory_id
    assert cycle.memory_item_id == old_cycle_memory_id

    previous_revision = cycle_item.revision
    retained_task = await db.scalar(
        select(Task)
        .where(Task.id == cycle.task_id)
        .execution_options(include_historized=True)
    )
    assert retained_task is not None
    retained_task.soft_delete()
    cycle.progress_summary = "Les correctifs prioritaires sont appliqués."
    await db.commit()
    await sync_goal_source(goal.id)
    refreshed_cycle = await db.get(MemoryItem, old_cycle_memory_id)
    assert refreshed_cycle is not None
    assert refreshed_cycle.revision == previous_revision + 1
    _item, rebuilt_content, _access, _content_type, _media_type = await service.get_item(
        old_cycle_memory_id,
        agent_id=owner.id,
    )
    assert b"Trois erreurs r\xc3\xa9currentes" in rebuilt_content

    goal.soft_delete()
    await db.commit()
    # Startup/manual reconciliation also heals a delete event that could not be
    # enqueued while Memory was temporarily unavailable.
    orphan_rebuild = await rebuild_source_memories(missing_only=True)
    assert orphan_rebuild.orphans_removed == 2
    deleted_goal = await db.scalar(
        select(Goal)
        .where(Goal.id == goal.id)
        .execution_options(include_historized=True)
    )
    assert deleted_goal is not None
    assert deleted_goal.memory_item_id is None
    await db.refresh(cycle)
    assert cycle.memory_item_id is None
    with pytest.raises(service.MemoryNotFoundError):
        await service.get_item(
            old_cycle_memory_id,
            agent_id=owner.id,
        )


@pytest.mark.asyncio
async def test_reconciliation_preserves_cycle_reports_with_unsupported_links(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    goal, cycle = await _goal_with_cycle(db, owner, peer)
    report = (
        "Audit terminé : [**script d’audit**]"
        "(console://work/memory-cycle34/audit_censoring.py).\n\n"
        "[Documentation](https://example.com/audit)."
    )
    cycle.progress_summary = report
    cycle.evidence = ["[Ancienne tâche](galaris://task/not-a-uuid)"]
    await db.commit()

    await _reconcile_source_projections(db)

    await db.refresh(cycle)
    assert cycle.memory_item_id is not None
    item, content, _access, _content_type, media_type = await service.get_item(
        cycle.memory_item_id, agent_id=owner.id,
    )
    html = content.decode("utf-8")
    assert media_type == "text/html"
    assert normalize_html(html) == html
    assert "Audit terminé : script d’audit" in visible_text(html)
    assert "Ancienne tâche" in visible_text(html)
    assert '<strong>script d’audit</strong>' in html
    assert 'href="console://' not in html
    assert 'href="galaris://task/not-a-uuid"' not in html
    assert 'href="https://example.com/audit"' in html
    assert cycle.progress_summary == report
    previous_revision = item.revision

    await _reconcile_source_projections(db)
    await db.refresh(item)
    assert item.revision == previous_revision
    rebuilt = await rebuild_source_memories(missing_only=True)
    assert rebuilt.failures == ()
    assert rebuilt.goals_scanned == 0


@pytest.mark.asyncio
async def test_goal_projection_keeps_only_the_most_recent_cycle_window(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, peer = agents
    assert source_projection.GOAL_CYCLE_PROJECTION_LIMIT == 100
    monkeypatch.setattr(source_projection, "GOAL_CYCLE_PROJECTION_LIMIT", 3)
    goal, first_cycle = await _goal_with_cycle(db, owner, peer)
    other_cycles = [
        GoalCycle(
            goal_id=goal.id,
            sequence=sequence,
            status=GoalCycleStatus.DECIDED,
            verdict=GoalVerdict.CONTINUE,
            progress_summary=f"Progression du cycle {sequence}",
        )
        for sequence in (2, 3)
    ]
    db.add_all(other_cycles)
    await db.commit()

    await sync_goal_source(goal.id)
    await db.refresh(first_cycle)
    for cycle in other_cycles:
        await db.refresh(cycle)
    assert first_cycle.memory_item_id is not None
    assert all(cycle.memory_item_id is not None for cycle in other_cycles)
    evicted_memory_id = first_cycle.memory_item_id
    assert evicted_memory_id is not None

    newest_cycle = GoalCycle(
        goal_id=goal.id,
        sequence=4,
        status=GoalCycleStatus.DECIDED,
        verdict=GoalVerdict.STOP,
        progress_summary="Progression du cycle 4",
    )
    db.add(newest_cycle)
    await db.commit()
    await sync_goal_source(goal.id)
    await db.refresh(first_cycle)
    await db.refresh(newest_cycle)

    assert first_cycle.memory_item_id is None
    assert newest_cycle.memory_item_id is not None
    assert await db.scalar(
        select(func.count(MemoryItem.id)).where(
            MemoryItem.source_managed.is_(True),
            MemoryItem.managed_source_kind == "goal_cycle",
            MemoryItem.managed_source_ref.in_(
                [f"goal-cycle:{cycle.id}" for cycle in [*other_cycles, newest_cycle]]
            ),
        )
    ) == 3
    with pytest.raises(service.MemoryNotFoundError):
        await service.get_item(
            evicted_memory_id,
            agent_id=owner.id,
        )
