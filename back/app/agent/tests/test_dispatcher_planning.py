"""Tests for dispatcher planning detection and depth limits."""

from types import SimpleNamespace
import json
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent import dispatcher as dispatcher_mod, dispatcher_service
from app.agent.contracts import (
    ActiveDispatchDecision,
    TaskDispatchDecision,
    ConversationDispatchDecision,
    DispatchDecision,
    DispatchResult,
)
from app.agent.dispatcher import Dispatcher
from app.llm import model_usages
from app.task import task_service
from app.task.models import Task, TaskStatus
from app.task import TaskMessage


@pytest.mark.asyncio
async def test_standard_only_harness_dispatches_without_loading_model(monkeypatch):
    from dataclasses import replace
    from app.agent.contracts import DriverPipelinePolicy
    from app.agent.registry import INTERNAL_HARNESS

    spec = replace(INTERNAL_HARNESS, pipeline_policy=DriverPipelinePolicy(
        use_planner=False, use_briefing=False,
    ))
    monkeypatch.setattr(Dispatcher, "_task_executor_driver", staticmethod(lambda task: spec))
    inference = AsyncMock(side_effect=AssertionError("No choice remains"))
    model_check = AsyncMock(side_effect=AssertionError("No model should be resolved"))
    monkeypatch.setattr(Dispatcher, "_infer_dispatch", inference)
    monkeypatch.setattr(dispatcher_mod, "has_agent_profile_model", model_check)
    result = await Dispatcher().run(_task(data={"language": "fr"}))

    assert result.success is True
    assert (result.decision.route, result.decision.effort) == ("EXEC", "standard")
    assert result.decision.language == "fr"
    inference.assert_not_awaited()
    model_check.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("route, effort, phase", [
    ("EXEC", "standard", TaskStatus.DISPATCH),
    ("EXEC", "high", TaskStatus.DISPATCH),
    ("BRIEFING", "high", TaskStatus.BRIEFING),
    ("PLAN", "high", TaskStatus.PLAN),
])
async def test_dispatcher_choice_drives_the_pipeline_when_all_capabilities_exist(
    monkeypatch, route, effort, phase,
):
    from dataclasses import replace
    from app.agent.contracts import DriverPipelinePolicy
    from app.agent.registry import INTERNAL_HARNESS

    spec = replace(INTERNAL_HARNESS, pipeline_policy=DriverPipelinePolicy(
        use_planner=True, use_briefing=True,
        uses_llm_calls=True,
        execution_efforts=frozenset({"standard", "high"}),
        briefing_efforts=frozenset({"high"}),
    ))
    monkeypatch.setattr(Dispatcher, "_task_executor_driver", staticmethod(lambda task: spec))
    infer = AsyncMock(return_value=SimpleNamespace(
        output=TaskDispatchDecision(route=route, effort=effort), cost=0.0,
    ))
    monkeypatch.setattr(dispatcher_mod, "run_structured", infer)
    monkeypatch.setattr(dispatcher_mod, "require_agent_profile_model", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(task_service, "save", AsyncMock())
    task = _task()

    result = await dispatcher_service.run(task)

    assert task.status == phase
    assert (result.decision.route, result.decision.effort) == (route, effort)
    assert task.get_dispatch_result() is not None
    assert result.pipeline_policy["dispatch_choices"] == [
        {"route": "EXEC", "effort": "standard"},
        {"route": "EXEC", "effort": "high"},
        {"route": "BRIEFING", "effort": "high"},
        {"route": "PLAN", "effort": "high"},
    ]
    prompt = infer.await_args.kwargs["system_prompt"]
    assert "route=BRIEFING, effort=high" in prompt
    assert "route=EXEC, effort=high" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("uses_llm_calls", [False, True])
async def test_selected_provider_policy_overrides_shared_network_driver(monkeypatch, uses_llm_calls):
    from app.agent.contracts import ConfiguredHarnessSelection, DriverPipelinePolicy
    from app.agent.harness_port import harness_selection_port

    task = _task()
    task.agent = SimpleNamespace(id=7, agent_driver="openai_messages")
    selected = ConfiguredHarnessSelection(
        id=uuid4(), name="Provider", provider_code="codex", driver_code="openai_messages",
        revision=1, status="ready", pipeline_policy=DriverPipelinePolicy(
            use_planner=False, use_briefing=False,
            execution_efforts=frozenset({"standard", "high"}),
            uses_llm_calls=uses_llm_calls,
        ),
    )
    monkeypatch.setattr(harness_selection_port, "resolve", AsyncMock(return_value=selected))
    infer = AsyncMock(return_value=DispatchResult(
        prompt="choice", decision=DispatchDecision(route="EXEC", effort="high"),
    ))
    monkeypatch.setattr(Dispatcher, "_infer_dispatch", infer)

    result = await Dispatcher().run(task)

    assert result.decision.effort == ("high" if uses_llm_calls else "standard")
    assert infer.await_count == int(uses_llm_calls)
    assert result.pipeline_policy["uses_llm_calls"] is uses_llm_calls
    assert result.allowed_routes == ["EXEC"]


@pytest.mark.asyncio
async def test_missing_model_does_not_hide_incompatible_task_route(monkeypatch):
    task = _task(forced_route="PLAN")
    task.agent = SimpleNamespace(agent_driver="hermes")
    monkeypatch.setattr(dispatcher_mod, "has_agent_profile_model", AsyncMock(return_value=False))
    monkeypatch.setattr(task_service, "save", AsyncMock(return_value=task))

    result = await dispatcher_service.run(task)

    assert result.success is False
    assert task.status == TaskStatus.ERROR
    assert task.get_dispatch_result() is not None


@pytest.mark.parametrize("kind, output_type", [
    ("active", ActiveDispatchDecision),
    ("conversation", ConversationDispatchDecision),
])
def test_dispatcher_contract_upgrade_preserves_frozen_inferences(kind, output_type):
    from app.llm import output_registry
    from app.llm.contracts import StructuredOutputSpec

    dispatcher_mod.register_dispatcher_output_contracts()
    schemas = json.loads(
        (Path(__file__).parent / "fixtures/dispatcher_v1_schemas.json").read_text()
    )
    old_spec = StructuredOutputSpec(
        contract=f"galaris.dispatcher.{kind}/v1", json_schema=schemas[kind],
    )
    legacy = output_registry.resolve(old_spec).output_type.model_validate(
        {"route": "EXEC", "requires_action": True}
    )
    current = output_type.model_validate(legacy.model_dump())
    assert "requires_action" not in current.model_dump()
    current_spec = output_registry.for_type(output_type, None, mode="tool")
    assert current_spec.contract == f"galaris.dispatcher.{kind}/v2"
    assert "requires_action" not in current_spec.json_schema["properties"]
    if kind == "active":
        schema_v2 = schemas[kind]
        schema_v2["properties"].pop("requires_action")
        output_registry.resolve(StructuredOutputSpec(
            contract="galaris.dispatcher.active/v2", json_schema=schema_v2,
        ))
        spec_v3 = output_registry.for_type(TaskDispatchDecision, None, mode="tool")
        assert spec_v3.contract == "galaris.dispatcher.active/v3"
        assert spec_v3.json_schema["properties"]["route"]["enum"] == ["EXEC", "BRIEFING", "PLAN"]


@pytest.fixture(autouse=True)
def configured_dispatcher_model(monkeypatch):
    monkeypatch.setattr(dispatcher_mod, "has_agent_profile_model", AsyncMock(return_value=True))
    monkeypatch.setattr(dispatcher_mod, "resolve_agent_decision_models", AsyncMock(return_value=(None, None, False)))


def _task(**kw) -> Task:
    defaults = dict(
        id=uuid4(),
        label="P",
        objective="Background objective",
        status=TaskStatus.CREATE,
        cost=0.0,
        data=None,
        messages=None,
        message_group_id=None,
        message_platform=None,
        parent_id=None,
    )
    defaults.update(kw)
    return Task(**defaults)


def _message(message_id: str, text: str, sender_id: str = "alice") -> TaskMessage:
    return TaskMessage(
        external_message_id=message_id,
        text=text,
        sender_external_id=sender_id,
        sender_display_name=sender_id.title(),
    )


def _ai_message(message_id: str, time: int = 0) -> TaskMessage:
    return TaskMessage(
        external_message_id=message_id,
        text="msg",
        timestamp=time,
        sender_external_id="bot",
        sender_display_name="Bot",
        sender_agent_id=1,
        sender_is_ai=True,
    )


def test_is_background_objective_task_detection():
    assert Dispatcher._is_background_objective_task(_task()) is True
    # Messaging tasks cannot be planned.
    assert Dispatcher._is_background_objective_task(_task(message_group_id="room1")) is False
    assert Dispatcher._is_background_objective_task(_task(message_platform="talk")) is False
    # A task without an objective cannot be planned.
    assert Dispatcher._is_background_objective_task(_task(objective=None)) is False
    assert Dispatcher._is_background_objective_task(_task(objective="   ")) is False


def test_conversation_task_with_standalone_objective_uses_the_objective_prompt() -> None:
    task = _task(
        label="Calcul",
        objective="Calculer 12 + 5 et communiquer le résultat à Nicolas.",
        data={
            "objective_is_standalone": True,
            "text": "@task ok, vas-y",
        },
        message_group_id="room1",
        message_platform="internal",
    )

    assert Dispatcher._has_standalone_objective(task) is True
    prompt = Dispatcher._make_objective_prompt(task)
    assert "Calculer 12 + 5" in prompt
    assert "@task ok, vas-y" not in prompt


def test_conversation_context_keeps_current_message_and_ten_previous():
    messages = [_message(f"m{i}", f"Message {i:02d}") for i in range(12)]
    task = _task(
        objective="OK",
        data={"id": "current", "text": "OK", "sender.display_name": "Alice"},
        messages=messages,
        message_group_id="room1",
        message_platform="talk",
    )

    prompt = Dispatcher()._make_conversation_context(task)

    assert "<history>" in prompt
    assert "<current_message>" in prompt
    assert "Alice: OK" in prompt
    assert "Message 00" not in prompt
    assert "Message 01" not in prompt
    assert "Message 02" in prompt
    assert "Message 11" in prompt
    assert "omitted" not in prompt


def test_conversation_context_omits_history_code_blocks():
    task = _task(
        data={"id": "current", "text": "OK", "sender.display_name": "Alice"},
        messages=[
            _message(
                "previous",
                "Here is the file:\n```python\nprint('very long code')\n```\nUse it.",
            )
        ],
        message_group_id="room1",
        message_platform="talk",
    )

    prompt = Dispatcher()._make_conversation_context(task)

    assert "[code block omitted]" in prompt
    assert "very long code" not in prompt
    assert "Use it." in prompt


def test_conversation_context_openai_uses_last_message_as_current():
    task = _task(
        objective="OK",
        messages=[
            _message("m1", "Do you want me to create the report?"),
            _message("m2", "OK"),
        ],
        message_platform="openai",
    )

    prompt = Dispatcher()._make_conversation_context(task)

    assert "- Alice: Do you want me to create the report?" in prompt
    assert "<current_message>\nAlice: OK" in prompt


def test_conversation_context_renders_timestamp_and_sender_metadata() -> None:
    timestamp = 1_700_000_000
    task = _task(
        objective="Current",
        data={
            "id": "current",
            "text": "Current",
            "timestamp": timestamp,
            "sender.display_name": "Nicolas",
            "sender_is_ai": False,
        },
        messages=[
            TaskMessage(
                external_message_id="previous",
                text="Earlier message",
                timestamp=timestamp,
                sender_external_id="nicolas",
                sender_display_name="Nicolas",
            ),
            TaskMessage(
                external_message_id="current",
                text="Current",
                timestamp=timestamp,
                sender_external_id="nicolas",
                sender_display_name="Nicolas",
            ),
        ],
        message_group_id="room1",
        message_platform="talk",
    )

    prompt = Dispatcher()._make_conversation_context(task)

    assert "| Nicolas | human] Earlier message" in prompt
    assert "<current_message>\n[" in prompt
    assert "| Nicolas | human] Current" in prompt
    assert prompt.count("Current") == 1


@pytest.mark.asyncio
async def test_subtask_routes_exec_without_llm():
    # A non-conversational subtask with parent_id skips inference and goes directly to EXEC,
    # without LLM or database calls. The planner already decided child routing.
    task = _task(parent_id=uuid4())
    result = await Dispatcher().run(task)
    assert result.success is True
    assert result.decision.route == "EXEC"
    assert result.decision.effort == "standard"
    assert result.decision.language == "en"
    assert result.cost == 0.0
    assert result.prompt == ""


@pytest.mark.asyncio
async def test_ai_origin_task_cannot_route_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...] | None] = []

    async def fake_infer(
        self,
        task,
        start_time,
        system_prompt,
        human_prompt,
        *,
        clamp_to=None,
        force_route=None,
        force_effort=None,
    ):
        calls.append(clamp_to)
        return DispatchResult(
            decision=DispatchDecision(
                reasoning="Simulated legacy inference output.",
                route="END",
                effort="standard",
            ),
            prompt=human_prompt,
            system_prompt=system_prompt,
            success=True,
        )

    monkeypatch.setattr(Dispatcher, "_infer_dispatch", fake_infer)

    task = _task(
        data={"sender_is_ai": True, "text": "ok"},
        message_group_id="room1",
        message_platform="talk",
    )

    result = await Dispatcher().run(task)

    assert calls == [("EXEC", "PLAN")]
    assert result.decision.route == "EXEC"
    assert result.allowed_routes == ["EXEC", "PLAN"]


