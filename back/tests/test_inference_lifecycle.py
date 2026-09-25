import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from core.database import get_db_session
from app.llm import llm_call_service
from app.llm import inference_execution as execution, inference_store as store
from app.llm.call_capture import InferenceOwner, inference_owner
from app.llm.facade import (
    start_inference,
    read_inference,
    control_inference,
    stream_inference,
    read_inference_result,
)
from app.llm.models import LLMCall, LLMInference, LLMInferenceAttempt
from app.llm.inference_journal import append_events
from tests.test_text_inference import configure_provider, request_for


@pytest_asyncio.fixture
async def runtime(committed_database, monkeypatch, responses_sse):
    monkeypatch.setattr(llm_call_service, "AsyncSessionLocal", committed_database)
    async with get_db_session() as db:
        llm, requests, mode = await configure_provider(db, monkeypatch, responses_sse)
        try:
            yield db, llm, requests, mode
        finally:
            await execution.stop()


async def state(key, expected):
    async with asyncio.timeout(10):
        while True:
            snapshot = await read_inference(key)
            if snapshot.status == expected:
                return snapshot
            if snapshot.status == "failed":
                pytest.fail(str(snapshot.attempts[-1].result))
            await asyncio.sleep(0.02)


@pytest.mark.asyncio
@pytest.mark.parametrize("native_protocol", [False, True])
async def test_pause_silent_provider_resume_and_replay_keep_attempts_and_accounting(runtime, native_protocol):
    db, llm, requests, mode = runtime
    mode["gate"] = asyncio.Event()
    request = request_for(llm)
    if native_protocol:
        from app.llm.contracts import ProtocolInferenceRequest

        request = ProtocolInferenceRequest(
            llm_id=llm.id, prompt=request.prompt, purpose=request.purpose,
            protocol="chat", body={"model": llm.code, "stream": True,
                "messages": [{"role": "user", "content": request.prompt}]},
        )
    key = await start_inference(request)
    stream = stream_inference(key)
    first = await asyncio.wait_for(anext(stream), 10)
    assert first.message.content == "Je réfléchis."
    command_id = uuid4()
    await control_inference(key, "pause", command_id=command_id)
    paused = await state(key, "paused")
    receipt = await control_inference(key, "pause", command_id=command_id)
    assert receipt.applied_at is not None
    tail = [event async for event in stream]
    assert tail[-1].kind == "result" and not tail[-1].result.success
    assert [event.kind for event in tail].count("result") == 1
    assert paused.attempts[0].result.messages[0].content == "Je réfléchis."
    assert len(requests) == 1

    mode["gate"].set()
    resume_id = uuid4()
    await control_inference(key, "resume", command_id=resume_id)
    await control_inference(key, "resume", command_id=resume_id)
    completed = await state(key, "completed")
    assert len(completed.attempts) == 2
    assert completed.attempts[0] == paused.attempts[0]
    assert completed.attempts[1].result.result == "Bonjour !"
    events = [event async for event in stream_inference(key)]
    assert [event.kind for event in events].count("result") == 1
    assert events[-1].kind == "result"
    assert len(requests) == 2
    assert requests[0]["messages"] == requests[1]["messages"]
    calls = list(await db.scalars(select(LLMCall)))
    assert completed.cost == pytest.approx(sum(call.cost for call in calls))

    replay_command = uuid4()
    replay = await control_inference(key, "replay", command_id=replay_command)
    assert (
        await control_inference(key, "replay", command_id=replay_command)
    ).replay_id == replay.replay_id
    repeated = await state(replay.replay_id, "completed")
    assert repeated.replay_of_id == key
    assert await read_inference(key) == completed
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_queued_stop_and_duplicate_admission_never_contact_provider(runtime):
    _, llm, requests, _ = runtime
    request = request_for(llm)
    key = uuid4()
    await execution.transaction(lambda: store.create(request, inference_id=key))
    await control_inference(key, "stop")
    await start_inference(request, inference_id=key)
    snapshot = await state(key, "stopped")
    assert len(snapshot.attempts) == 1
    assert [event.kind async for event in stream_inference(key)] == ["result"]
    assert requests == []
    with pytest.raises(ValueError):
        await start_inference(
            request.model_copy(update={"prompt": "Another request"}), inference_id=key
        )
    with pytest.raises(ValueError):
        await control_inference(key, "resume")


