from types import SimpleNamespace
from unittest.mock import AsyncMock
from dataclasses import replace
import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks
from sqlalchemy import select

from app.harness import router as compatibility_router
from app.agent import AgentRunCheckpoint, AgentRunRequest, AgentSnapshot, ResolvedModel
from app.agent.contracts import ResolvedExecutionTarget
from app.agent.models import Agent, Title
from app.harnesses import skill_sync
from app.harnesses.models import AgentHarness
from app.harnesses.registry import get_provider
from app.skill import build_skill_projection, skill_service, storage
from app.skill.schemas import SkillCreate, SkillUpdate
from app.skill import learning_service
from app.skill.models import LearnedSkill


@pytest_asyncio.fixture
async def runtime(db, tmp_path, monkeypatch, request):
    code = getattr(request, "param", "codex")
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills"))
    title = Title(label="Mx", gender="M")
    db.add(title)
    await db.flush()
    provider = get_provider(code)
    agent = Agent(title_id=title.id, code="skill-audit", first_name="Synthetic", last_name="Agent", agent_driver=provider.driver_code)
    db.add(agent)
    await db.flush()
    assignment = AgentHarness(agent_id=agent.id, provider_code=code, lifecycle_status="ready", capabilities=sorted(provider.capabilities()))
    db.add(assignment)
    await db.commit()
    skill = await skill_service.create(SkillCreate(code="synthetic", label="Synthetic", markdown="---\nname: synthetic\ndescription: Synthetic procedure\n---\n\nVersion one."))
    await skill_service.set_agent_authorization(skill.id, agent.id, "enabled")
    projected = []

    async def project(_agent, action):
        assert action == "refresh"
        snapshot = await build_skill_projection(agent.id)
        projected.append({(f.skill_code, f.relative_path): f.source.read_bytes() for f in snapshot.files})
        return "synchronized"

    transport = AsyncMock(side_effect=project)
    monkeypatch.setattr(provider, "run_action", transport)
    run = AgentRunRequest(
        run_id=uuid4(), task_id=uuid4(),
        agent=AgentSnapshot(id=agent.id, code=agent.code, first_name=agent.first_name, last_name=agent.last_name, driver_code=agent.agent_driver),
        driver_code=agent.agent_driver, effort="standard", objective="Synthetic task",
        model=ResolvedModel(id=1, code="synthetic", model_name="synthetic", label="Synthetic", requested_effort="standard"),
        target=ResolvedExecutionTarget(provider_code=code, target_ref=f"harness:{assignment.id}", revision=str(assignment.revision), transport="chat_completions"),
    )
    return SimpleNamespace(agent=agent, assignment=assignment, skill=skill, run=run, projected=projected, transport=transport)


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["codex", "claude_agent", "deepseek_harness", "hermes"], indirect=True)
async def test_skill_refresh_accepts_the_selected_network_harness(runtime, db):
    """The compatibility endpoint must not depend on the legacy supervisor registry."""
    # Only queue the request: a running task must never be restarted by this API.
    background = BackgroundTasks()
    result = await compatibility_router.sync_harness_skills(runtime.agent.id, background)
    assert result.status in {"synchronizing", "pending"}
    assert background.tasks == []
    runtime.transport.assert_not_awaited()
    await db.refresh(runtime.assignment)
    assert runtime.assignment.provider_metadata["skill_sync_requested"]


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["codex", "claude_agent", "deepseek_harness", "hermes"], indirect=True)
async def test_next_execution_receives_changes_without_any_frontend_refresh(runtime, db):
    assert (await skill_sync.skill_sync_status(runtime.agent.id))[0] == "pending"
    await skill_sync.prepare_skill_execution(runtime.run)
    assert (await skill_sync.skill_sync_status(runtime.agent.id))[0] == "current"
    assert b"Version one" in runtime.projected[-1][("synthetic", "SKILL.md")]
    await skill_sync.prepare_skill_execution(runtime.run)
    assert len(runtime.projected) == 1
    # These persisted service mutations are the same operations used by the API.
    await skill_service.update(runtime.skill.id, SkillUpdate(markdown="---\nname: synthetic\ndescription: Revised procedure\n---\n\nVersion two."))
    assert (await skill_sync.skill_sync_status(runtime.agent.id))[0] == "pending"
    runtime.transport.assert_awaited_once()
    await skill_sync.prepare_skill_execution(replace(runtime.run, run_id=uuid4()))
    assert b"Version two" in runtime.projected[-1][("synthetic", "SKILL.md")]
    await skill_service.set_agent_authorization(runtime.skill.id, runtime.agent.id, "disabled")
    await skill_sync.prepare_skill_execution(replace(runtime.run, run_id=uuid4()))
    assert ("synthetic", "SKILL.md") not in runtime.projected[-1]
    await skill_service.set_agent_authorization(runtime.skill.id, runtime.agent.id, "enabled")
    await skill_sync.prepare_skill_execution(replace(runtime.run, run_id=uuid4()))
    assert ("synthetic", "SKILL.md") in runtime.projected[-1]
    await skill_service.delete_skill(runtime.skill.id)
    await skill_sync.prepare_skill_execution(replace(runtime.run, run_id=uuid4()))
    assert ("synthetic", "SKILL.md") not in runtime.projected[-1]


