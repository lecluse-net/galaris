from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import ExecutionResult
from app.agent.models import Agent, Title
from app.connection import Connection
from app.conversation import (
    ConversationRound,
    ConversationRoundMessage,
    ConversationTaskLink,
)
from app.dream import scheduler
from app.dream import monitoring_service
from app.dream.contracts import (
    DreamClaim,
    DreamMechanism,
    DreamPrepared,
    DreamRuntimeSnapshot,
    MemoryCreateOperation,
    MemoryExtractionDecision,
    MemoryExtractionExistingMemory,
    MemoryExtractionPrepared,
    MemoryLinkOperation,
)
from app.dream.mechanisms import task_memory
from app.dream.models import DreamReceipt
from app.dream.registry import register_mechanism, reset_registry
from app.dream.service import receipt_correlation_ref
from app.llm import LLMCall, profile_service
from app.llm.correlation import current_llm_correlation_ref
from app.memory.models import MemoryItem
from app.memory.storage import (
    NativeFileStorage,
    register_storage,
    reset_storage_registry,
)
from app.task.models import Task, TaskStatus
from app.messenger import Interaction, Message, Room
from app.tools.models import Tool
from app.topic.models import Topic
from core.authorize import Privileges
from core.database import get_db


class _AlwaysReadyMechanism:
    def __init__(self, key: str) -> None:
        self.key = key

    async def is_available(self) -> bool:
        return True

    async def count_pending(self) -> int:
        return 1

    async def claim_one(self) -> DreamClaim | None:
        return DreamClaim(
            receipt_id=uuid4(),
            lease_token=uuid4(),
            subject_kind="test",
            subject_id=self.key,
            attempts=1,
            prepared_payload=None,
        )

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        del claim
        return DreamPrepared(payload={})

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        del claim, payload
        return 0


class _AvailableWithoutWorkMechanism(_AlwaysReadyMechanism):
    async def count_pending(self) -> int:
        return 0

    async def claim_one(self) -> DreamClaim | None:
        return None


@pytest.mark.asyncio
async def test_run_claim_scopes_nested_llm_calls_to_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_refs: list[str | None] = []
    claim = DreamClaim(
        receipt_id=uuid4(),
        lease_token=uuid4(),
        subject_kind="message",
        subject_id=str(uuid4()),
        attempts=1,
        prepared_payload=None,
    )

    class _CorrelationMechanism(_AlwaysReadyMechanism):
        async def prepare(self, _claim: DreamClaim) -> DreamPrepared:
            observed_refs.append(current_llm_correlation_ref())
            return DreamPrepared(payload={})

    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(scheduler, "store_prepared", noop)
    monkeypatch.setattr(scheduler, "mark_success", noop)
    monkeypatch.setattr(scheduler, "has_active_voice_calls", lambda: False)
    monkeypatch.setattr(
        "app.memory.automation.enqueue_dream_link_reconciliation",
        noop,
    )

    await scheduler._run_claim(  # pyright: ignore[reportPrivateUsage]
        _CorrelationMechanism("topic.classify_message"),
        claim,
    )

    assert observed_refs == [receipt_correlation_ref(claim.receipt_id)]
    assert current_llm_correlation_ref() is None


@pytest.fixture
def dream_storage(tmp_path: Path) -> Path:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        yield tmp_path
    finally:
        reset_storage_registry()


async def _owner(db: AsyncSession) -> Agent:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Dream test {suffix}", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Dream",
        code=f"dream-{suffix}",
        agent_driver="internal",
    )
    db.add(owner)
    await db.flush()
    return owner


async def _terminal_task(
    db: AsyncSession,
    owner: Agent,
    *,
    label: str,
    objective: str = "Remember that answers must be concise. password=do-not-store",
    created_at: datetime | None = None,
    messenger_connection_id: int | None = None,
    message_platform: str | None = None,
    message_group_id: str | None = None,
) -> Task:
    task = Task(
        label=label,
        objective=objective,
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        created_at=created_at,
        messenger_connection_id=messenger_connection_id,
        message_platform=message_platform,
        message_group_id=message_group_id,
    )
    task.set_execution_result(
        ExecutionResult(
            prompt="Remember the preference.",
            result="The user prefers concise answers in French.",
            success=True,
        )
    )
    db.add(task)
    await db.flush()
    return task


