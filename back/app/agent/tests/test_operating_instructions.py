"""Every executor uses editable operating knowledge without losing local instructions."""

from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from app.agent import executor_instructions
from app.agent.prompt_tree import ExecutorKind
from app.lab import executor_prompt_service
from core.params import Params, params_service, prompt_default


@pytest.mark.asyncio
@pytest.mark.parametrize("executor,parameter", [
    ("task", Params.AI_EXECUTOR_SYSTEM_PROMPT),
    ("conversation", Params.AI_CONVERSATION_EXECUTOR_SYSTEM_PROMPT),
    ("voice", Params.AI_VOICE_EXECUTOR_SYSTEM_PROMPT),
])
async def test_all_executors_follow_edits_and_explicit_disable(db, executor: ExecutorKind, parameter: str):
    assert await params_service.set(parameter, "Synthetic executor-specific instructions")
    default = prompt_default(Params.AI_GALARIS_OPERATING_PROMPT)
    assert default
    assert await executor_instructions(executor) == default + "\n\nSynthetic executor-specific instructions"

    assert await params_service.set(Params.AI_GALARIS_OPERATING_PROMPT, "Synthetic operating instructions")
    assert await executor_instructions(executor) == "Synthetic operating instructions\n\nSynthetic executor-specific instructions"
    assert await params_service.set(Params.AI_GALARIS_OPERATING_PROMPT, "")
    assert await executor_instructions(executor) == "Synthetic executor-specific instructions"
    assert await params_service.set(Params.AI_GALARIS_OPERATING_PROMPT, None)
    assert await executor_instructions(executor) == default + "\n\nSynthetic executor-specific instructions"


@pytest.mark.asyncio
async def test_lab_freezes_the_composed_prompt_and_accepts_an_empty_baseline(db):
    assert await params_service.set(Params.AI_GALARIS_OPERATING_PROMPT, "Synthetic operating policy v1")
    snapshot = await executor_prompt_service.resolve_dataset_configuration(
        "task", dataset_id=uuid4(), dataset_revision=1, dataset_name="Synthetic experiment", prompt_suffix=None,
    )
    assert await params_service.set(Params.AI_GALARIS_OPERATING_PROMPT, "Synthetic operating policy v2")
    assert snapshot["prompt_suffix"] == "Synthetic operating policy v1"
    assert await executor_prompt_service.default_suffix("task") == "Synthetic operating policy v2"
    baseline = await executor_prompt_service.resolve_dataset_configuration(
        "task", dataset_id=uuid4(), dataset_revision=1, dataset_name="Synthetic baseline", prompt_suffix="",
    )
    assert baseline["prompt_suffix"] == ""


@pytest.mark.asyncio
async def test_task_production_prompt_uses_the_current_composed_setting(monkeypatch):
    from app.agent import executor_service
    from app.agent.contracts import AgentSnapshot
    monkeypatch.setattr(executor_service, "executor_instructions", AsyncMock(return_value="Synthetic administrable policy"))
    agent = AgentSnapshot(id=700, code="synthetic", first_name="Example", last_name="Agent", driver_code="internal")
    assert (await executor_service.build_system_prompt(agent)).endswith("Synthetic administrable policy")