@pytest.mark.asyncio
async def test_failed_projection_remains_pending_and_retries_without_losing_a_late_request(runtime, db):
    project = runtime.transport.side_effect
    runtime.transport.side_effect = RuntimeError("Synthetic transport unavailable")
    with pytest.raises(RuntimeError, match="Skill synchronization failed"):
        await skill_sync.prepare_skill_execution(runtime.run)
    await db.refresh(runtime.assignment)
    assert runtime.assignment.provider_metadata.get("skill_revision") is None
    assert runtime.assignment.provider_metadata["skill_sync_error"]

    async def project_with_late_request(agent, action):
        result = await project(agent, action)
        await skill_sync.request_skill_sync(agent.id)
        return result

    runtime.transport.side_effect = project_with_late_request
    await skill_sync.prepare_skill_execution(runtime.run)
    await db.refresh(runtime.assignment)
    metadata = runtime.assignment.provider_metadata
    assert metadata["skill_sync_error"] is None
    assert metadata["skill_sync_requested"] != metadata["skill_sync_applied"]
    runtime.transport.side_effect = project
    await skill_sync.prepare_skill_execution(runtime.run)
    await db.refresh(runtime.assignment)
    assert runtime.assignment.provider_metadata["skill_sync_requested"] == runtime.assignment.provider_metadata["skill_sync_applied"]


@pytest.mark.asyncio
async def test_absent_or_replaced_runtime_is_never_started_by_skill_refresh(runtime, db):
    runtime.assignment.lifecycle_status = "absent"
    await db.commit()
    await skill_sync.request_skill_sync(runtime.agent.id)
    with pytest.raises(RuntimeError, match="no longer ready"):
        await skill_sync.prepare_skill_execution(runtime.run)
    runtime.assignment.lifecycle_status = "ready"
    runtime.assignment.revision += 1
    await db.commit()
    with pytest.raises(RuntimeError, match="no longer ready"):
        await skill_sync.prepare_skill_execution(runtime.run)
    runtime.transport.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_selection_controls_affected_agents(runtime, db):
    assert await skill_service.runtime_requires_skill_sync(runtime.agent.id)
    assert runtime.agent.id in [a.id for a in await skill_service.list_managed_runtime_agents()]
    # Merely using the network transport does not imply a managed skill tree.
    await db.delete(await db.scalar(select(AgentHarness).where(AgentHarness.agent_id == runtime.agent.id)))
    await db.commit()
    assert not await skill_service.runtime_requires_skill_sync(runtime.agent.id)


@pytest.mark.asyncio
async def test_interrupted_copy_and_auxiliary_file_changes_cannot_reuse_an_old_receipt(runtime, db):
    await skill_sync.prepare_skill_execution(runtime.run)
    project = runtime.transport.side_effect
    await skill_sync.request_skill_sync(runtime.agent.id)
    runtime.transport.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await skill_sync.prepare_skill_execution(runtime.run)
    assert (await skill_sync.skill_sync_status(runtime.agent.id))[0] == "pending"
    await storage.write_file("synthetic", "references/example.txt", b"Synthetic supporting file.", overwrite=False)
    runtime.transport.side_effect = project
    await skill_sync.prepare_skill_execution(runtime.run)
    assert runtime.projected[-1][("synthetic", "references/example.txt")] == b"Synthetic supporting file."
    assert (await skill_sync.skill_sync_status(runtime.agent.id))[0] == "current"


@pytest.mark.asyncio
async def test_changed_library_during_copy_is_reconciled_before_execution(runtime, db):
    project = runtime.transport.side_effect

    async def change_once(agent, action):
        result = await project(agent, action)
        if len(runtime.projected) == 1:
            await skill_service.set_agent_authorization(runtime.skill.id, agent.id, "disabled")
        return result

    runtime.transport.side_effect = change_once
    await skill_sync.prepare_skill_execution(runtime.run)
    assert len(runtime.projected) == 2
    assert ("synthetic", "SKILL.md") not in runtime.projected[-1]
    assert (await skill_sync.skill_sync_status(runtime.agent.id))[0] == "current"


@pytest.mark.asyncio
async def test_import_and_learned_skill_suspension_apply_at_the_next_execution(runtime, db):
    await skill_sync.prepare_skill_execution(runtime.run)
    await skill_service.import_upload(
        "SKILL.md", b"---\nname: synthetic\ndescription: Imported procedure\n---\n\nImported instructions.",
        "synthetic", "Synthetic", True,
    )
    learned = LearnedSkill(
        agent_id=runtime.agent.id, code="learned-synthetic", label="Synthetic learning",
        description="Synthetic learned procedure", evidence_count=100, score=1,
        markdown="---\nname: learned-synthetic\ndescription: Synthetic learning\n---\n\nLearned instructions.",
    )
    db.add(learned)
    await db.commit()
    await skill_sync.prepare_skill_execution(runtime.run)
    assert b"Imported instructions" in runtime.projected[-1][("synthetic", "SKILL.md")]
    assert ("learned-synthetic", "SKILL.md") in runtime.projected[-1]
    before = len(runtime.projected)
    await learning_service.set_suspended(learned.id, True)
    assert len(runtime.projected) == before
    await skill_sync.prepare_skill_execution(runtime.run)
    assert ("learned-synthetic", "SKILL.md") not in runtime.projected[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["hermes"], indirect=True)
async def test_remote_continuation_keeps_its_runtime_until_a_fresh_execution(runtime, db):
    await skill_sync.prepare_skill_execution(runtime.run)
    await skill_service.set_agent_authorization(runtime.skill.id, runtime.agent.id, "disabled")
    await skill_sync.request_skill_sync(runtime.agent.id)
    continuation = replace(runtime.run, resume_checkpoint=AgentRunCheckpoint(
        driver_code="hermes", runtime_run_id="synthetic-remote-run", status="running",
    ))
    await skill_sync.prepare_skill_execution(continuation)
    runtime.transport.assert_awaited_once()
    assert (await skill_sync.skill_sync_status(runtime.agent.id))[0] == "pending"
    await skill_sync.prepare_skill_execution(replace(runtime.run, task_id=uuid4(), run_id=uuid4()))
    assert ("synthetic", "SKILL.md") not in runtime.projected[-1]