@pytest.mark.asyncio
async def test_subtask_routes_exec_with_planner_high_effort():
    task = _task(parent_id=uuid4(), effort="high", data={"language": "fr"})

    result = await Dispatcher().run(task)

    assert result.success is True
    assert result.decision.route == "EXEC"
    assert result.decision.effort == "high"
    assert result.decision.language == "fr"


@pytest.mark.asyncio
async def test_lab_input_evaluation_rebuilds_current_dispatcher_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_infer(
        self,
        task,
        start_time,
        system_prompt,
        human_prompt,
        *,
        clamp_to=None,
        force_route=None,
        force_effort=None,
        llm_override=None,
        record_task_trace=True,
    ):
        captured.update(
            task=task,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            clamp_to=clamp_to,
            llm_override=llm_override,
            record_task_trace=record_task_trace,
        )
        return DispatchResult(
            decision=DispatchDecision(
                reasoning="One direct response.",
                route="EXEC",
                effort="standard",
                language="fr",
            ),
            prompt=human_prompt,
            system_prompt=system_prompt,
        )

    monkeypatch.setattr(Dispatcher, "_infer_dispatch", fake_infer)
    llm = MagicMock()

    result = await Dispatcher().evaluate_input(
        input_data={
            "label": "Répondre",
            "objective": "Répondre à Alice",
            "driver_code": "internal",
            "message_platform": "talk",
            "message_group_id": "room-1",
            "data": {
                "id": "current",
                "text": "Peux-tu répondre ?",
                "sender.display_name": "Alice",
            },
            "messages": [
                {
                    "id": "previous",
                    "text": "Bonjour",
                    "time": 1,
                    "sender": {"id": "alice", "display_name": "Alice"},
                }
            ],
        },
        llm=llm,
    )

    assert result.decision.route == "EXEC"
    assert "Alice: Peux-tu répondre ?" in str(captured["human_prompt"])
    assert "## AVAILABLE ROUTES" in str(captured["system_prompt"])
    assert captured["clamp_to"] == ("EXEC", "PLAN")
    assert captured["llm_override"] is llm
    assert captured["record_task_trace"] is False