@pytest.mark.asyncio
async def test_cycle_scans_exactly_one_task_and_checkpoints_memories(
    db: AsyncSession,
    dream_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del dream_storage
    owner = await _owner(db)
    topic = Topic(title="Concise communication")
    db.add(topic)
    await db.flush()
    source_date = datetime(2026, 6, 1, 8, 30, tzinfo=timezone.utc)
    first = await _terminal_task(
        db,
        owner,
        label="First terminal task",
        created_at=source_date,
        message_platform="nextcloud_talk",
        message_group_id="room-42",
    )
    second = await _terminal_task(
        db,
        owner,
        label="Second terminal task",
        objective="That worked; keep future answers just as concise.",
        created_at=source_date + timedelta(minutes=5),
        message_platform="nextcloud_talk",
        message_group_id="room-42",
    )
    first.topic_id = topic.id
    second.topic_id = topic.id
    first.data = {"language": "fr"}
    second.data = {"language": "fr"}
    await db.commit()

    captured_prompts: list[str] = []

    async def fake_resolve(_model_field: str, agent_id: int | None) -> object:
        assert agent_id == owner.id
        get_db()
        return object()

    async def fake_extract(**kwargs: Any) -> tuple[MemoryExtractionPrepared, float]:
        get_db()
        input_data = kwargs["input_data"]
        captured_prompts.append(
            f"{kwargs['language_instruction']}\n{input_data.model_dump_json()}"
        )
        if input_data.existing_memories:
            target = input_data.existing_memories[0].id
            return MemoryExtractionPrepared(
                decision=MemoryExtractionDecision(
                    operations=[MemoryLinkOperation(target_memory_id=target)]
                ),
                candidate_memory_ids=[UUID(target)],
            ), 0.0
        return MemoryExtractionPrepared(
            decision=MemoryExtractionDecision(
                operations=[
                    MemoryCreateOperation(
                        title="Concise French answers",
                        content="The user prefers concise answers in French.",
                        memory_type="core",
                        keywords=["French", "concise"],
                        retention_reason="explicit_user_preference",
                    )
                ]
            )
        ), 0.0

    async def fake_recall(*_args: Any, **_kwargs: Any) -> Any:
        memories = list(
            (
                await get_db().scalars(
                    select(MemoryItem).where(
                        MemoryItem.node_kind == "memory",
                        MemoryItem.source_managed.is_(False),
                    )
                )
            ).all()
        )
        return type(
            "RecallResult",
            (),
            {
                "hits": [
                    type(
                        "RecallHit",
                        (),
                        {
                            "item": type(
                                "RecallItem",
                                (),
                                {"id": item.id, "title": item.title},
                            )(),
                            "excerpt": item.search_text,
                        },
                    )()
                    for item in memories
                ]
            },
        )()

    def fake_existing_memories(
        hits: list[Any],
        *,
        owner_agent_id: int | None = None,
        source_text: str = "",
    ) -> list[MemoryExtractionExistingMemory]:
        assert owner_agent_id == owner.id
        assert source_text
        return [
            MemoryExtractionExistingMemory(
                id=str(hit.item.id),
                title=hit.item.title,
                content=hit.excerpt,
                memory_type="core",
            )
            for hit in hits
        ]

    monkeypatch.setattr(
        profile_service, "has_any_profile_value", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        task_memory.llm_service,
        "get_profile_llm_for_agent_id",
        fake_resolve,
    )
    monkeypatch.setattr(task_memory, "search_memory_detailed", fake_recall)
    monkeypatch.setattr(task_memory, "run_memory_extraction", fake_extract)
    monkeypatch.setattr(task_memory, "existing_memories_from_hits", fake_existing_memories)
    monkeypatch.setattr(scheduler, "has_active_voice_calls", lambda: False)
    monkeypatch.setattr(scheduler.runtime_settings, "DREAM_ENABLED", True)
    reset_registry()
    register_mechanism(task_memory.task_memory_mechanism)
    try:
        assert await scheduler.run_cycle() == 1
        receipts = list(
            (
                await db.scalars(
                    select(DreamReceipt).order_by(DreamReceipt.created_at)
                )
            ).all()
        )
        assert len(receipts) == 1
        assert receipts[0].subject_id == str(first.id)
        assert receipts[0].status == "success"
        assert receipts[0].result_count == 1
        assert receipts[0].prepared_payload is not None
        first_application = receipts[0].prepared_payload["application"]
        assert len(first_application["operations"]) == 1
        assert first_application["operations"][0]["action"] == "CREATE"
        assert first_application["operations"][0]["status"] == "stored"
        assert await db.scalar(
            select(func.count(MemoryItem.id)).where(
                MemoryItem.owner_agent_id == owner.id
            )
        ) == 1
        assert "do-not-store" not in captured_prompts[0]
        assert "password=[redacted]" in captured_prompts[0]
        assert "Required output language: French (fr)" in captured_prompts[0]
        assert "following_objective" in captured_prompts[0]
        assert "That worked; keep future answers just as concise." in captured_prompts[0]
        stored_item = await db.scalar(
            select(MemoryItem).where(MemoryItem.owner_agent_id == owner.id)
        )
        assert stored_item is not None
        assert stored_item.created_at == source_date
        assert stored_item.metadata_["language"] == "fr"

        assert await scheduler.run_cycle() == 1
        assert await db.scalar(select(func.count(DreamReceipt.id))) == 2
        assert await db.scalar(
            select(func.count(MemoryItem.id)).where(
                MemoryItem.owner_agent_id == owner.id
            )
        ) == 1
        second_receipt = await db.scalar(
            select(DreamReceipt)
            .where(DreamReceipt.id != receipts[0].id)
            .limit(1)
        )
        assert second_receipt is not None
        assert second_receipt.result_count == 1
        assert "existing_memories" in captured_prompts[1]
        assert "The user prefers concise answers in French." in captured_prompts[1]
        stored_item = await db.scalar(
            select(MemoryItem).where(MemoryItem.owner_agent_id == owner.id)
        )
        assert stored_item is not None
        assert stored_item.created_at == source_date
        subject_ids = set(
            (
                await db.scalars(select(DreamReceipt.subject_id))
            ).all()
        )
        assert subject_ids == {str(first.id), str(second.id)}

        assert await scheduler.run_cycle() == 0
        assert await db.scalar(select(func.count(DreamReceipt.id))) == 2
    finally:
        reset_registry()


@pytest.mark.asyncio
async def test_task_memory_waits_until_topic_classification_receipt_finishes(
    db: AsyncSession,
) -> None:
    owner = await _owner(db)
    topic = Topic(title="Dream dependency")
    db.add(topic)
    await db.flush()
    task = await _terminal_task(db, owner, label="Topic is being applied")
    task.topic_id = topic.id
    classification = DreamReceipt(
        mechanism_key="topic.classify_task",
        subject_kind="task",
        subject_id=str(task.id),
        status="running",
        attempts=1,
    )
    db.add(classification)
    await db.commit()

    assert await task_memory.task_memory_mechanism.count_pending() == 0

    classification.status = "success"
    await db.commit()

    assert await task_memory.task_memory_mechanism.count_pending() == 1


@pytest.mark.asyncio
async def test_task_memory_retry_waits_for_topic_classification(
    db: AsyncSession,
) -> None:
    owner = await _owner(db)
    task = await _terminal_task(
        db,
        owner,
        label="Unclassified terminal task",
        created_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
    receipt = DreamReceipt(
        mechanism_key=task_memory.task_memory_mechanism.key,
        subject_kind="task",
        subject_id=str(task.id),
        status="retry",
        attempts=0,
        available_at=datetime.now(timezone.utc),
    )
    db.add(receipt)
    await db.commit()

    claim = await task_memory.task_memory_mechanism.claim_one()
    assert claim is None


@pytest.mark.asyncio
async def test_task_memory_replays_legacy_success_without_application_proof(
    db: AsyncSession,
) -> None:
    owner = await _owner(db)
    topic = Topic(title="Legacy Dream replay")
    db.add(topic)
    await db.flush()
    task = await _terminal_task(db, owner, label="Prepared but never persisted")
    task.topic_id = topic.id
    receipt = DreamReceipt(
        mechanism_key=task_memory.task_memory_mechanism.key,
        subject_kind="task",
        subject_id=str(task.id),
        status="success",
        attempts=4,
        result_count=0,
        prepared_payload={
            "decision": {
                "operations": [
                    {
                        "action": "CREATE",
                        "title": "Validated decision",
                        "content": "The decision remains in force.",
                        "retention_reason": "explicit_decision_or_commitment",
                        "future_utility": "high",
                    }
                ]
            },
            "candidate_memory_ids": [],
        },
    )
    db.add(receipt)
    await db.commit()

    assert await task_memory.task_memory_mechanism.count_pending() == 1
    claim = await task_memory.task_memory_mechanism.claim_one()

    assert claim is not None
    assert claim.receipt_id == receipt.id
    assert claim.prepared_payload == receipt.prepared_payload
    assert claim.attempts == 1
    await db.refresh(receipt)
    assert receipt.status == "running"


@pytest.mark.asyncio
async def test_task_memory_ignores_ineligible_tasks(
    db: AsyncSession,
) -> None:
    owner = await _owner(db)
    topic = Topic(title="Unowned task topic")
    db.add(topic)
    await db.flush()
    parent = await _terminal_task(db, owner, label="Parent task")
    parent.topic_id = topic.id
    child = await _terminal_task(db, owner, label="Documentary child task")
    child.topic_id = topic.id
    child.parent_id = parent.id
    opted_out = await _terminal_task(db, owner, label="Opted-out task")
    opted_out.topic_id = topic.id
    opted_out.data = {"memory_capture": False}
    failed = Task(
        label="Failed task",
        objective="A failure is not ordinary durable memory.",
        status=TaskStatus.ERROR,
        agent_id=owner.id,
        topic_id=topic.id,
    )
    db.add(failed)
    await db.commit()

    assert await task_memory.task_memory_mechanism.count_pending() == 1
    claim = await task_memory.task_memory_mechanism.claim_one()
    assert claim is not None
    assert claim.subject_id == str(parent.id)


def test_task_memory_requires_explicit_high_future_utility() -> None:
    from app.dream.mechanisms.memory_extraction import (
        validate_memory_extraction_decision,
    )

    preference = MemoryCreateOperation(
        title="Preferred answer length",
        content="The user explicitly prefers concise answers.",
        retention_reason="explicit_user_preference",
        future_utility="high",
    )
    result = validate_memory_extraction_decision(
        MemoryExtractionDecision(operations=[preference]),
        allowed_memory_ids=set(),
    )

    assert result.operations == [preference]


@pytest.mark.asyncio
async def test_cycle_runs_one_operation_and_rotates_mechanisms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed: list[str] = []

    async def no_active_task_work() -> bool:
        return False

    async def fake_run_claim(
        mechanism: DreamMechanism,
        claim: DreamClaim,
    ) -> None:
        del claim
        completed.append(mechanism.key)

    monkeypatch.setattr(scheduler, "has_active_voice_calls", lambda: False)
    monkeypatch.setattr(scheduler, "has_active_task_work", no_active_task_work)
    monkeypatch.setattr(scheduler, "_run_claim", fake_run_claim)
    monkeypatch.setattr(scheduler.runtime_settings, "DREAM_ENABLED", True)
    monkeypatch.setattr(
        scheduler,
        "_next_mechanism_index",
        0,
    )
    reset_registry()
    register_mechanism(_AlwaysReadyMechanism("first"))
    register_mechanism(_AlwaysReadyMechanism("second"))
    try:
        assert await scheduler.run_cycle() == 1
        assert await scheduler.run_cycle() == 1
        assert await scheduler.run_cycle() == 1
    finally:
        reset_registry()

    assert completed == ["first", "second", "first"]


@pytest.mark.asyncio
@pytest.mark.parametrize("message_has_work", [True, False])
async def test_message_topic_classification_precedes_dependent_task_classification(
    monkeypatch: pytest.MonkeyPatch,
    message_has_work: bool,
) -> None:
    completed: list[str] = []

    async def no_active_task_work() -> bool:
        return False

    async def fake_run_claim(
        mechanism: DreamMechanism,
        claim: DreamClaim,
    ) -> None:
        del claim
        completed.append(mechanism.key)

    message_mechanism = (
        _AlwaysReadyMechanism("topic.classify_message")
        if message_has_work
        else _AvailableWithoutWorkMechanism("topic.classify_message")
    )
    monkeypatch.setattr(scheduler, "has_active_voice_calls", lambda: False)
    monkeypatch.setattr(scheduler, "has_active_task_work", no_active_task_work)
    monkeypatch.setattr(scheduler, "_run_claim", fake_run_claim)
    monkeypatch.setattr(scheduler.runtime_settings, "DREAM_ENABLED", True)
    monkeypatch.setattr(scheduler, "_next_mechanism_index", 1)
    reset_registry()
    register_mechanism(message_mechanism)
    register_mechanism(_AlwaysReadyMechanism("topic.classify_task"))
    register_mechanism(_AlwaysReadyMechanism("memory.extract_task"))
    try:
        assert await scheduler.run_cycle() == 1
    finally:
        reset_registry()

    assert completed == [
        "topic.classify_message" if message_has_work else "topic.classify_task"
    ]


@pytest.mark.asyncio
async def test_worker_starts_pause_after_operation_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def fake_cycle() -> int:
        events.extend(["operation_started", "operation_finished"])
        return 1

    async def stop_in_pause(*, full_operation_delay: bool) -> None:
        assert full_operation_delay is True
        events.append("pause_started")
        raise asyncio.CancelledError

    monkeypatch.setattr(scheduler, "run_cycle", fake_cycle)
    monkeypatch.setattr(
        scheduler,
        "_wait_for_next_cycle",
        stop_in_pause,
    )
    monkeypatch.setattr(scheduler, "_worker_started_event", None)
    monkeypatch.setattr(scheduler, "_stopping", False)

    with pytest.raises(asyncio.CancelledError):
        await scheduler._worker()  # pyright: ignore[reportPrivateUsage]

    assert events == [
        "operation_started",
        "operation_finished",
        "pause_started",
    ]


@pytest.mark.asyncio
async def test_full_operation_pause_ignores_early_wake_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    wake_event = asyncio.Event()
    wake_event.set()

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(scheduler, "_wake_event", wake_event)
    monkeypatch.setattr(
        scheduler.runtime_settings,
        "DREAM_POLL_SECONDS",
        30.0,
    )
    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)

    await scheduler._wait_for_next_cycle(  # pyright: ignore[reportPrivateUsage]
        full_operation_delay=True,
    )

    assert slept == [30.0]


@pytest.mark.asyncio
async def test_voice_activity_cancels_current_dream_work() -> None:
    started = asyncio.Event()

    async def work() -> None:
        started.set()
        await asyncio.Event().wait()

    current = asyncio.create_task(work())
    await started.wait()
    scheduler._current_work = current  # pyright: ignore[reportPrivateUsage]
    try:
        scheduler._on_voice_activity(True)  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(asyncio.CancelledError):
            await current
    finally:
        scheduler._current_work = None  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_start_confirms_worker_has_entered_its_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered_cycle = asyncio.Event()
    release_cycle = asyncio.Event()

    async def fake_reconcile() -> None:
        return None

    async def fake_cycle() -> int:
        entered_cycle.set()
        await release_cycle.wait()
        return 0

    monkeypatch.setattr(scheduler, "reconcile_expired_receipts", fake_reconcile)
    monkeypatch.setattr(scheduler, "register_default_mechanisms", lambda: None)
    monkeypatch.setattr(scheduler, "register_voice_activity_listener", lambda _listener: None)
    monkeypatch.setattr(scheduler, "unregister_voice_activity_listener", lambda _listener: None)
    monkeypatch.setattr(scheduler, "run_cycle", fake_cycle)
    try:
        await scheduler.start()
        assert scheduler.is_running()
        assert entered_cycle.is_set()
    finally:
        release_cycle.set()
        await scheduler.stop()


@pytest.mark.asyncio
async def test_monitoring_summarizes_and_searches_receipts(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await _owner(db)
    first = await _terminal_task(db, owner, label="Find this Dream task")
    second = await _terminal_task(db, owner, label="Other Dream task")
    first_receipt = DreamReceipt(
        mechanism_key="memory.extract_task",
        subject_kind="task",
        subject_id=str(first.id),
        status="success",
        attempts=1,
        result_count=0,
        cost=0.01,
        prepared_payload={
            "decision": {
                "operations": [
                    {
                        "action": "LINK",
                        "target_memory_id": str(uuid4()),
                        "reason": "The source confirms the durable preference.",
                    }
                ]
            }
        },
    )
    second_receipt = DreamReceipt(
        mechanism_key="memory.extract_task",
        subject_kind="task",
        subject_id=str(second.id),
        status="error",
        attempts=5,
        result_count=0,
        cost=0.02,
        last_error="Model output was invalid.",
    )
    applied_receipt = DreamReceipt(
        mechanism_key="memory.extract_task",
        subject_kind="task",
        subject_id=str(uuid4()),
        status="success",
        attempts=1,
        result_count=1,
        prepared_payload={
            "decision": {
                "operations": [
                    {
                        "action": "CREATE",
                        "title": "Persisted memory",
                        "content": "This operation has durable application proof.",
                        "retention_reason": "explicit_decision_or_commitment",
                        "future_utility": "high",
                    }
                ]
            },
            "application": {
                "operations": [
                    {
                        "operation_index": 0,
                        "action": "CREATE",
                        "memory_id": str(uuid4()),
                        "status": "stored",
                    }
                ]
            },
        },
    )
    unregistered_receipt = DreamReceipt(
        mechanism_key="test.unregistered",
        subject_kind="test",
        subject_id=str(first.id),
        status="success",
        attempts=1,
        result_count=1,
    )
    topic_receipt = DreamReceipt(
        mechanism_key="topic.classify_task",
        subject_kind="task",
        subject_id=str(first.id),
        status="success",
        attempts=1,
        result_count=1,
    )
    db.add_all(
        [
            first_receipt,
            second_receipt,
            applied_receipt,
            topic_receipt,
            unregistered_receipt,
        ]
    )
    await db.flush()
    dream_call = LLMCall(
        task_id=first.id,
        correlation_ref=receipt_correlation_ref(first_receipt.id),
        agent_id=owner.id,
        provider_name="Local",
        requested_model="gemma",
        effective_model="gemma-4b",
        status="completed",
        stream=True,
        request_messages=[],
        prompt="Extract durable memories.",
        system_prompt="Dream memory extraction.",
        response_text='{"memories": []}',
        reasoning="",
        tool_calls=[],
        usage={},
    )
    db.add(dream_call)
    await db.commit()

    async def fake_snapshot() -> DreamRuntimeSnapshot:
        return DreamRuntimeSnapshot(
            status="idle",
            phase="waiting",
            reason="no_eligible_subject",
            worker_running=True,
            current_mechanism=None,
            current_subject_kind=None,
            current_subject_id=None,
            last_cycle_at=None,
            last_cycle_finished_at=None,
            next_cycle_at=None,
            state_changed_at=None,
            cycle_count=0,
            last_error_type=None,
        )

    monkeypatch.setattr(monitoring_service, "runtime_snapshot", fake_snapshot)
    reset_registry()
    register_mechanism(task_memory.task_memory_mechanism)
    register_mechanism(_AlwaysReadyMechanism("topic.classify_task"))
    register_mechanism(_AlwaysReadyMechanism("test.second"))
    try:
        overview = await monitoring_service.get_overview()
    finally:
        reset_registry()
    assert overview.runtime.status == "idle"
    assert overview.total_operations == 6
    assert overview.completed_operations == 4
    assert overview.pending_operations == 2
    assert overview.terminal_tasks == 2
    assert overview.unscanned_tasks == 0
    assert overview.successful_receipts == 3
    assert overview.error_receipts == 1
    assert overview.memories_created == 1
    assert overview.memories_linked == 0
    assert overview.total_cost == pytest.approx(0.03)
    assert [item.mechanism_key for item in overview.mechanisms] == [
        "memory.extract_task",
        "topic.classify_task",
        "test.second",
    ]
    mechanism = overview.mechanisms[0]
    assert mechanism.mechanism_key == "memory.extract_task"
    assert set(mechanism.model_dump()) == {
        "mechanism_key",
        "pending",
        "running",
        "retry",
        "success",
        "error",
        "result_count",
        "cost",
    }
    assert mechanism.success == 2
    assert mechanism.result_count == 1
    assert mechanism.error == 1
    assert mechanism.pending == 0
    assert mechanism.running == 0
    assert mechanism.retry == 0
    assert overview.mechanisms[1].success == 1
    assert overview.mechanisms[1].result_count == 1
    assert overview.mechanisms[2].pending == 1

    page = await monitoring_service.list_receipts(
        page=1,
        page_size=50,
        search="Find this",
    )
    assert page.total == 2
    memory_item = next(
        item for item in page.items if item.mechanism_key == "memory.extract_task"
    )
    assert memory_item.task_label == "Find this Dream task"
    assert first.objective is not None
    assert memory_item.subject_preview == first.objective[:240]
    assert memory_item.agent_id == owner.id
    assert memory_item.result_count == 0
    assert set(memory_item.model_dump()) == {
        "id",
        "mechanism_key",
        "subject_kind",
        "subject_id",
        "status",
        "attempts",
        "result_count",
        "cost",
        "created_at",
        "updated_at",
        "available_at",
        "subject_preview",
        "task_label",
        "task_status",
        "agent_id",
    }

    detail = await monitoring_service.get_receipt(first_receipt.id)
    assert detail is not None
    assert detail.prepared_payload == first_receipt.prepared_payload
    assert detail.result_count == 0
    assert [call.id for call in detail.llm_calls] == [dream_call.id]


@pytest.mark.asyncio
async def test_monitoring_previews_and_searches_conversation_round_messages(
    db: AsyncSession,
) -> None:
    owner = await _owner(db)
    suffix = uuid4().hex[:10]
    tool = Tool(
        code=f"dream-monitoring-{suffix}",
        label="Dream monitoring",
        description="",
        connection_schema={},
    )
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=f"dream-room-{suffix}",
        label="Dream monitoring",
        kind="direct",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    message_text = "Début reconnaissable du round Dream. " + ("suite " * 80)
    message = Message(
        connection_id=connection.id,
        tool_id=tool.id,
        platform="telegram",
        remote_message_id=f"dream-message-{suffix}",
        direction="inbound",
        messenger_room_id=room.id,
        room_id=room.external_id,
        text=message_text,
    )
    round_ = ConversationRound(room_id=room.id, status="SUCCEEDED")
    db.add_all([message, round_])
    await db.flush()
    db.add_all(
        [
            ConversationRoundMessage(
                round_id=round_.id,
                message_id=message.id,
                role="input",
                response_sequence=None,
                sequence=1,
            ),
            DreamReceipt(
                mechanism_key="memory.extract_conversation_round",
                subject_kind="conversation_round",
                subject_id=str(round_.id),
                status="success",
                attempts=1,
                result_count=0,
                cost=0.0,
            ),
        ]
    )
    await db.commit()

    page = await monitoring_service.list_receipts(
        page=1,
        page_size=50,
        search="reconnaissable du round",
    )

    assert page.total == 1
    assert page.items[0].subject_preview == message_text[:240]


@pytest.mark.asyncio
async def test_topic_assignment_audit_follows_message_round_and_task_lineage(
    db: AsyncSession,
) -> None:
    owner = await _owner(db)
    suffix = uuid4().hex[:10]
    tool = Tool(
        code=f"topic-audit-{suffix}",
        label="Topic assignment audit",
        description="",
        connection_schema={},
    )
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=f"topic-audit-room-{suffix}",
        label="Topic audit",
        kind="direct",
        conversation_type="text",
    )
    dream_topic = Topic(title=f"Dream topic {suffix}")
    manual_topic = Topic(title=f"Manual topic {suffix}")
    db.add_all([room, dream_topic, manual_topic])
    await db.flush()
    message = Message(
        connection_id=connection.id,
        tool_id=tool.id,
        platform="internal",
        remote_message_id=f"topic-audit-message-{suffix}",
        direction="inbound",
        messenger_room_id=room.id,
        room_id=room.external_id,
        text="Keep discussing the release plan.",
        topic_id=dream_topic.id,
    )
    round_ = ConversationRound(
        room_id=room.id,
        status="SUCCEEDED",
        topic_id=dream_topic.id,
    )
    task = Task(
        label="Inherited Topic task",
        objective="Continue the release plan.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        topic_id=dream_topic.id,
    )
    db.add_all([message, round_, task])
    await db.flush()
    db.add_all(
        [
            ConversationRoundMessage(
                round_id=round_.id,
                message_id=message.id,
                role="input",
                response_sequence=None,
                sequence=1,
            ),
            ConversationTaskLink(
                round_id=round_.id,
                task_id=task.id,
                action_key=f"topic-audit:{suffix}",
            ),
            DreamReceipt(
                mechanism_key="topic.classify_message",
                subject_kind="message",
                subject_id=str(message.id),
                status="success",
                attempts=1,
                result_count=1,
                prepared_payload={
                    "decision": {
                        "action": "reuse",
                        "topic_id": str(dream_topic.id),
                        "confidence": 1.0,
                        "reason": "",
                    },
                    "diagnostics": {
                        "topic_id": str(dream_topic.id),
                        "resolution": "continuity",
                        "semantic_continuity": {
                            "same_topic_probability": 0.87,
                            "reason": "The message continues the same release plan.",
                            "same_topic": True,
                            "threshold": 0.55,
                            "version": "topic-continuity-decision:v1-heuristic",
                        },
                    },
                },
            ),
        ]
    )
    await db.commit()

    inherited = await monitoring_service.get_topic_assignment_audit(
        topic_id=dream_topic.id,
        subject_kind="task",
        subject_id=task.id,
    )
    assert inherited.origin == "dream"
    assert inherited.action == "continuity"
    assert inherited.reason == "The message continues the same release plan."
    assert inherited.confidence == pytest.approx(0.87)
    assert inherited.dream_subject_kind == "message"
    assert inherited.dream_subject_id == str(message.id)

    task.topic_id = manual_topic.id
    await db.commit()
    manual = await monitoring_service.get_topic_assignment_audit(
        topic_id=manual_topic.id,
        subject_kind="task",
        subject_id=task.id,
    )
    assert manual.origin == "manual"
    assert manual.dream_receipt_id is None


@pytest.mark.asyncio
async def test_topic_assignment_audit_marks_human_confirmed_dream_choice(
    db: AsyncSession,
) -> None:
    topic = Topic(title=f"Approved Dream topic {uuid4().hex[:10]}")
    db.add(topic)
    await db.flush()
    task = Task(
        label="Approved Topic task",
        objective="Use the approved thematic dossier.",
        status=TaskStatus.SUCCESS,
        topic_id=topic.id,
    )
    db.add(task)
    await db.flush()
    receipt = DreamReceipt(
        mechanism_key="topic.classify_task",
        subject_kind="task",
        subject_id=str(task.id),
        status="success",
        attempts=1,
        result_count=1,
        prepared_payload={
            "decision": {
                "action": "create",
                "topic_id": str(topic.id),
                "title": topic.title,
                "confidence": 0.78,
                "reason": "No existing dossier covers this durable subject.",
            }
        },
    )
    db.add(receipt)
    await db.flush()
    interaction = Interaction(
        reference=uuid4().hex[:12].upper(),
        kind="topic_creation_approval",
        status="RESOLVED",
        title="Approve Topic",
        metadata_={
            "subject_kind": "task",
            "subject_id": str(task.id),
            "idempotency_key": f"topic-approval:{receipt.id}",
            "topic_payload": receipt.prepared_payload,
        },
        resolution={
            "option_id": "create",
            "metadata": {},
            "text": "yes",
        },
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        resolved_at=datetime.now(timezone.utc),
    )
    db.add(interaction)
    await db.commit()

    audit = await monitoring_service.get_topic_assignment_audit(
        topic_id=topic.id,
        subject_kind="task",
        subject_id=task.id,
    )
    assert audit.origin == "dream"
    assert audit.action == "create"
    assert audit.human_confirmed is True
    assert audit.dream_receipt_id == receipt.id
    assert audit.reason == "No existing dossier covers this durable subject."


@pytest.mark.asyncio
async def test_monitoring_loads_explicitly_correlated_message_inference(
    db: AsyncSession,
) -> None:
    receipt = DreamReceipt(
        mechanism_key="topic.classify_message",
        subject_kind="message",
        subject_id=str(uuid4()),
        status="success",
        attempts=1,
        result_count=1,
        cost=0.0004,
    )
    db.add(receipt)
    await db.flush()
    correlated = LLMCall(
        correlation_ref=receipt_correlation_ref(receipt.id),
        provider_name="Local",
        requested_model="gemma",
        effective_model="gemma-4b",
        status="completed",
        stream=True,
        request_messages=[],
        prompt="Classify this message.",
        system_prompt="Classify the current message into a thematic dossier.",
        response_text='{"topic_id": null}',
        reasoning="",
        tool_calls=[],
        usage={},
        cost=0.0004,
    )
    unrelated = LLMCall(
        provider_name="Local",
        requested_model="gemma",
        effective_model="gemma-4b",
        status="completed",
        stream=True,
        request_messages=[],
        prompt="Unrelated inference.",
        system_prompt="Another taskless subsystem.",
        response_text="Done.",
        reasoning="",
        tool_calls=[],
        usage={},
        cost=0.0004,
    )
    db.add_all([correlated, unrelated])
    await db.commit()

    detail = await monitoring_service.get_receipt(receipt.id)

    assert detail is not None
    assert [call.id for call in detail.llm_calls] == [correlated.id]
    assert detail.llm_calls[0].correlation_ref == receipt_correlation_ref(receipt.id)


@pytest.mark.asyncio
async def test_monitoring_recovers_legacy_message_inference_from_closed_window(
    db: AsyncSession,
) -> None:
    started_at = datetime(2026, 8, 17, 9, 13, 20, tzinfo=timezone.utc)
    receipt = DreamReceipt(
        mechanism_key="topic.classify_message",
        subject_kind="message",
        subject_id=str(uuid4()),
        status="success",
        attempts=1,
        result_count=1,
        cost=0.0004,
        created_at=started_at,
        updated_at=started_at + timedelta(seconds=7),
    )
    legacy_call = LLMCall(
        provider_name="Local",
        requested_model="gemma",
        effective_model="gemma-4b",
        status="completed",
        stream=True,
        request_messages=[],
        prompt="Classify this message.",
        system_prompt="Classify the current message into a thematic dossier.",
        response_text='{"topic_id": null}',
        reasoning="",
        tool_calls=[],
        usage={},
        cost=0.0004,
        started_at=started_at + timedelta(seconds=1),
    )
    db.add_all([receipt, legacy_call])
    await db.commit()

    detail = await monitoring_service.get_receipt(receipt.id)

    assert detail is not None
    assert [call.id for call in detail.llm_calls] == [legacy_call.id]


@pytest.mark.asyncio
async def test_monitoring_filters_active_history_and_dates(
    db: AsyncSession,
) -> None:
    older = DreamReceipt(
        mechanism_key="memory.extract_task",
        subject_kind="task",
        subject_id=str(uuid4()),
        status="success",
        created_at=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
    )
    active = DreamReceipt(
        mechanism_key="memory.extract_task",
        subject_kind="task",
        subject_id=str(uuid4()),
        status="running",
        created_at=datetime(2026, 8, 2, 10, tzinfo=timezone.utc),
    )
    recent = DreamReceipt(
        mechanism_key="memory.extract_task",
        subject_kind="task",
        subject_id=str(uuid4()),
        status="error",
        created_at=datetime(2026, 8, 2, 18, tzinfo=timezone.utc),
    )
    db.add_all([older, active, recent])
    await db.commit()

    active_page = await monitoring_service.list_receipts(
        page=1,
        page_size=50,
        active=True,
    )
    assert active_page.total == 1
    assert active_page.items[0].id == active.id

    history_page = await monitoring_service.list_receipts(
        page=1,
        page_size=50,
        active=False,
        date_from=date(2026, 8, 2),
        date_to=date(2026, 8, 2),
    )
    assert history_page.total == 1
    assert history_page.items[0].id == recent.id


@pytest.mark.asyncio
async def test_runtime_state_change_emits_websocket_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str, dict[str, str]]] = []
    entered = asyncio.Event()
    release = asyncio.Event()
    received_latest = asyncio.Event()

    async def fake_emit(
        subject: str,
        action: str,
        data: dict[str, str],
        room: object = None,
    ) -> None:
        del room
        events.append((subject, action, data))
        if len(events) == 1:
            entered.set()
            await release.wait()
        else:
            received_latest.set()

    monkeypatch.setattr(scheduler.websocket, "emit", fake_emit)
    monkeypatch.setattr(scheduler, "_runtime_status", "stopped")
    monkeypatch.setattr(scheduler, "_runtime_phase", "stopped")
    monkeypatch.setattr(scheduler, "_runtime_reason", "not_started")
    monkeypatch.setattr(scheduler, "_next_cycle_at", None)
    monkeypatch.setattr(scheduler, "_last_error_type", None)
    monkeypatch.setattr(scheduler, "_runtime_update_task", None)
    monkeypatch.setattr(scheduler, "_runtime_update_pending", False)

    scheduler._set_runtime_state(  # pyright: ignore[reportPrivateUsage]
        status="idle",
        phase="waiting",
        reason="no_eligible_subject",
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        for _ in range(100):
            scheduler._set_runtime_state(status="idle", phase="checking", reason="checking_activity")
            scheduler._set_runtime_state(status="idle", phase="waiting", reason="no_eligible_subject")
        await asyncio.sleep(0.03)
        assert events == [("dream", "update", {"scope": "runtime"})]
        release.set()
        await asyncio.wait_for(received_latest.wait(), timeout=1)
        assert len(events) == 2
        snapshot = await scheduler.runtime_snapshot()
        assert snapshot.reason == "no_eligible_subject"
    finally:
        release.set()
        await scheduler.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("result_count", [0, 1])
async def test_unchanged_memory_scan_does_not_reconcile_the_graph(
    monkeypatch: pytest.MonkeyPatch, result_count: int,
) -> None:
    class Maintenance(_AlwaysReadyMechanism):
        async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
            return result_count

    mechanism = Maintenance("memory.maintain_findings")
    claim = await mechanism.claim_one()
    assert claim is not None
    completed = AsyncMock()
    reconcile = AsyncMock()
    monkeypatch.setattr(scheduler, "store_prepared", AsyncMock())
    monkeypatch.setattr(scheduler, "mark_success", completed)
    monkeypatch.setattr(scheduler, "has_active_voice_calls", lambda: False)
    monkeypatch.setattr("app.memory.automation.enqueue_dream_link_reconciliation", reconcile)
    try:
        await scheduler._run_claim(mechanism, claim)
        completed.assert_awaited_once_with(claim, result_count=result_count)
        assert reconcile.await_count == result_count
    finally:
        await scheduler.stop()


def test_monitoring_routes_require_task_access() -> None:
    from app.dream.router import (
        read_dream_overview,
        read_dream_receipt,
        read_dream_receipts,
        read_dream_runtime,
    )

    for endpoint in (
        read_dream_runtime,
        read_dream_overview,
        read_dream_receipt,
        read_dream_receipts,
    ):
        assert endpoint._authorize_meta["privileges"] == [Privileges.TASK_ACCESS]  # pyright: ignore[reportFunctionMemberAccess]


@pytest.mark.asyncio
async def test_monitoring_rejects_unauthenticated_requests(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/dream/overview")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_is_available_opens_its_own_db_session(db: AsyncSession) -> None:
    """The scheduler calls is_available() without an ambient DB session.

    The gate must open its own session before reading the current profile
    (real profile_service, no monkeypatch): regression guard against
    LookupError on the db_session ContextVar.
    """
    assert isinstance(
        await task_memory.task_memory_mechanism.is_available(), bool
    )