@pytest.mark.asyncio
async def test_concurrent_executors_claim_only_one_provider_request(runtime):
    _, llm, requests, _ = runtime
    key = await execution.transaction(lambda: store.create(request_for(llm)))
    await asyncio.gather(execution.execute(key), execution.execute(key))
    result = await read_inference(key)
    assert result.status == "completed"
    assert len(requests) == 1
    assert len(result.attempts[0].call_ids) == 1


@pytest.mark.asyncio
async def test_stop_between_call_admission_and_provider_send_closes_physical_trace(
    runtime, monkeypatch
):
    _, llm, requests, _ = runtime
    admitted = asyncio.Event()

    async def publish(channel, event, *_args):
        if channel == "llm_call" and event == "create":
            admitted.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(llm_call_service.websocket, "emit", publish)
    key = await start_inference(request_for(llm))
    await asyncio.wait_for(admitted.wait(), 10)
    await control_inference(key, "stop")
    stopped = await state(key, "stopped")
    call_id = stopped.attempts[0].call_ids[0]
    async with get_db_session():
        call = await llm_call_service.get_call(call_id)
        assert call.status == "cancelled"
        assert (await read_inference_result(call_id)).success is False
    assert not requests


@pytest.mark.asyncio
async def test_waiting_consumer_survives_pause_and_disconnect_does_not_cancel_work(
    runtime, monkeypatch
):
    from app.llm.retention import prune_traces
    from core.params import runtime_settings

    db, llm, requests, mode = runtime
    mode["gate"] = asyncio.Event()
    consumer = asyncio.create_task(execution.run_text(request_for(llm)))
    async with asyncio.timeout(10):
        key = None
        while key is None:
            key = await db.scalar(select(LLMInference.id))
            await asyncio.sleep(0.02)
    stream = stream_inference(key)
    first = await anext(stream)
    await stream.aclose()
    call = await db.get(LLMCall, first.call_id)
    call.updated_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db.commit()
    assert await llm_call_service.reconcile_stale_running_calls() == 0
    assert (await read_inference(key)).status == "running"
    await control_inference(key, "pause")
    await state(key, "paused")
    assert not consumer.done()
    # Durable inference history is not a disposable diagnostic trace.
    call = await db.get(LLMCall, first.call_id)
    call.completed_at = call.updated_at = datetime.now(timezone.utc) - timedelta(days=40)
    await db.commit()
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", 30)
    assert await prune_traces() == 0
    await llm_call_service.cleanup_all()
    with pytest.raises(llm_call_service.InferenceCallDeletionError):
        await llm_call_service.delete_call(first.call_id)
    assert (await read_inference_result(first.call_id)).messages[0].content == "Je réfléchis."
    await control_inference(key, "resume")
    mode["gate"].set()
    result = await asyncio.wait_for(consumer, 10)
    assert result.output == "Bonjour !" and len(result.messages) == 2
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_cancelling_waiting_consumer_acknowledges_stop_and_keeps_partial(runtime):
    db, llm, _, mode = runtime
    mode["gate"] = asyncio.Event()
    consumer = asyncio.create_task(execution.run_text(request_for(llm)))
    async with asyncio.timeout(10):
        key = None
        while key is None:
            key = await db.scalar(select(LLMInference.id))
            await asyncio.sleep(0.02)
    stream = stream_inference(key)
    await anext(stream)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(consumer, 10)
    stopped = await read_inference(key)
    assert stopped.status == "stopped"
    assert stopped.attempts[0].result.messages[0].content == "Je réfléchis."
    assert stopped.attempts[0].result.usage.requests == 1
    await stream.aclose()


@pytest.mark.asyncio
async def test_worker_shutdown_records_interruption_without_automatic_reexecution(runtime):
    _, llm, requests, mode = runtime
    mode["gate"] = asyncio.Event()
    key = await start_inference(request_for(llm))
    stream = stream_inference(key)
    await anext(stream)
    await asyncio.wait_for(execution.stop(), 10)
    snapshot = await read_inference(key)
    assert snapshot.status == "interrupted"
    assert snapshot.attempts[0].result.messages[0].content == "Je réfléchis."
    await execution.start()
    assert await execution.transaction(store.pending) == []
    assert len(requests) == 1
    mode["gate"].set()
    await control_inference(key, "resume")
    completed = await state(key, "completed")
    assert completed.attempts[0] == snapshot.attempts[0]
    assert len(requests) == 2
    await stream.aclose()


