from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import llm_call_service
from app.llm.models import LLMCall
from app.llm.purposes import LLMCallPurpose
from app.task import task_service
from app.task.models import Task, TaskStatus


class FakeDb:
    def __init__(self, call: object | None) -> None:
        self.call = call
        self.deleted: object | None = None
        self.committed = False

    async def get(self, model: object, call_id: object) -> object | None:
        return self.call

    async def scalar(self, query: object) -> object | None:
        return self.call

    async def delete(self, call: object) -> None:
        self.deleted = call

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_media_completion_survives_late_failure_and_duplicate_cost(db, monkeypatch):
    from app.llm.media_facade import finish_media_call
    from app.llm.media_contracts import MediaResult

    call = LLMCall(status="running", purpose="multimedia.audio_speak")
    db.add(call)
    await db.commit()
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())
    await finish_media_call(call.id, MediaResult(state="success", text="ready", cost=0.42))
    await finish_media_call(call.id, MediaResult(state="error", error="stale observation", cost=0.01))
    await finish_media_call(call.id, MediaResult(state="success", text="duplicate", cost=0.84))
    await db.refresh(call)
    assert call.status == "completed" and call.error is None
    assert call.response_text == "ready" and call.cost == pytest.approx(0.42)


@pytest.mark.asyncio
async def test_delete_call_deletes_and_emits_websocket(monkeypatch: pytest.MonkeyPatch) -> None:
    call_id = uuid4()
    call = LLMCall(id=call_id, agent_id=12)
    db = FakeDb(call)
    events: list[tuple[str, str, dict[str, str], object | None]] = []

    async def emit(channel: str, event: str, data: dict[str, str], room: object | None) -> None:
        events.append((channel, event, data, room))

    monkeypatch.setattr(llm_call_service, "get_db", lambda: db)
    monkeypatch.setattr(llm_call_service.websocket, "emit", emit)

    assert await llm_call_service.delete_call(call_id) is True
    assert db.deleted is call
    assert db.committed is True
    assert events == [("llm_call", "delete", {
        "id": str(call_id), "agent_id": 12, "task_id": None,
        "conversation_round_id": None, "process_run_id": None,
    }, None)]


@pytest.mark.asyncio
async def test_delete_call_returns_false_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDb(None)

    monkeypatch.setattr(llm_call_service, "get_db", lambda: db)

    assert await llm_call_service.delete_call(uuid4()) is False
    assert db.committed is False


def _history_call(call_id: UUID, started_at: datetime, status: str = "completed") -> LLMCall:
    return LLMCall(
        id=call_id,
        provider_name="test",
        requested_model="test-model",
        effective_model="test-model",
        status=status,
        stream=False,
        started_at=started_at,
    )


def _legacy_conversation_call(round_id: UUID) -> LLMCall:
    now = datetime.now(timezone.utc)
    call = _history_call(uuid4(), now)
    call.conversation_round_id = round_id
    call.purpose = LLMCallPurpose.AGENT_EXEC.value
    call.request_messages = []
    call.prompt = "Hello"
    call.system_prompt = "Conversation prompt"
    call.response_text = "Hi"
    call.reasoning = ""
    call.tool_calls = []
    call.usage = {}
    call.input_tokens = 0
    call.output_tokens = 0
    call.total_tokens = 0
    call.cache_read_tokens = 0
    call.cache_write_tokens = 0
    call.reasoning_tokens = 0
    call.cost = 0.0
    call.inference_cost = 0.0
    call.cost_estimated = True
    call.is_subscription = False
    call.duration = 0.0
    call.created_at = now
    call.updated_at = now
    return call


@pytest.mark.asyncio
async def test_serialize_calls_repairs_legacy_conversation_purposes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text_round_id = uuid4()
    audio_round_id = uuid4()

    class FakeRows:
        def all(self) -> list[tuple[UUID, UUID | None]]:
            return [(text_round_id, None), (audio_round_id, uuid4())]

    class SerializeDb:
        async def execute(self, _query: object) -> FakeRows:
            return FakeRows()

    monkeypatch.setattr(llm_call_service, "get_db", lambda: SerializeDb())

    serialized = await llm_call_service.serialize_calls(
        [
            _legacy_conversation_call(text_round_id),
            _legacy_conversation_call(audio_round_id),
        ]
    )

    assert [call.purpose for call in serialized] == [
        LLMCallPurpose.CONVERSATION_TEXT.value,
        LLMCallPurpose.CONVERSATION_AUDIO.value,
    ]


