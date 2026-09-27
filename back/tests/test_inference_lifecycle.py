import asyncio
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text, update

from core.database import get_db_session
from app.llm import llm_call_service
from app.llm import inference_execution as execution, inference_store as store
from app.llm import inference_notifications as notifications
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
async def test_commits_wake_every_reader_even_between_read_and_wait(runtime, monkeypatch):
    _, llm, _, mode = runtime
    mode["gate"] = asyncio.Event()
    monkeypatch.setattr(notifications, "RECONCILE_SECONDS", 60.0)
    key = await start_inference(request_for(llm))
    stream = stream_inference(key)
    first = await anext(stream)
    async with get_db_session() as db:
        attempt = await db.get(LLMInferenceAttempt, first.attempt_id)
        owner = InferenceOwner(key, attempt.id, attempt.lease_token)

    second = stream_inference(key, after_sequence=first.sequence)
    empty_reads = 0
    both_read = asyncio.Event()
    release = asyncio.Event()
    original = store.read_events

    async def read_then_pause(*args, **kwargs):
        nonlocal empty_reads
        batch = await original(*args, **kwargs)
        if not batch and empty_reads < 2:
            empty_reads += 1
            if empty_reads == 2:
                both_read.set()
            await release.wait()
        return batch

    monkeypatch.setattr(store, "read_events", read_then_pause)
    consumers = [asyncio.create_task(anext(reader)) for reader in (stream, second)]
    try:
        await asyncio.wait_for(both_read.wait(), 5)
        token = inference_owner.set(owner)
        try:
            async with get_db_session():
                await append_events(first.call_id, [{"kind": "message", "message":
                    first.message.model_copy(update={"content": "Committed during read"}).model_dump(mode="json"),
                }])
        finally:
            inference_owner.reset(token)
        release.set()
        received = await asyncio.wait_for(asyncio.gather(*consumers), 5)
        assert [item.message.content for item in received] == ["Committed during read"] * 2
        await stream.aclose()
        # Closing one subscriber must neither stop the provider nor detach the other.
        terminal = asyncio.create_task(anext(second))
        await control_inference(key, "stop")
        assert (await asyncio.wait_for(terminal, 5)).kind == "result"
    finally:
        release.set()
        for consumer in consumers:
            consumer.cancel()
        await asyncio.gather(*consumers, return_exceptions=True)
        await stream.aclose()
        await second.aclose()
    assert ("changes", key) not in notifications._subscribers


