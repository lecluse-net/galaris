import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from app.agent import executor_service
from app.agent.contracts import BriefingChoice, BriefingResult
from app.agent import briefing_service
from app.task import task_service
from app.task.models import Task, TaskStatus
from tests import conftest as protocols
from tests import test_inference_lifecycle as lifecycle
from tests.test_briefing_inference import briefing_context

runtime = lifecycle.runtime
responses_sse = protocols.responses_sse


def _high_task() -> Task:
    return Task(
        id=uuid4(),
        revision=1,
        label="Briefing",
        objective="Find the closing procedure and apply it carefully",
        status=TaskStatus.BRIEFING,
        effort="high",
        agent_id=7,
        paused=False,
        ai=True,
        cost=0.0,
    )


def test_briefing_output_schema_has_no_nested_reference() -> None:
    schema = briefing_service._BriefingDraft.model_json_schema()  # pyright: ignore[reportPrivateUsage]
    assert '"$ref"' not in json.dumps(schema)


def test_high_briefing_rejects_no_issues() -> None:
    catalog = briefing_service._ResourceCatalog((), ())  # pyright: ignore[reportPrivateUsage]
    draft = briefing_service._BriefingDraft(  # pyright: ignore[reportPrivateUsage]
        result="NO ISSUES",
        choices=[],
    )

    with pytest.raises(ModelRetry, match="forbidden"):
        briefing_service._validate_choices(catalog, draft)  # pyright: ignore[reportPrivateUsage]


def test_high_briefing_rejects_empty_resource_selection() -> None:
    catalog = briefing_service._ResourceCatalog(  # pyright: ignore[reportPrivateUsage]
        tools=(
            briefing_service._ToolResource(  # pyright: ignore[reportPrivateUsage]
                identifier="image_generate",
                label="Images",
                description="Generate an image.",
            ),
        ),
        processes=(),
    )
    draft = briefing_service._BriefingDraft(  # pyright: ignore[reportPrivateUsage]
        result="Generate the requested image and send it to the user.",
        choices=[],
    )

    with pytest.raises(ModelRetry, match="cannot leave choices empty"):
        briefing_service._validate_choices(catalog, draft)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
@pytest.mark.parametrize('custom,override', [(None, None), ('Instance briefing instructions', None), ('Instance briefing instructions', 'Evaluation instructions')])
async def test_briefing_agent_returns_validated_resources(
    runtime,
    monkeypatch: pytest.MonkeyPatch,
    custom,
    override,
) -> None:
    from core.params import Params, params_service

    db, llm, requests, mode = runtime
    monkeypatch.setattr(params_service, '_params_cache', {})
    monkeypatch.setattr(params_service, '_cache_loaded', False)
    assert await params_service.set(Params.AI_BRIEFING_SYSTEM_PROMPT, custom)
    await params_service.refresh()
    task, _ = await briefing_context(db)
    mode.update(
        structured=True,
        outputs=[
            json.dumps(
                {
                    "result": "Find the procedure, verify its date, then follow its steps.",
                    "choices": [
                        {
                            "kind": "tool",
                            "identifier": "memory_search",
                            "label": "Memory",
                            "reason": "Find the validated procedure.",
                            "score": 0.9,
                        }
                    ],
                }
            )
        ],
    )
    catalog = briefing_service._ResourceCatalog(  # pyright: ignore[reportPrivateUsage]
        tools=(
            briefing_service._ToolResource(  # pyright: ignore[reportPrivateUsage]
                identifier="memory_search",
                label="Memory",
                description="Search long-term memory.",
            ),
        ),
        processes=(),
    )

    monkeypatch.setattr(briefing_service, "_resource_catalog", AsyncMock(return_value=catalog))

    result = await briefing_service.generate(
        task,
        llm_override=llm,
        record_task_trace=False,
        system_prompt_override=override,
    )

    assert result.success is True
    assert result.system_prompt == (override or custom or briefing_service.briefing_system_prompt())
    assert result.result.startswith("Find the procedure")
    assert result.choices == [
        BriefingChoice(
            kind="tool",
            identifier="memory_search",
            label="Memory",
            reason="Find the validated procedure.",
            score=0.9,
        )
    ]
    assert '"identifier": "memory_search"' in result.prompt
    assert result.prompt.startswith("# Execution briefing input")
    assert "## Task\n\n    {" in result.prompt
    assert "## Available resources\n\n    {" in result.prompt
    assert 'kind="memory"' not in result.system_prompt
    assert len(requests) == 1
    assert requests[0]["tools"]


@pytest.mark.asyncio
async def test_briefing_persists_result_and_unlocks_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _high_task()
    save = AsyncMock(return_value=task)
    generated = BriefingResult(
        result="Verify the procedure before applying it.",
        choices=[
            BriefingChoice(
                kind="tool",
                identifier="memory_search",
                reason="Find the latest version.",
            )
        ],
        cost=0.01,
    )
    monkeypatch.setattr(task_service, "save", save)
    from app.agent import registry

    monkeypatch.setattr(registry, "should_use_briefing", lambda *_: True)
    monkeypatch.setattr(briefing_service, "is_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(briefing_service, "generate", AsyncMock(return_value=generated))

    result = await briefing_service.run(task)

    assert result == generated
    assert task.get_briefing_result() == result
    assert task.cost == pytest.approx(0.01)
    assert task.status == TaskStatus.DISPATCH
    save.assert_awaited_once_with(task)


@pytest.mark.asyncio
async def test_briefing_is_skipped_when_its_llm_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _high_task()
    save = AsyncMock(return_value=task)
    generate = AsyncMock()
    monkeypatch.setattr(task_service, "save", save)
    monkeypatch.setattr(briefing_service, "is_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(briefing_service, "generate", generate)

    result = await briefing_service.run(task)

    assert result.success is True
    assert result.result == ""
    assert task.get_briefing_result() is None
    assert task.status == TaskStatus.DISPATCH
    generate.assert_not_awaited()
    save.assert_awaited_once_with(task)


@pytest.mark.asyncio
async def test_hermes_never_runs_an_inherited_briefing_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _high_task()
    task.agent = SimpleNamespace(agent_driver="hermes")
    save = AsyncMock(return_value=task)
    generate = AsyncMock()
    monkeypatch.setattr(task_service, "save", save)
    monkeypatch.setattr(briefing_service, "is_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(briefing_service, "generate", generate)

    result = await briefing_service.run(task)

    assert result.success is True
    assert result.result == ""
    assert task.status == TaskStatus.DISPATCH
    generate.assert_not_awaited()
    save.assert_awaited_once_with(task)


@pytest.mark.asyncio
async def test_internal_executor_prompt_contains_its_briefing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _high_task()
    task.set_briefing_result(
        BriefingResult(
            result="Verify the procedure before applying it.",
            choices=[
                BriefingChoice(
                    kind="tool",
                    identifier="memory_search",
                    reason="Find the procedure.",
                )
            ],
        )
    )

    prompt = await executor_service.build_task_prompt(task)

    assert "# Execution Briefing\n\nCRITICAL — this briefing is the execution contract" in prompt
    assert "Verify the procedure before applying it." in prompt
    assert "do not silently omit or weaken" in prompt
    assert "compare the work actually performed and the tool results" in prompt
    assert "Selected resources and checks" in prompt
    assert "- [tool] memory_search: Find the procedure." in prompt
    assert "Memory query already executed" not in prompt


def test_failed_briefing_is_not_injected_into_executor_prompt() -> None:
    task = _high_task()
    task.set_briefing_result(BriefingResult(result="Briefing unavailable.", success=False))

    assert briefing_service.executor_text(task) == ""
