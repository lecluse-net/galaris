from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import briefing_service, dispatcher as dispatcher_module, facade
from app.agent import planner_service
from app.agent.contracts import ActiveDispatchDecision, AgentTask
from app.llm import LLM, LLMCallPurpose
from app.llm.structured_service import StructuredInferenceResult


@pytest.mark.asyncio
async def test_dispatcher_inference_is_task_owned_and_identified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_structured(
        **kwargs: Any,
    ) -> StructuredInferenceResult[ActiveDispatchDecision]:
        captured.update(kwargs)
        return StructuredInferenceResult(
            output=ActiveDispatchDecision(
                reasoning="Bounded task",
                route="EXEC",
                effort="standard",
                language="en",
            ),
            cost=0.0,
            messages=[],
        )

    monkeypatch.setattr(dispatcher_module, "run_structured", fake_run_structured)
    task_id = uuid4()
    agent_run_id = uuid4()
    conversation_round_id = uuid4()

    await dispatcher_module._run_dispatch_inference(  # pyright: ignore[reportPrivateUsage]
        llm=cast(LLM, object()),
        output_type=ActiveDispatchDecision,
        prompted=False,
        prompt="Route this task",
        system_prompt="Dispatcher",
        task_id=task_id,
        agent_id=7,
        agent_run_id=agent_run_id,
        conversation_round_id=conversation_round_id,
        purpose=LLMCallPurpose.AGENT_DISPATCH,
        reasoning_effort_override=None,
    )

    assert captured["task_id"] == task_id
    assert captured["agent_run_id"] == agent_run_id
    assert captured["conversation_round_id"] == conversation_round_id
    assert captured["purpose"] == LLMCallPurpose.AGENT_DISPATCH


@pytest.mark.asyncio
async def test_briefing_inference_is_task_owned_and_identified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    task_id = uuid4()
    task = cast(
        AgentTask,
        SimpleNamespace(
            id=task_id,
            agent_id=7,
            reasoning_effort_override=None,
        ),
    )
    catalog = briefing_service._ResourceCatalog((), ())  # pyright: ignore[reportPrivateUsage]
    draft = briefing_service._BriefingDraft(  # pyright: ignore[reportPrivateUsage]
        result="Inspect the inputs, then verify the result.",
        choices=[
            {
                "kind": "other",
                "identifier": "verification",
                "label": "Verification",
                "reason": "No external resource is required.",
            }
        ],
    )

    async def fake_run_structured(**kwargs: Any) -> StructuredInferenceResult[Any]:
        captured.update(kwargs)
        return StructuredInferenceResult(output=draft, cost=0.0, messages=[])

    monkeypatch.setattr(
        briefing_service,
        "_resource_catalog",
        AsyncMock(return_value=catalog),
    )
    monkeypatch.setattr(briefing_service, "_briefing_prompt", lambda *_args: "Brief")
    monkeypatch.setattr(briefing_service, "run_structured", fake_run_structured)

    result = await briefing_service.generate(
        task,
        llm_override=cast(LLM, object()),
    )

    assert result.success is True
    assert captured["task_id"] == task_id
    assert captured["purpose"] == LLMCallPurpose.AGENT_BRIEFING


@pytest.mark.asyncio
async def test_planner_inference_is_task_owned_and_identified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    task_id = uuid4()
    task = cast(
        AgentTask,
        SimpleNamespace(
            id=task_id,
            agent_id=7,
            agent=object(),
            reasoning_effort_override=None,
        ),
    )
    plan = planner_service.Plan(clarification_questions=["Which target should be used?"])

    async def fake_run_structured(**kwargs: Any) -> StructuredInferenceResult[Any]:
        captured.update(kwargs)
        return StructuredInferenceResult(output=plan, cost=0.0, messages=[])

    async def fake_context(_task: AgentTask, *, stage: str) -> SimpleNamespace:
        assert stage == "planning"
        return SimpleNamespace(conversation_history=[], shared_context="")

    monkeypatch.setattr(
        planner_service,
        "planner_system_prompt",
        AsyncMock(return_value="Planner"),
    )
    monkeypatch.setattr(facade, "build_task_context", fake_context)
    monkeypatch.setattr(planner_service, "_make_plan_prompt", lambda *_args, **_kwargs: "Plan")
    monkeypatch.setattr(
        planner_service,
        "_effective_tool_catalog",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(planner_service, "run_structured", fake_run_structured)

    await planner_service._build_plan(  # pyright: ignore[reportPrivateUsage]
        task,
        llm_override=cast(LLM, object()),
    )

    assert captured["task_id"] == task_id
    assert captured["purpose"] == LLMCallPurpose.AGENT_PLANNING