@pytest.mark.asyncio
async def test_silent_provider_commands_do_not_wait_for_heartbeat(runtime, monkeypatch):
    _, llm, _, mode = runtime
    mode["gate"] = asyncio.Event()
    monkeypatch.setattr(execution, "HEARTBEAT_SECONDS", 60.0)
    key = await start_inference(request_for(llm))
    stream = stream_inference(key)
    await anext(stream)
    try:
        async with asyncio.timeout(5):
            await control_inference(key, "pause")
            await state(key, "paused")
            await control_inference(key, "resume")
            await state(key, "running")
            await control_inference(key, "stop")
            await state(key, "stopped")
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_call_stop_preserves_trace_is_scoped_and_never_stops_a_new_attempt(runtime):
    _, llm, requests, mode = runtime
    mode["gate"] = asyncio.Event()
    key = await start_inference(request_for(llm))
    stream = stream_inference(key)
    first = await anext(stream)
    try:
        async with get_db_session():
            assert not await llm_call_service.stop_call(first.call_id, agent_ids=frozenset())
        assert (await read_inference(key)).status == "running"
        await control_inference(key, "pause")
        await state(key, "paused")
        await control_inference(key, "resume")
        second_stream = stream_inference(key)
        second = await anext(second_stream)
        try:
            async with get_db_session():
                assert await llm_call_service.stop_call(first.call_id)
            assert (await read_inference(key)).status == "running"
            async with get_db_session():
                assert await llm_call_service.stop_call(second.call_id)
            stopped = await state(key, "stopped")
            async with get_db_session():
                assert await llm_call_service.stop_call(second.call_id)
                call = await llm_call_service.get_call(second.call_id)
                assert call.status == "cancelled"
                assert call.completed_at is not None
                assert call.inference_attempt_id == second.attempt_id
                assert (await read_inference_result(second.call_id)).success is False
            assert (await read_inference(key)) == stopped
            assert len(requests) == 2
        finally:
            await second_stream.aclose()
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_call_stop_http_requires_edit_privilege_and_management_scope(runtime, monkeypatch):
    import importlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from fastapi import Depends, FastAPI, Request
    from core.authorize import GuardProvider, Privileges
    from app.llm import call_router

    _, llm, _, mode = runtime
    mode["gate"] = asyncio.Event()
    key = await start_inference(request_for(llm))
    stream = stream_inference(key)
    first = await anext(stream)
    guards_module = importlib.import_module("core.authorize.guard_provider")
    identity = SimpleNamespace(id=1, is_active=True)

    async def guard(request: Request):
        await guards_module.global_authorization_guard(request, current_user=identity)

    api = FastAPI(dependencies=[Depends(guard)])
    api.include_router(call_router.calls_router)
    guards = GuardProvider()
    guards.scan_app(api)
    monkeypatch.setattr(guards_module, "guard_provider", guards)
    privilege = AsyncMock(return_value=False)
    monkeypatch.setattr(guards_module, "check_privilege", privilege)
    scope = AsyncMock(return_value=SimpleNamespace(agent_ids=frozenset()))
    monkeypatch.setattr(call_router, "current_management_scope", scope)
    try:
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
            url = f"/llm-calls/{first.call_id}/stop"
            assert (await client.post(url)).status_code == 403
            assert privilege.await_args.args[1] == [Privileges.TASK_EDIT]
            privilege.return_value = True
            assert (await client.post(url)).status_code == 404
            assert (await read_inference(key)).status == "running"
            scope.return_value = SimpleNamespace(agent_ids=None)
            trace = (await client.get(f"/llm-calls/{first.call_id}")).json()
            assert trace["inference_attempt_id"] == str(first.attempt_id)
            assert (await client.post(url)).status_code == 202
            await state(key, "stopped")
            assert (await client.post(url)).status_code == 202
            assert (await client.delete(f"/llm-calls/{first.call_id}")).status_code == 409
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_stream_catches_up_after_a_missed_notification(runtime, monkeypatch):
    _, llm, requests, mode = runtime
    mode["gate"] = asyncio.Event()
    monkeypatch.setattr(notifications, "RECONCILE_SECONDS", 0.2)
    key = await start_inference(request_for(llm))
    stream = stream_inference(key)
    first = await anext(stream)
    async with get_db_session() as db:
        attempt = await db.get(LLMInferenceAttempt, first.attempt_id)
        owner = InferenceOwner(key, attempt.id, attempt.lease_token)
    token = inference_owner.set(owner)
    consumer = asyncio.create_task(anext(stream))
    try:
        # Lose every subsequent advisory signal: the durable cursor must still
        # catch up, without admitting another generation or duplicating a message.
        monkeypatch.setattr(notifications, "notify", lambda *_args: None)
        await asyncio.sleep(0.1)
        async with get_db_session():
            await append_events(first.call_id, [{"kind": "message", "message":
                first.message.model_copy(update={"content": "Recovered from journal"}).model_dump(mode="json"),
            }])
        recovered = await asyncio.wait_for(consumer, 5)
        assert recovered.message.content == "Recovered from journal"
        assert recovered.sequence > first.sequence
        assert len(requests) == 1
    finally:
        inference_owner.reset(token)
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        await stream.aclose()


@pytest.mark.asyncio
async def test_worker_drains_more_than_one_admission_page_without_polling(runtime):
    _, llm, requests, mode = runtime
    mode["concurrent"] = True
    # Existing committed work must be found at startup, even if its notifications
    # were emitted before any worker subscribed.
    keys = []
    async with get_db_session():
        for _ in range(store.PENDING_BATCH_SIZE + 1):
            keys.append(await store.create(request_for(llm)))
    await execution.start()
    async with asyncio.timeout(15):
        await asyncio.gather(*(state(key, "completed") for key in keys))
    assert len(requests) == len(keys)