@pytest.mark.asyncio
async def test_execution_restores_saved_authority_instead_of_first_caller_context(runtime):
    from app.llm.subscription_policy import llm_execution_scope, SubscriptionAccessError
    from app.llm.tests.test_subscription_policy import _user

    db, llm, requests, _ = runtime
    owner = await _user(db, "durable-owner")
    other = await _user(db, "durable-other")
    llm.provider.catalog_code = "openai-codex"
    llm.provider.provider_type = "openai_codex"
    llm.provider.oauth_credentials = '{"access_token":"test-only-token"}'
    llm.provider.user_id = owner.id
    llm.provider.subscription_acknowledged = True
    await db.commit()
    # Start the shared worker from an unrelated authority. It must inherit none.
    with llm_execution_scope(requester_user_id=other.id, api_token_label="Unrelated client"):
        await execution.start()
        with pytest.raises(SubscriptionAccessError):
            await start_inference(request_for(llm))
    assert not requests
    with llm_execution_scope(requester_user_id=owner.id, api_token_label="Original client"):
        key = await start_inference(request_for(llm))
    completed = await state(key, "completed")
    call = await db.get(LLMCall, completed.attempts[0].call_ids[0])
    assert call.requester_user_id == owner.id
    assert call.api_token_label == "Original client"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_expired_lease_preserves_partial_rejects_late_writer_and_requires_resume(runtime):
    db, llm, requests, mode = runtime
    mode["gate"] = asyncio.Event()
    key = await start_inference(request_for(llm))
    stream = stream_inference(key)
    first = await asyncio.wait_for(anext(stream), 10)
    attempt = await db.get(LLMInferenceAttempt, first.attempt_id)
    old_owner = InferenceOwner(key, attempt.id, attempt.lease_token)
    await db.execute(
        update(LLMInferenceAttempt)
        .where(LLMInferenceAttempt.id == attempt.id)
        .values(
            lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    )
    await db.commit()
    await execution.transaction(store.recover_expired)
    interrupted = await state(key, "interrupted")
    assert interrupted.attempts[0].result.messages[0].content == "Je réfléchis."
    assert (await read_inference_result(first.call_id)).success is False
    assert len(requests) == 1
    token = inference_owner.set(old_owner)
    try:
        with pytest.raises(store.LostInferenceLease):
            await execution.transaction(
                lambda: append_events(
                    first.call_id,
                    [
                        {
                            "kind": "message",
                            "message": first.message.model_copy(
                                update={"content": "late"}
                            ).model_dump(mode="json"),
                        }
                    ],
                )
            )
    finally:
        inference_owner.reset(token)
    assert await read_inference(key) == interrupted
    assert (await anext(stream)).kind == "result"
    await stream.aclose()
    mode["gate"].set()
    await control_inference(key, "resume")
    completed = await state(key, "completed")
    assert len(completed.attempts) == 2
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("through_lab", [False, True])
async def test_real_lab_memory_extraction_keeps_validation_retries_and_cost(runtime, through_lab):
    # This guarantee moved from the text pilot suite: detached admission requires
    # independent committed connections rather than the rollback fixture.
    from app.lab.mechanism_registry import evaluate_mechanism, get_mechanism
    from app.dream.evaluation import evaluate_memory_extraction
    from app.llm.accounting_scope import llm_call_accounting
    from app.llm import llm_correlation_scope

    db, llm, requests, mode = runtime
    mode.update(outputs=["invalid JSON", '{"operations":[]}'])
    definition = get_mechanism("memory_extraction")
    input_data = {**definition.default_input, "current": [{"role": "human", "text": "Bonjour."}]}
    with llm_call_accounting() as accounting, llm_correlation_scope("lab-pilot"):
        if through_lab:
            output, cost = await evaluate_mechanism(definition, input_data=input_data, llm=llm)
        else:
            output, cost = await evaluate_memory_extraction(input_data=input_data, llm=llm)
    assert output == {"operations": [], "relevant_memory_ids": [], "ranked_memory_ids": []}
    assert len(requests) == 2
    assert "previous response was rejected" in requests[1]["messages"][0]["content"]
    calls = list(await db.scalars(select(LLMCall).order_by(LLMCall.started_at)))
    assert len(calls) == 2
    assert accounting.cost == cost == pytest.approx(sum(call.cost for call in calls))
    assert {call.correlation_ref for call in calls} == {"lab-pilot"}
    for call in calls:
        result = await read_inference_result(call.id)
        assert result is not None
        assert result.cost == call.cost
        assert result.metadata["llm_call_id"] == str(call.id)
        assert call.inference_attempt_id is not None