@pytest.mark.asyncio
async def test_paginate_history_is_newest_first_and_excludes_running(db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    oldest_id = uuid4()
    middle_id = uuid4()
    newest_id = uuid4()
    oldest = _history_call(oldest_id, now - timedelta(minutes=3))
    oldest.cost = 0.1
    oldest.inference_cost = 0.1
    middle = _history_call(middle_id, now - timedelta(minutes=2), status="error")
    middle.cost = 0.2
    middle.inference_cost = 0.2
    newest = _history_call(newest_id, now - timedelta(minutes=1))
    newest.cost = 0.3
    newest.inference_cost = 0.3
    running = _history_call(uuid4(), now, status="running")
    running.cost = 0.4
    running.inference_cost = 0.4
    db.add_all([oldest, middle, newest, running])
    await db.commit()

    first_page, total, summary = await llm_call_service.paginate_history(page=1, page_size=2)
    second_page, second_total, second_summary = await llm_call_service.paginate_history(
        page=2,
        page_size=2,
    )
    error_page, error_total, error_summary = await llm_call_service.paginate_history(
        page=1,
        page_size=2,
        errors_only=True,
    )

    assert total == second_total == 3
    assert [call.id for call in first_page] == [newest_id, middle_id]
    assert [call.id for call in second_page] == [oldest_id]
    assert summary == second_summary
    assert summary.running == 1
    assert summary.completed == 2
    assert summary.errors == 1
    assert summary.total_cost == pytest.approx(1.0)
    assert summary.total_inference_cost == pytest.approx(1.0)
    assert error_total == 1
    assert [call.id for call in error_page] == [middle_id]
    assert error_summary == summary


@pytest.mark.asyncio
async def test_list_running_calls_is_newest_first_and_excludes_history(db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    older_id = uuid4()
    newer_id = uuid4()
    db.add_all([
        _history_call(older_id, now - timedelta(minutes=2), status="running"),
        _history_call(uuid4(), now - timedelta(minutes=1), status="completed"),
        _history_call(newer_id, now, status="running"),
    ])
    await db.commit()

    calls = await llm_call_service.list_running_calls(limit=10)

    assert [call.id for call in calls] == [newer_id, older_id]


@pytest.mark.asyncio
async def test_reconcile_stale_call_preserves_accounting_and_recent_activity(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    stale = _history_call(
        uuid4(),
        now - timedelta(hours=2),
        status="running",
    )
    stale.updated_at = now - timedelta(hours=1)
    stale.response_text = "partial output"
    stale.usage = {"prompt_tokens": 120, "completion_tokens": 30}
    stale.input_tokens = 120
    stale.output_tokens = 30
    stale.total_tokens = 150
    stale.cost = 0.42
    recent = _history_call(
        uuid4(),
        now - timedelta(hours=2),
        status="running",
    )
    recent.updated_at = now - timedelta(minutes=1)
    db.add_all([stale, recent])
    await db.commit()
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())

    reconciled = await llm_call_service.reconcile_stale_running_calls(
        now=now,
        stale_after=timedelta(minutes=30),
    )

    assert reconciled == 1
    await db.refresh(stale)
    await db.refresh(recent)
    assert stale.status == "cancelled"
    assert stale.completed_at == now
    assert stale.response_text == "partial output"
    assert stale.usage == {"prompt_tokens": 120, "completion_tokens": 30}
    assert stale.input_tokens == 120
    assert stale.output_tokens == 30
    assert stale.total_tokens == 150
    assert stale.cost == pytest.approx(0.42)
    assert await db.get(LLMCall, stale.id) is stale
    assert recent.status == "running"

    # A detached finalizer can arrive after reconciliation without a terminal usage block.
    # It must not erase counters already captured by partial stream updates.
    await llm_call_service.finalize_call(
        stale.id,
        trace={},
        status="cancelled",
        error="late stream finalization",
    )
    await db.refresh(stale)
    assert stale.response_text == "partial output"
    assert stale.usage == {"prompt_tokens": 120, "completion_tokens": 30}
    assert stale.total_tokens == 150
    assert stale.cost == pytest.approx(0.42)


@pytest.mark.asyncio
async def test_finalize_subscription_call_keeps_comparable_inference_cost(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = _history_call(uuid4(), datetime.now(timezone.utc), status="running")
    call.is_subscription = True
    db.add(call)
    await db.commit()
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())

    await llm_call_service.finalize_call(
        call.id,
        trace={
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "cost": 0.42,
            }
        },
        raw_response='{"type":"response.completed"}',
        input_rate=2.0,
        output_rate=4.0,
    )

    await db.refresh(call)
    assert call.cost == 0.0
    assert call.inference_cost == pytest.approx(0.42)
    assert call.cost_estimated is False
    assert call.is_subscription is True
    assert call.raw_response == '{"type":"response.completed"}'


@pytest.mark.asyncio
async def test_deleting_task_cancels_call_without_deleting_token_history(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task(
        id=uuid4(),
        label="Completed Task",
        status=TaskStatus.SUCCESS,
        ai=True,
    )
    call = _history_call(uuid4(), datetime.now(timezone.utc), status="running")
    call.task_id = task.id
    call.usage = {"total_tokens": 77}
    call.input_tokens = 50
    call.output_tokens = 27
    call.total_tokens = 77
    call.cost = 0.19
    db.add(task)
    await db.flush()
    db.add(call)
    await db.commit()
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())

    assert await task_service.delete(task.id)

    retained = await db.get(LLMCall, call.id)
    assert retained is not None
    assert retained.status == "cancelled"
    assert retained.completed_at is not None
    assert retained.usage == {"total_tokens": 77}
    assert retained.input_tokens == 50
    assert retained.output_tokens == 27
    assert retained.total_tokens == 77
    assert retained.cost == pytest.approx(0.19)


@pytest.mark.asyncio
async def test_reconciler_detects_recent_call_linked_to_soft_deleted_task(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    task = Task(
        id=uuid4(),
        label="Deleted before trace finalization",
        status=TaskStatus.SUCCESS,
        ai=True,
    )
    call = _history_call(uuid4(), now, status="running")
    call.task_id = task.id
    db.add(task)
    await db.flush()
    db.add(call)
    await db.commit()
    task.soft_delete()
    await db.commit()
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())

    reconciled = await llm_call_service.reconcile_stale_running_calls(
        now=now,
        stale_after=timedelta(days=1),
    )

    assert reconciled == 1
    await db.refresh(call)
    assert call.status == "cancelled"
    assert call.error == "LLM trace stopped because its Task was deleted."


@pytest.mark.asyncio
async def test_reconciler_immediately_closes_agent_call_of_terminal_task(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    task = Task(
        id=uuid4(),
        label="Completed execution",
        status=TaskStatus.SUCCESS,
        ai=True,
    )
    call = _history_call(uuid4(), now - timedelta(minutes=1), status="running")
    call.task_id = task.id
    call.purpose = LLMCallPurpose.AGENT_EXEC
    call.updated_at = now
    db.add(task)
    await db.flush()
    db.add(call)
    await db.commit()
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())

    reconciled = await llm_call_service.reconcile_stale_running_calls(
        now=now,
        stale_after=timedelta(days=1),
    )

    assert reconciled == 1
    await db.refresh(call)
    assert call.status == "cancelled"
    assert call.error == (
        "LLM trace stopped after its Task reached terminal status SUCCESS."
    )


@pytest.mark.asyncio
async def test_call_date_range_is_inclusive_and_updates_global_summary(db: AsyncSession) -> None:
    completed = _history_call(
        uuid4(),
        datetime(2025, 2, 1, 0, 0, tzinfo=timezone.utc),
    )
    completed.cost = 0.1
    error = _history_call(
        uuid4(),
        datetime(2025, 3, 1, 23, 59, tzinfo=timezone.utc),
        status="error",
    )
    error.cost = 0.2
    running = _history_call(
        uuid4(),
        datetime(2025, 3, 2, 0, 0, tzinfo=timezone.utc),
        status="running",
    )
    running.cost = 0.4
    db.add_all([completed, error, running])
    await db.commit()

    calls, total, summary = await llm_call_service.paginate_history(
        page=1,
        page_size=10,
        date_from=date(2025, 2, 1),
        date_to=date(2025, 3, 1),
    )
    running_calls = await llm_call_service.list_running_calls(
        limit=10,
        date_from=date(2025, 2, 1),
        date_to=date(2025, 3, 1),
    )

    assert {call.id for call in calls} == {completed.id, error.id}
    assert total == 2
    assert summary.completed == 1
    assert summary.errors == 1
    assert summary.running == 0
    assert summary.total_cost == pytest.approx(0.3)
    assert running_calls == []


@pytest.mark.asyncio
async def test_serialize_call_includes_task_context_and_call_type(db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    task = Task(
        id=uuid4(),
        label="Composer le PDF",
        objective="<p>Contrôler l’illustration et composer le PDF final.</p>",
        status=TaskStatus.SUCCESS,
        ai=True,
    )
    call = _history_call(uuid4(), now)
    call.task_id = task.id
    call.purpose = LLMCallPurpose.AGENT_EXEC
    call.prompt = "<system-reminder>Skill catalogue reminder</system-reminder>"
    call.request_messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "Contrôler l’illustration"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}},
        ],
    }]
    db.add(task)
    await db.flush()
    db.add(call)
    await db.commit()

    payload = await llm_call_service.serialize_call(call)

    assert payload.task_label == "Composer le PDF"
    assert payload.task_status == TaskStatus.SUCCESS.value
    assert payload.prompt == "<p>Contrôler l’illustration et composer le PDF final.</p>"
    assert payload.call_type == "vision"