def test_dispatch_decision_language_falls_back_to_english():
    decision = DispatchDecision(
        reasoning="Unsupported language",
        route="EXEC",
        effort="standard",
        language="de",
    )

    assert decision.language == "en"


def test_active_dispatch_decision_rejects_historical_end_route() -> None:
    with pytest.raises(ValueError):
        ActiveDispatchDecision.model_validate(
            {
                "reasoning": "Historical close-without-execution route.",
                "route": "END",
                "effort": "standard",
            }
        )
    historical = DispatchDecision(
        reasoning="Historical close-without-execution route.",
        route="END",
        effort="standard",
    )
    assert historical.route == "END"


def test_inferred_dispatch_contracts_do_not_request_generated_reasoning() -> None:
    assert "reasoning" not in ActiveDispatchDecision.model_fields
    assert "reasoning" not in ConversationDispatchDecision.model_fields
    assert DispatchDecision(route="EXEC").reasoning == ""
    assert "Do not generate a justification" in dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    assert "Do not generate a justification" in (
        dispatcher_mod._CONVERSATION_DISPATCHER_SYSTEM_PROMPT
    )


@pytest.mark.asyncio
async def test_dispatcher_uses_agent_specific_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    personal_model = MagicMock()
    resolve_override = AsyncMock(return_value=personal_model)
    inference = SimpleNamespace(
        output=ActiveDispatchDecision(
            reasoning="Direct task",
            route="EXEC",
            effort="standard",
            language="en",
        ),
        cost=0.01,
    )
    run_structured = AsyncMock(return_value=inference)
    monkeypatch.setattr(
        dispatcher_mod,
        "require_agent_profile_model",
        resolve_override,
    )
    monkeypatch.setattr(dispatcher_mod, "run_structured", run_structured)
    task = SimpleNamespace(
        id=uuid4(),
        agent_id=7,
        agent=SimpleNamespace(),
    )

    result = await Dispatcher()._infer_dispatch(
        task,
        0.0,
        "system",
        "objective",
    )

    assert result.success is True
    resolve_override.assert_awaited_once_with(task.agent, model_usages.DISPATCHER)
    assert run_structured.await_args.kwargs["llm"] is personal_model
    assert run_structured.await_args.kwargs["max_tokens"] == 256


