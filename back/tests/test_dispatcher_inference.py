import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.dispatcher import Dispatcher
from app.connection import Connection
from app.conversation import ConversationRound, ConversationTaskLink
from app.llm.facade import (
    llm_call_accounting,
    read_inference,
    stream_inference,
    start_inference,
    control_inference,
)
from app.llm.models import LLMCall, LLMInference
from app.messenger import Room
from app.task.models import Task, TaskAttempt, TaskStatus
from tests import test_inference_lifecycle as lifecycle
from tests.test_conversation_concurrency import seed_round
from tests.test_text_inference import request_for

runtime = lifecycle.runtime


@pytest.mark.asyncio
async def test_single_choice_task_persists_dispatch_without_inference(runtime, monkeypatch):
    from dataclasses import replace
    from unittest.mock import AsyncMock
    from app.agent import dispatcher as dispatcher_module, dispatcher_service
    from app.agent.contracts import DriverPipelinePolicy
    from app.agent.registry import INTERNAL_HARNESS
    from app.task import task_service

    db, _llm, requests, _mode = runtime
    _context, _options, task_id, _attempt = await dispatch_context(db, "task")
    task = await task_service.get_by_id(task_id)
    spec = replace(INTERNAL_HARNESS, pipeline_policy=DriverPipelinePolicy(
        use_planner=False, use_briefing=False,
        execution_efforts=frozenset({"standard", "high"}),
        uses_llm_calls=False,
    ))
    monkeypatch.setattr(Dispatcher, "_task_executor_driver", staticmethod(lambda task: spec))
    model_check = AsyncMock(side_effect=AssertionError("No choice to infer"))
    monkeypatch.setattr(dispatcher_module, "has_agent_profile_model", model_check)

    result = await dispatcher_service.run(task)

    await db.refresh(task)
    assert task.get_dispatch_result() == result
    assert task.status == TaskStatus.DISPATCH
    assert task.effort == "standard"
    assert requests == []
    assert await db.scalar(select(LLMInference.id)) is None
    assert await db.scalar(select(LLMCall.id)) is None
    model_check.assert_not_awaited()


async def dispatch_context(db, kind):
    round_id = await seed_round()
    agent_id = await db.scalar(
        select(Connection.agent_id)
        .join(Room, Room.connection_id == Connection.id)
        .join(ConversationRound, ConversationRound.room_id == Room.id)
        .where(ConversationRound.id == round_id)
    )
    task_id, attempt_id = None, None
    if kind == "task":
        token = uuid4()
        task = Task(
            label="Dispatcher",
            objective="Répondre à Alice.",
            agent_id=agent_id,
            status=TaskStatus.DISPATCH,
            lease_token=token,
        )
        db.add(task)
        await db.flush()
        attempt = TaskAttempt(
            task_id=task.id, attempt_number=1, phase="DISPATCH", worker_id="test", lease_token=token
        )
        db.add_all(
            [attempt, ConversationTaskLink(round_id=round_id, task_id=task.id, action_key="test")]
        )
        await db.flush()
        task_id, attempt_id = task.id, attempt.id
        await db.commit()
    context = SimpleNamespace(
        id=task_id or round_id,
        agent_id=agent_id,
        data={"language": "fr"},
        reasoning_effort_override="low",
    )
    options = dict(
        record_task_trace=kind == "task",
        allow_end=kind == "ai",
        conversation_round_id=round_id,
        agent_run_id=uuid4(),
    )
    return context, options, task_id, attempt_id