@pytest.mark.asyncio
async def test_restart_recovers_all_expired_pages_without_reexecuting(runtime):
    from sqlalchemy import func

    _, llm, requests, _ = runtime
    keys = []
    async with get_db_session() as db:
        for _ in range(store.RECOVERY_BATCH_SIZE + 1):
            keys.append(await store.create(request_for(llm)))
        await db.execute(update(LLMInference).where(LLMInference.id.in_(keys)).values(status="running"))
        await db.execute(update(LLMInferenceAttempt).where(LLMInferenceAttempt.inference_id.in_(keys)).values(
            status="running", lease_token=uuid4(),
            lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
    await execution.start()
    async with asyncio.timeout(10):
        while True:
            async with get_db_session() as db:
                interrupted = await db.scalar(select(func.count()).select_from(LLMInference).where(
                    LLMInference.id.in_(keys), LLMInference.status == "interrupted",
                ))
            if interrupted == len(keys):
                break
            await asyncio.sleep(0.02)
    assert requests == []


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
async def test_silent_stream_does_no_sql_then_wakes_without_transferring_histories(runtime):
    db, llm, _, mode = runtime
    mode["gate"] = asyncio.Event()
    request = request_for(llm).model_copy(update={"prompt": "Synthetic context. " * 10_000})
    key = await start_inference(request)
    stream = stream_inference(key)
    first = await asyncio.wait_for(anext(stream), 10)
    async with get_db_session() as session:
        attempt = await session.get(LLMInferenceAttempt, first.attempt_id)
        owner = InferenceOwner(key, attempt.id, attempt.lease_token)
    transferred_histories = []
    idle_queries = []

    def observe_columns(_connection, cursor, _statement, _parameters, _context, _many):
        if "llm_inference" in _statement.lower() or "llm_call_event" in _statement.lower():
            idle_queries.append(_statement)
        columns = {column[0] for column in (cursor.description or [])}
        if columns & {"request", "request_messages", "prompt", "system_prompt"}:
            transferred_histories.append(columns)

    engine = db.bind.sync_engine
    event.listen(engine, "after_cursor_execute", observe_columns)
    token = inference_owner.set(owner)
    next_event = asyncio.create_task(anext(stream))
    try:
        # Let the initial read catch up, then measure the same silent interval
        # before/after the change. An idle subscriber must not scan PostgreSQL.
        await asyncio.sleep(0.1)
        idle_queries.clear()
        await asyncio.sleep(0.7)
        assert idle_queries == [], f"{len(idle_queries)} SQL statements while the provider was silent"
        assert await execution.transaction(lambda: store.heartbeat(owner)) == "running"
        async with get_db_session():
            await append_events(first.call_id, [{"kind": "message", "message":
                first.message.model_copy(update={"content": "Still progressing"}).model_dump(mode="json"),
            }])
        received = await asyncio.wait_for(next_event, 10)
        assert received.message.content == "Still progressing"
        assert transferred_histories == []
    finally:
        if not next_event.done():
            next_event.cancel()
        await asyncio.gather(next_event, return_exceptions=True)
        inference_owner.reset(token)
        event.remove(engine, "after_cursor_execute", observe_columns)
        mode["gate"].set()
        await state(key, "completed")
        await stream.aclose()


@pytest.mark.asyncio
async def test_trace_preparation_does_not_block_inference_journal(runtime, monkeypatch):
    _, llm, _, mode = runtime
    mode["gate"] = asyncio.Event()
    key = await start_inference(request_for(llm))
    stream = stream_inference(key)
    first = await asyncio.wait_for(anext(stream), 10)
    async with get_db_session() as db:
        attempt = await db.get(LLMInferenceAttempt, first.attempt_id)
        owner = InferenceOwner(key, attempt.id, attempt.lease_token)

    preparing = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = llm_call_service._compact_trace_output

    def prepare(trace):
        loop.call_soon_threadsafe(preparing.set)
        if not release.wait(10):
            raise TimeoutError("Test did not release trace preparation")
        return original(trace)

    monkeypatch.setattr(llm_call_service, "_compact_trace_output", prepare)
    finalizer = asyncio.create_task(
        llm_call_service.finalize_call(first.call_id, trace={})
    )
    try:
        await asyncio.wait_for(preparing.wait(), 10)
        token = inference_owner.set(owner)
        try:
            async with get_db_session() as db:
                await db.execute(text("SET LOCAL lock_timeout = '200ms'"))
                written = await append_events(first.call_id, [{
                    "kind": "message",
                    "message": first.message.model_copy(
                        update={"content": "Additional progress"}
                    ).model_dump(mode="json"),
                }])
            assert len(written) == 1
            assert await execution.transaction(lambda: store.heartbeat(owner)) == "running"
        finally:
            inference_owner.reset(token)
    finally:
        release.set()
        await asyncio.wait_for(finalizer, 10)
        await stream.aclose()
        await control_inference(key, "stop")
        await state(key, "stopped")


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