@pytest.mark.asyncio
async def test_conversation_dispatcher_uses_prompted_json_without_output_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    round_id = uuid4()
    run_id = uuid4()
    prompted = AsyncMock(
        return_value=SimpleNamespace(
            output=ActiveDispatchDecision(
                reasoning="Direct conversation",
                route="EXEC",
                effort="standard",
                language="fr",
            ),
            cost=0.01,
        )
    )
    structured = AsyncMock()
    monkeypatch.setattr(
        dispatcher_mod,
        "require_agent_profile_model",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(dispatcher_mod, "run_prompted", prompted)
    monkeypatch.setattr(dispatcher_mod, "run_structured", structured)
    task = SimpleNamespace(
        id=round_id,
        agent_id=7,
        agent=SimpleNamespace(),
        data={"language": "fr"},
    )

    result = await Dispatcher()._infer_dispatch(
        task,
        0.0,
        "system",
        "As-tu une âme ?",
        record_task_trace=False,
        agent_run_id=run_id,
        conversation_round_id=round_id,
    )

    assert result.success is True
    assert result.decision.route == "EXEC"
    structured.assert_not_awaited()
    assert prompted.await_args.kwargs["output_type"] is TaskDispatchDecision
    assert prompted.await_args.kwargs["output_retries"] == 0
    assert prompted.await_args.kwargs["max_tokens"] == 256
    assert prompted.await_args.kwargs["task_id"] is None
    assert prompted.await_args.kwargs["agent_run_id"] == run_id
    assert prompted.await_args.kwargs["conversation_round_id"] == round_id


@pytest.mark.asyncio
async def test_human_conversation_dispatcher_provider_failure_falls_back_to_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dispatcher_mod,
        "require_agent_profile_model",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        dispatcher_mod,
        "run_prompted",
        AsyncMock(side_effect=RuntimeError("provider overloaded")),
    )
    task = SimpleNamespace(
        id=uuid4(),
        agent_id=7,
        agent=SimpleNamespace(),
        data={"language": "fr"},
    )

    result = await Dispatcher()._infer_dispatch(
        task,
        0.0,
        "system",
        "stop",
        record_task_trace=False,
        conversation_round_id=uuid4(),
    )

    assert result.decision.route == "EXEC"
    assert result.decision.language == "fr"
    assert result.success is True
    assert "provider overloaded" in result.decision.reasoning


@pytest.mark.asyncio
@pytest.mark.parametrize("subscription", [False, True])
async def test_truncated_dispatch_retains_persisted_call_cost_in_conversation_result(db, monkeypatch, subscription):
    from app.llm import LLMCall, llm_call_service

    call = LLMCall(provider_name="test", requested_model="reasoner", is_subscription=subscription)
    unrelated = LLMCall(provider_name="test", cost=9.0)
    db.add_all([call, unrelated])
    await db.commit()
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())
    monkeypatch.setattr(dispatcher_mod, "has_agent_profile_model", AsyncMock(return_value=True))
    monkeypatch.setattr(dispatcher_mod, "require_agent_profile_model", AsyncMock(return_value=MagicMock()))

    async def truncated(**kwargs):
        trace = {"finish_reason": "length", "usage": {"prompt_tokens": 1350,
                 "completion_tokens": 256, "completion_tokens_details": {"reasoning_tokens": 256}, "cost": .042}}
        # Streaming updates and a repeated terminal observation are one billable call.
        await llm_call_service.finalize_call(call.id, trace=trace)
        await llm_call_service.finalize_call(call.id, trace=trace)
        raise RuntimeError("Model token limit (256) exceeded before any response was generated")

    monkeypatch.setattr(dispatcher_mod, "run_prompted", truncated)
    result = await Dispatcher().run_conversation(round_id=uuid4(), run_id=uuid4(),
        agent_id=7, agent=SimpleNamespace(), language="fr", objective="Dessine une image", sender_is_ai=True)
    await db.refresh(call)
    assert result.success and result.decision.route == "END"
    assert call.output_tokens == call.reasoning_tokens == 256
    assert call.inference_cost == pytest.approx(.042)
    assert result.cost == call.cost == (0.0 if subscription else .042)


@pytest.mark.asyncio
async def test_ai_conversation_dispatcher_provider_failure_falls_back_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dispatcher_mod,
        "require_agent_profile_model",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        dispatcher_mod,
        "run_prompted",
        AsyncMock(side_effect=RuntimeError("malformed structured output")),
    )
    task = SimpleNamespace(
        id=uuid4(),
        agent_id=7,
        agent=SimpleNamespace(),
        data={"language": "fr"},
    )

    result = await Dispatcher()._infer_dispatch(
        task,
        0.0,
        "system",
        "merci",
        record_task_trace=False,
        allow_end=True,
        conversation_round_id=uuid4(),
    )

    assert result.decision.route == "END"
    assert result.decision.language == "fr"
    assert result.success is True
    assert "malformed structured output" in result.decision.reasoning