@pytest.mark.asyncio
@pytest.mark.parametrize("kind, malformed", [
    ("task", False), ("task", True), ("ai", False), ("ai", True), ("human", False),
])
async def test_production_dispatch_preserves_protocol_fallback_and_durable_lineage(
    runtime, kind, malformed
):
    db, llm, requests, mode = runtime
    context, options, task_id, attempt_id = await dispatch_context(db, kind)
    if kind == "human":
        with llm_call_accounting() as accounting:
            result = await Dispatcher().run_conversation(
                round_id=options["conversation_round_id"],
                run_id=options["agent_run_id"],
                agent_id=context.agent_id,
                language="fr",
                objective="Répondre à Alice.",
                sender_is_ai=False,
            )
        assert result.success is True
        assert result.decision.route == "EXEC"
        assert result.decision.effort == "standard"
        assert result.decision.language == "fr"
        assert result.cost == accounting.cost == 0
        assert requests == []
        assert await db.scalar(select(LLMInference.id)) is None
        assert await db.scalar(select(LLMCall.id)) is None
        return
    route = "END" if kind == "ai" else "EXEC"
    mode.update(
        structured=True,
        outputs=["invalid JSON" if malformed else json.dumps({"route": route, "language": "FR"})]
        * 3,
    )
    with llm_call_accounting() as accounting:
        result = await Dispatcher()._infer_dispatch(
            context, 0.0, "Return a route.", "Répondre à Alice.", llm_override=llm, **options
        )
    assert result.success is True  # The advisory gate keeps its existing fallback contract.
    assert result.decision.route == route
    assert result.decision.effort == "standard"
    assert result.decision.language == "fr"
    assert bool(result.decision.reasoning) == malformed
    assert len(requests) == (2 if malformed and kind == "task" else 1)
    assert all(request["stream"] is True for request in requests)
    assert all(bool(request.get("tools")) == (kind == "task") for request in requests)
    key = await db.scalar(select(LLMInference.id))
    snapshot = await read_inference(key)
    assert snapshot.status == ("failed" if malformed else "completed")
    assert snapshot.request.task_id == task_id
    assert snapshot.request.agent_id == context.agent_id
    assert snapshot.request.agent_run_id == options["agent_run_id"]
    assert snapshot.request.conversation_round_id == options["conversation_round_id"]
    assert snapshot.request.reasoning_effort == "low"
    assert snapshot.request.parameters == {"temperature": 0.0, "max_tokens": 256}
    assert snapshot.request.output.mode == ("tool" if kind == "task" else "prompted")
    assert snapshot.request.output_retries == (None if kind == "task" else 0)
    calls = list(await db.scalars(select(LLMCall)))
    assert accounting.cost == snapshot.cost == pytest.approx(sum(call.cost for call in calls))
    if not malformed:
        assert result.cost == accounting.cost
    for call in calls:
        assert call.task_id == task_id
        assert call.task_attempt_id == attempt_id
        assert call.agent_id == context.agent_id
        assert call.agent_run_id == options["agent_run_id"]
        assert call.conversation_round_id == options["conversation_round_id"]
        assert call.inference_attempt_id == snapshot.attempts[0].id
    events = [event async for event in stream_inference(key)]
    assert sum(event.kind == "result" for event in events) == 1
    assert events[-1].result.success is not malformed
    assert (events[-1].result.structured_output is None) == malformed


@pytest.mark.asyncio
async def test_production_dispatch_keeps_forced_choices_above_inference(runtime):
    db, llm, _, mode = runtime
    context, options, _, _ = await dispatch_context(db, "task")
    mode.update(structured=True, outputs=['{"route":"PLAN","effort":"standard"}'])
    result = await Dispatcher()._infer_dispatch(
        context,
        0.0,
        "Return a route.",
        "Répondre.",
        llm_override=llm,
        force_route="EXEC",
        force_effort="high",
        **options,
    )
    assert result.decision.route == "EXEC"
    assert result.decision.effort == "high"
    key = await db.scalar(select(LLMInference.id))
    raw = (await read_inference(key)).attempts[0].result.structured_output
    assert raw["route"] == "PLAN" and raw["effort"] == "standard"


@pytest.mark.asyncio
async def test_cancelling_conversation_dispatch_stops_inference_without_a_fallback(runtime):
    db, llm, requests, mode = runtime
    context, options, _, _ = await dispatch_context(db, "ai")
    mode.update(structured=True, outputs=['{"route":"EXEC"}'], gate=asyncio.Event())
    consumer = asyncio.create_task(
        Dispatcher()._infer_dispatch(
            context,
            0.0,
            "Return a route.",
            "Répondre.",
            llm_override=llm,
            **options,
        )
    )
    async with asyncio.timeout(10):
        while not (key := await db.scalar(select(LLMInference.id))):
            await asyncio.sleep(0.02)
        stream = stream_inference(key)
        first = await anext(stream)
        assert first.message.content == "Je réfléchis."
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        tail = [event async for event in stream]
    assert len(requests) == 1
    assert tail[-1].result.success is False
    snapshot = await read_inference(key)
    assert snapshot.status == "stopped"
    assert snapshot.attempts[0].result.messages[0].content == "Je réfléchis."
    assert snapshot.attempts[0].result.structured_output is None


@pytest.mark.asyncio
async def test_foreground_dispatch_is_not_blocked_by_four_waiting_lab_inferences(runtime):
    db, llm, requests, mode = runtime
    context, options, _, _ = await dispatch_context(db, "ai")
    mode.update(concurrent=True, gate=asyncio.Event())
    keys = []
    for _ in range(4):
        key = await start_inference(request_for(llm))
        keys.append(key)
        stream = stream_inference(key)
        await asyncio.wait_for(anext(stream), 10)
        await stream.aclose()
    consumer = asyncio.create_task(
        Dispatcher()._infer_dispatch(
            context,
            0.0,
            "Return a route.",
            "Répondre.",
            llm_override=llm,
            **options,
        )
    )
    try:
        async with asyncio.timeout(5):
            while len(requests) < 5:
                await asyncio.sleep(0.02)
    finally:
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        for key in keys:
            await control_inference(key, "stop")