def test_conversation_dispatch_decision_rejects_plan_and_high_effort() -> None:
    with pytest.raises(ValueError):
        ConversationDispatchDecision(
            reasoning="Planning is outside the conversation profile.",
            route="PLAN",  # type: ignore[arg-type]
            effort="standard",
        )
    with pytest.raises(ValueError):
        ConversationDispatchDecision(
            reasoning="Elevated execution is outside the conversation profile.",
            route="EXEC",
            effort="high",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_dispatcher_prompt_lists_only_available_routes():
    assert "- PLAN:" not in dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    assert "- END:" not in dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    assert 'Start from EXEC with effort "standard"' in dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    assert (
        'EXEC with effort "high" is the preferred route'
        in dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    )
    assert (
        "PLAN is reserved for SEVERAL independently executable work units"
        in dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    )
    assert (
        'When uncertain between EXEC "high" and PLAN, choose EXEC "high"'
        in dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    )
    assert "Research, production" in dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    assert "Operational risk changes the required safeguards" in (
        dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    )
    assert "resetting one exact repository" in dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    assert 'operation remains EXEC "standard"' in (
        dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    )

    prompt = await Dispatcher()._routing_gate({"EXEC"}, _task())

    assert "${languages}" in dispatcher_mod._DISPATCHER_SYSTEM_PROMPT
    assert "- **EXEC**" in prompt
    assert "the default route" in prompt
    assert "execution briefing" not in prompt
    assert "- **PLAN**" not in prompt
    assert "- **END**" not in prompt


def test_dispatcher_effort_contract_keeps_bounded_destructive_work_standard() -> None:
    description = ActiveDispatchDecision.model_fields["effort"].description or ""

    assert "bounded, explicit, deterministic operation" in description
    assert "authorized destructive action" in description
    assert "Operational risk requires safety controls" in description
    assert "material cognitive complexity" in description


@pytest.mark.asyncio
async def test_dispatcher_plan_gate_reserves_planning_for_independent_work_units():
    prompt = await Dispatcher()._routing_gate({"EXEC", "PLAN"}, _task())

    assert "one coherent but demanding work unit" in prompt
    assert "execution briefing" not in prompt
    assert "at least two independently executable, meaningful work units" in prompt
    assert "one cohesive artifact requires several phases" in prompt


@pytest.mark.asyncio
async def test_hermes_route_gate_does_not_advertise_galaris_briefing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    monkeypatch.setattr(
        task,
        "agent",
        SimpleNamespace(agent_driver="hermes"),
        raising=False,
    )

    prompt = await Dispatcher()._routing_gate({"EXEC"}, task)

    assert "or high for one coherent" in prompt
    assert "execution briefing" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("user_language,expected", [(None, "fr"), ("zh", "zh")])
async def test_dispatcher_service_persists_detected_language(monkeypatch: pytest.MonkeyPatch, user_language, expected):
    monkeypatch.setattr(
        "core.user.user_service.get_current_user",
        AsyncMock(return_value=SimpleNamespace(language=user_language) if user_language else None),
    )
    task = _task(
        data={"room_id": "room1"},
        message_group_id="room1",
        message_platform="talk",
        cost=0.0,
    )
    result = DispatchResult(
        decision=DispatchDecision(
            reasoning="Message in French",
            route="EXEC",
            effort="standard",
            language="fr",
        ),
        prompt="",
        system_prompt="",
        success=True,
    )
    fake_dispatcher = MagicMock()
    fake_dispatcher.run = AsyncMock(return_value=result)
    monkeypatch.setattr(dispatcher_service, "get_dispatcher", lambda: fake_dispatcher)
    monkeypatch.setattr(
        dispatcher_mod,
        "has_agent_profile_model",
        AsyncMock(return_value=MagicMock()),
    )

    update = AsyncMock()
    monkeypatch.setattr(task_service, "update", update)

    await dispatcher_service.run(task)

    assert task.data is not None
    assert task.data["room_id"] == "room1"
    assert task.data["language"] == expected
    assert result.decision.language == expected
    assert update.await_count >= 1


@pytest.mark.asyncio
async def test_dispatcher_routes_high_exec_directly_while_briefing_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task(effort="high")
    save = AsyncMock(return_value=task)
    monkeypatch.setattr(task_service, "save", save)

    await dispatcher_service._update_task_status(task, TaskStatus.DISPATCH)

    assert task.status == TaskStatus.DISPATCH
    save.assert_awaited_once_with(task)


@pytest.mark.asyncio
async def test_missing_dispatcher_llm_skips_inference_and_executes_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task(effort="standard", data={"language": "fr"})
    save = AsyncMock(return_value=task)
    monkeypatch.setattr(
        dispatcher_mod,
        "has_agent_profile_model",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(task_service, "save", save)

    result = await dispatcher_service.run(task)

    assert result.decision.route == "EXEC"
    assert result.decision.effort == "standard"
    assert result.decision.language == "fr"
    assert result.prompt == ""
    assert task.get_dispatch_result() is not None
    assert task.status == TaskStatus.DISPATCH
    assert save.await_count == 2


@pytest.mark.asyncio
async def test_root_task_with_single_route_still_infers_executor_tier(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, ...] | None] = []

    async def fake_infer(
        self,
        task,
        start_time,
        system_prompt,
        human_prompt,
        *,
        clamp_to=None,
        force_route=None,
        force_effort=None,
    ):
        calls.append(clamp_to)
        return DispatchResult(
            decision=DispatchDecision(
                reasoning="EXEC with high tier",
                route="EXEC",
                effort="high",
            ),
            prompt=human_prompt,
            system_prompt=system_prompt,
            success=True,
        )

    monkeypatch.setattr(Dispatcher, "_infer_dispatch", fake_infer)

    result = await Dispatcher().run(_task(objective="Background objective"))

    assert calls == [("EXEC", "PLAN")]
    assert result.decision.route == "EXEC"
    assert result.decision.effort == "high"


def test_plan_route_forces_high_executor_tier():
    decision = DispatchDecision(
        reasoning="Needs a plan",
        route="PLAN",
        effort="standard",
    )

    Dispatcher._normalize_effort(decision)

    assert decision.effort == "high"


@pytest.mark.asyncio
async def test_hermes_agent_disables_plan_route(monkeypatch: pytest.MonkeyPatch):
    # Hermes has its own reasoning, memory, and skills, so the dispatcher does not offer the
    # Galaris planner for this driver.
    from types import SimpleNamespace

    calls: list[tuple[str, ...] | None] = []

    async def fake_infer(
        self,
        task,
        start_time,
        system_prompt,
        human_prompt,
        *,
        clamp_to=None,
        force_route=None,
        force_effort=None,
    ):
        calls.append(clamp_to)
        return DispatchResult(
            decision=DispatchDecision(
                reasoning="Hermes direct execution",
                route="EXEC",
                effort="standard",
            ),
            prompt=human_prompt,
            system_prompt=system_prompt,
            success=True,
        )

    monkeypatch.setattr(Dispatcher, "_infer_dispatch", fake_infer)

    task = _task(objective="Background objective")
    monkeypatch.setattr(task, "agent", SimpleNamespace(agent_driver="hermes"), raising=False)

    result = await Dispatcher().run(task)
    assert result.success is True
    assert result.decision.route == "EXEC"
    assert calls == [("EXEC",)]


@pytest.mark.asyncio
async def test_hermes_forced_plan_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    task = _task(objective="Background objective", forced_route="PLAN")
    monkeypatch.setattr(task, "agent", SimpleNamespace(agent_driver="hermes"), raising=False)

    result = await Dispatcher().run(task)

    assert result.success is False
    assert result.decision.route == "EXEC"
    assert "incompatible" in result.decision.reasoning


@pytest.mark.asyncio
async def test_soft_plan_directive_respects_driver_route_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A message tag cannot enable a pipeline stage absent from the driver spec."""

    from types import SimpleNamespace

    infer = AsyncMock(
        return_value=DispatchResult(
            decision=DispatchDecision(
                reasoning="Direct execution through the selected driver.",
                route="EXEC",
                effort="standard",
            ),
            prompt="@plan Build the artifact",
            success=True,
        )
    )
    monkeypatch.setattr(Dispatcher, "_infer_dispatch", infer)
    task = _task(objective="@plan Build the artifact")
    monkeypatch.setattr(task, "agent", SimpleNamespace(agent_driver="hermes"), raising=False)

    result = await Dispatcher().run(task)

    assert result.success is True
    assert result.decision.route == "EXEC"
    assert task.forced_route is None
    assert result.allowed_routes == ["EXEC"]
    assert any("unsupported" in note for note in result.policy_notes)
    assert infer.await_args.kwargs["clamp_to"] == ("EXEC",)


# Forced route and effort.


@pytest.mark.asyncio
async def test_fully_forced_task_skips_llm():
    # Forced route and effort yield a deterministic decision without LLM inference.
    task = _task(forced_route="EXEC", forced_effort="standard")

    result = await Dispatcher().run(task)

    assert result.success is True
    assert result.decision.route == "EXEC"
    assert result.decision.effort == "standard"
    assert result.cost == 0.0
    assert result.prompt == ""


@pytest.mark.asyncio
async def test_forced_plan_forces_high_effort_without_llm():
    # Forced PLAN implies high effort, so every field is decided without an LLM.
    task = _task(forced_route="PLAN")

    result = await Dispatcher().run(task)

    assert result.success is True
    assert result.decision.route == "PLAN"
    assert result.decision.effort == "high"
    assert result.cost == 0.0


@pytest.mark.asyncio
async def test_forced_route_exec_still_infers_effort(monkeypatch: pytest.MonkeyPatch):
    # With a forced route but automatic effort, inference still chooses effort while the gate
    # exposes only the forced route.
    captured: dict = {}

    async def fake_infer(
        self,
        task,
        start_time,
        system_prompt,
        human_prompt,
        *,
        clamp_to=None,
        force_route=None,
        force_effort=None,
    ):
        captured["clamp_to"] = clamp_to
        captured["force_route"] = force_route
        captured["force_effort"] = force_effort
        captured["system_prompt"] = system_prompt
        decision = DispatchDecision(reasoning="r", route="EXEC", effort="high")
        self._apply_forces(decision, force_route, force_effort)
        return DispatchResult(
            decision=decision, prompt=human_prompt, system_prompt=system_prompt, success=True
        )

    monkeypatch.setattr(Dispatcher, "_infer_dispatch", fake_infer)

    result = await Dispatcher().run(_task(forced_route="EXEC"))

    assert captured["clamp_to"] == ("EXEC",)
    assert captured["force_route"] == "EXEC"
    assert captured["force_effort"] is None
    assert "FORCED CHOICES" in captured["system_prompt"]
    assert result.decision.route == "EXEC"
    assert result.decision.effort == "high"


@pytest.mark.asyncio
@pytest.mark.parametrize("effort, should_infer", [("standard", False), ("high", True)])
async def test_forced_effort_infers_only_when_multiple_choices_remain(monkeypatch, effort, should_infer):
    inference = AsyncMock(return_value=DispatchResult(
        prompt="route", decision=DispatchDecision(route="EXEC", effort=effort),
    ))
    monkeypatch.setattr(Dispatcher, "_infer_dispatch", inference)
    result = await Dispatcher().run(_task(forced_effort=effort))
    assert result.success is True
    assert result.decision.effort == effort
    assert inference.await_count == int(should_infer)


@pytest.mark.asyncio
@pytest.mark.parametrize("route, effort", [("PLAN", "standard"), ("WEIRD", "high"), ("EXEC", "max")])
async def test_contradictory_or_unknown_constraints_fail_without_inference(monkeypatch, route, effort):
    inference = AsyncMock()
    monkeypatch.setattr(Dispatcher, "_infer_dispatch", inference)
    result = await Dispatcher().run(_task(forced_route=route, forced_effort=effort))
    assert result.success is False
    inference.assert_not_awaited()


def test_apply_forces_overrides_decision():
    decision = DispatchDecision(reasoning="r", route="PLAN", effort="high")
    Dispatcher._apply_forces(decision, "EXEC", "standard")
    assert decision.route == "EXEC"
    assert decision.effort == "standard"


@pytest.mark.asyncio
async def test_conversation_burst_guard_can_still_route_end() -> None:
    import time as _time

    now = int(_time.time())
    messages = [
        _ai_message(f"m{i}", time=now)
        for i in range(dispatcher_mod.AI_BURST_MAX + 1)
    ]
    task = _task(
        data={"sender_is_ai": True},
        messages=messages,
        message_group_id="room1",
        message_platform="talk",
    )

    result = await Dispatcher().run_conversation(task)

    assert result.decision.route == "END"
    assert result.allowed_routes == ["END"]


def test_conversation_ai_exchange_depth_counts_current_thread() -> None:
    assert Dispatcher._ai_exchange_depth(
        _task(messages=[_ai_message(f"a{i}") for i in range(3)])
    ) == 3
    assert Dispatcher._ai_exchange_depth(
        _task(
            messages=[
                _ai_message("a0"),
                _message("h", "hello", sender_id="nicolas"),
                _ai_message("a1"),
                _ai_message("a2"),
            ]
        )
    ) == 2


@pytest.mark.asyncio
async def test_conversation_depth_cap_routes_end_without_task_execution() -> None:
    messages = [
        _ai_message(f"a{i}") for i in range(dispatcher_mod.AI_EXCHANGE_MAX_DEPTH)
    ]
    task = _task(
        data={"sender_is_ai": True},
        messages=messages,
        message_group_id="room1",
        message_platform="talk",
    )

    result = await Dispatcher().run_conversation(task)

    assert result.decision.route == "END"


@pytest.mark.asyncio
async def test_conversation_profile_only_allows_direct_standard_exec_or_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    round_id = uuid4()
    run_id = uuid4()

    async def fake_infer(
        self,
        task,
        start_time,
        system_prompt,
        human_prompt,
        **kwargs,
    ):
        captured.update(
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            **kwargs,
        )
        return DispatchResult(
            decision=DispatchDecision(
                reasoning="The peer asked a useful question.",
                route="EXEC",
                effort="high",
                language="fr",
            ),
            prompt=human_prompt,
            system_prompt=system_prompt,
            success=True,
        )

    monkeypatch.setattr(Dispatcher, "_infer_dispatch", fake_infer)
    # The dispatcher model is configured (gate check), and the messenger AI
    # gate stays enabled so inference runs.
    monkeypatch.setattr(
        dispatcher_mod,
        "has_agent_profile_model",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        dispatcher_mod.params_service,
        "get",
        AsyncMock(return_value="on"),
    )

    result = await Dispatcher().run_conversation(
        round_id=round_id,
        run_id=run_id,
        agent_id=7,
        language="fr",
        objective="[Collègue] Peux-tu confirmer ce point ?",
        messages=(
            {
                "id": "peer-1",
                "text": "Peux-tu confirmer ce point ?",
                "sender": {
                    "id": "peer",
                    "display_name": "Collègue",
                    "agent_id": 9,
                },
            },
        ),
        sender_is_ai=True,
    )

    assert result.decision.route == "EXEC"
    assert result.decision.effort == "standard"
    assert result.allowed_routes == ["EXEC", "END"]
    assert result.pipeline_policy == {
        "use_planner": False,
        "use_briefing": False,
        "briefing_efforts": [],
    }
    assert captured["clamp_to"] == ("EXEC", "END")
    assert captured["force_effort"] == "standard"
    assert captured["allow_end"] is True
    assert captured["record_task_trace"] is False
    assert captured["agent_run_id"] == run_id
    assert captured["conversation_round_id"] == round_id
    assert "cannot plan or decompose" in str(captured["system_prompt"])
    assert "PLAN" not in str(captured["system_prompt"])
    assert "Collègue: Peux-tu confirmer ce point ?" in str(captured["human_prompt"])


@pytest.mark.asyncio
@pytest.mark.parametrize("objective", ["Bonjour", "Crée un fichier HTML détaillé.", "Où en est la tâche ?"])
async def test_human_conversation_executes_without_dispatch_inference(
    monkeypatch: pytest.MonkeyPatch,
    objective: str,
) -> None:
    infer = AsyncMock(
        return_value=DispatchResult(
            decision=DispatchDecision(
                reasoning="The requested file needs durable background work.",
                route="EXEC",
                effort="standard",
                language="fr",
            ),
            prompt="Créer le fichier",
            success=True,
        )
    )
    monkeypatch.setattr(Dispatcher, "_infer_dispatch", infer)
    model_check = AsyncMock(return_value=True)
    agent_loader = AsyncMock()
    monkeypatch.setattr(
        dispatcher_mod,
        "has_agent_profile_model",
        model_check,
    )

    result = await Dispatcher().run_conversation(
        round_id=uuid4(),
        run_id=uuid4(),
        agent_id=7,
        language="fr",
        objective=objective,
        messages=(),
        sender_is_ai=False,
        agent_loader=agent_loader,
    )

    assert result.decision.route == "EXEC"
    assert result.decision.effort == "standard"
    assert result.allowed_routes == ["EXEC"]
    assert result.decision.language == "fr"
    assert result.cost == 0
    infer.assert_not_awaited()
    model_check.assert_not_awaited()
    agent_loader.assert_not_awaited()


@pytest.mark.asyncio
async def test_conversation_profile_keeps_current_attachment_in_dispatch_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_id = uuid4()
    attachment_uri = f"chat://chat:direct:1:7/{file_id}"
    captured: dict[str, str] = {}

    async def fake_infer(
        _self: Dispatcher,
        _task: object,
        _start_time: float,
        _system_prompt: str,
        human_prompt: str,
        **_kwargs: object,
    ) -> DispatchResult:
        captured["human_prompt"] = human_prompt
        return DispatchResult(
            decision=DispatchDecision(
                reasoning="The attached video requires durable background work.",
                route="EXEC",
                effort="standard",
                language="fr",
            ),
            prompt=human_prompt,
            success=True,
        )

    monkeypatch.setattr(Dispatcher, "_infer_dispatch", fake_infer)
    monkeypatch.setattr(
        dispatcher_mod,
        "has_agent_profile_model",
        AsyncMock(return_value=True),
    )

    await Dispatcher().run_conversation(
        round_id=uuid4(),
        run_id=uuid4(),
        agent_id=7,
        language="fr",
        objective="[Nicolas] Tu peux me transcrire cette vidéo stp ?",
        messages=(
            {
                "messenger_message_id": str(uuid4()),
                "external_message_id": "current-video-message",
                "text": "Tu peux me transcrire cette vidéo stp ?",
                "sender_display_name": "Nicolas",
                "attachments": [
                    {
                        "id": str(file_id),
                        "uri": attachment_uri,
                        "name": "entretien.mkv",
                        "mime": "video/x-matroska",
                        "size": 29_594_447,
                        "kind": "video",
                    }
                ],
            },
        ),
        sender_is_ai=True,
        agent=SimpleNamespace(),
    )

    assert "Tu peux me transcrire cette vidéo stp ?" in captured["human_prompt"]
    assert f"[file: entretien.mkv] {attachment_uri}" in captured["human_prompt"]


@pytest.mark.asyncio
async def test_conversation_plan_directive_is_preserved_without_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    infer = AsyncMock(
        return_value=DispatchResult(
            decision=DispatchDecision(
                reasoning="Direct execution.",
                route="EXEC",
                effort="standard",
                language="fr",
            ),
            prompt="@plan Créer la scène",
            success=True,
        )
    )
    monkeypatch.setattr(Dispatcher, "_infer_dispatch", infer)
    monkeypatch.setattr(
        dispatcher_mod,
        "has_agent_profile_model",
        AsyncMock(return_value=True),
    )

    result = await Dispatcher().run_conversation(
        round_id=uuid4(),
        run_id=uuid4(),
        agent_id=7,
        language="fr",
        objective="@plan Créer la scène 3D de la Tour Eiffel.",
        messages=(),
        sender_is_ai=False,
        agent=SimpleNamespace(),
    )

    assert result.decision.route == "EXEC"
    assert result.conversation_route_directive == "PLAN"
    assert result.cost == 0.0
    infer.assert_not_awaited()


@pytest.mark.asyncio
async def test_conversation_profile_executes_directly_without_dispatcher_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dispatcher_mod, "has_agent_profile_model", AsyncMock(return_value=False))
    infer = AsyncMock()
    monkeypatch.setattr(Dispatcher, "_infer_dispatch", infer)
    monkeypatch.setattr(
        dispatcher_mod.params_service,
        "get",
        AsyncMock(side_effect=["on", None]),
    )

    result = await Dispatcher().run_conversation(
        round_id=uuid4(),
        run_id=uuid4(),
        agent_id=7,
        language="fr",
        objective="Peux-tu répondre ?",
        messages=(
            {
                "id": "peer-1",
                "text": "Peux-tu répondre ?",
                "sender": {"id": "peer", "agent_id": 9},
            },
        ),
        sender_is_ai=True,
    )

    assert result.decision.route == "EXEC"
    assert result.decision.effort == "standard"
    assert result.allowed_routes == ["EXEC"]
    assert "No dispatcher model is configured" in result.decision.reasoning
    infer.assert_not_awaited()


# @tag directives.


def test_message_tags_applied_from_current_message():
    task = _task(
        data={"text": "@exec @standard Summarize the room"},
        message_group_id="room1",
        message_platform="talk",
    )
    applied = Dispatcher()._apply_message_tags(task)
    assert set(applied) == {"@exec", "@standard"}
    assert task.forced_route == "EXEC"
    assert task.forced_effort == "standard"


def test_message_tags_ignored_for_ai_sender():
    task = _task(data={"text": "@approve @exec go ahead", "sender_is_ai": True})
    assert Dispatcher()._apply_message_tags(task) == []
    assert task.forced_route is None
    assert not task.auto_approve


def test_message_tags_contradictory_and_email_safe():
    # Ignore contradictory tags; email@exec.com is not a tag.
    task = _task(data={"text": "@exec @plan @high @standard go ahead"})
    assert Dispatcher()._apply_message_tags(task) == []
    assert task.forced_route is None
    assert task.forced_effort is None

    task2 = _task(data={"text": "write to contact@plan.com please"})
    assert Dispatcher()._apply_message_tags(task2) == []
    assert task2.forced_route is None


def test_message_tags_do_not_override_creation_forcing():
    task = _task(forced_route="PLAN", data={"text": "@exec @high quickly"})
    applied = Dispatcher()._apply_message_tags(task)
    assert applied == ["@high"]
    assert task.forced_route == "PLAN"
    assert task.forced_effort == "high"


@pytest.mark.asyncio
async def test_tags_fully_forcing_skip_llm():
    # @exec plus @standard leaves nothing to decide, so no LLM call occurs.
    task = _task(
        data={"text": "@exec @standard answer simply"},
        message_group_id="room1",
        message_platform="talk",
    )
    result = await Dispatcher().run(task)
    assert result.success is True
    assert result.decision.route == "EXEC"
    assert result.decision.effort == "standard"
    assert result.cost == 0.0


@pytest.mark.asyncio
async def test_plan_tag_in_objective_skips_llm():
    # In a background objective, @plan forces deterministic high-effort PLAN routing.
    task = _task(objective="@plan Completely redesign the public website")
    result = await Dispatcher().run(task)
    assert result.decision.route == "PLAN"
    assert result.decision.effort == "high"
    assert result.cost == 0.0
    assert task.forced_route == "PLAN"


@pytest.mark.asyncio
async def test_approve_tag_sets_auto_approve_and_still_infers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # @approve alone enables auto_approve, but the LLM still decides route and effort.
    called = {"infer": False}

    async def fake_infer(
        self,
        task,
        start_time,
        system_prompt,
        human_prompt,
        *,
        clamp_to=None,
        force_route=None,
        force_effort=None,
    ):
        called["infer"] = True
        return DispatchResult(
            decision=DispatchDecision(reasoning="r", route="EXEC", effort="standard"),
            prompt=human_prompt,
            system_prompt=system_prompt,
            success=True,
        )

    monkeypatch.setattr(Dispatcher, "_infer_dispatch", fake_infer)

    task = _task(
        data={"text": "@approve deploy the new version"},
        message_group_id="room1",
        message_platform="talk",
    )
    result = await Dispatcher().run(task)

    assert called["infer"] is True
    assert task.auto_approve is True
    assert result.decision.route == "EXEC"
