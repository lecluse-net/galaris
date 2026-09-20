from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import ExecutionResult
from app.agent.models import Agent
from app.memory import acquisition_service, automation, service
from app.memory.contracts import SourceMemoryDocument
from app.memory.models import MemoryAcquisition, MemoryAutomationJob, MemoryItem
from app.memory.schemas import (
    MemoryAcquisitionCreate,
    MemoryItemCreate,
    MemoryPayload,
    MemorySimilarityCandidate,
)
from app.task.models import Task, TaskStatus
from core.params import runtime_settings
from core.util.rich_text import visible_text


@pytest.mark.asyncio
async def test_memory_acquisition_is_immediate_idempotent_and_attributable(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    data = MemoryAcquisitionCreate(
        agent_id=owner.id,
        title="User preference",
        content="The user prefers concise French answers.",
        source_kind="messenger",
        source_ref="message:42",
        metadata={"memory_type": "core"},
    )

    first = await acquisition_service.acquire_memory(data)
    second = await acquisition_service.acquire_memory(data)

    assert first.created and first.applied
    assert not second.created and not second.applied
    assert first.status == second.status == "stored"
    assert second.acquisition_id == first.acquisition_id
    assert first.memory_id is not None and second.memory_id == first.memory_id
    item, content, _access, _content_type, _media_type = await service.get_item(
        first.memory_id,
        agent_id=owner.id,
    )
    assert item.memory_type == "core"
    assert item.visibility == "private"
    assert visible_text(content.decode()) == "The user prefers concise French answers."
    candidate = await acquisition_service.get_acquisition_record(first.acquisition_id)
    assert candidate is not None
    assert candidate.status == "accepted"
    assert candidate.resolved_at is not None
    assert candidate.resolved_by is None


@pytest.mark.asyncio
async def test_explicit_forget_blocks_same_source_content_but_allows_correction(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    original = MemoryAcquisitionCreate(
        agent_id=owner.id,
        title="Obsolete preference",
        content="The user prefers weekly reports.",
        source_kind="task",
        source_ref="task:forget-regression",
    )
    acquired = await acquisition_service.acquire_memory(original)
    assert acquired.memory_id is not None

    await service.forget_item(
        acquired.memory_id,
        actor_agent_id=owner.id,
    )
    tombstone = await db.scalar(
        select(MemoryAcquisition).where(
            MemoryAcquisition.id == acquired.acquisition_id
        )
    )
    assert tombstone is not None
    assert tombstone.metadata_["forget_kind"] == "explicit"
    assert "forgotten_content_hash" in tombstone.metadata_
    relearned = await acquisition_service.acquire_memory(
        original.model_copy(
            update={"idempotency_key": f"retry-{uuid4().hex}"}
        )
    )
    corrected = await acquisition_service.acquire_memory(
        original.model_copy(
            update={
                "content": "The user prefers monthly reports.",
                "idempotency_key": f"correction-{uuid4().hex}",
            }
        )
    )

    assert relearned.status == "rejected"
    assert relearned.memory_id is None
    assert corrected.status == "stored"
    assert corrected.memory_id is not None


@pytest.mark.asyncio
async def test_new_acquisition_reports_merge_without_losing_its_idempotency_state(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    existing, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Stable preference",
            payload=MemoryPayload(text="Always answer in French."),
        )
    )
    data = MemoryAcquisitionCreate(
        agent_id=owner.id,
        title="Stable preference",
        content="Always answer in French.",
        source_kind="task",
        source_ref="task:deduplicated",
    )

    first = await acquisition_service.acquire_memory(data)
    second = await acquisition_service.acquire_memory(data)

    assert first.created and first.applied
    assert first.status == "merged"
    assert first.memory_id == existing.id
    assert not second.created and not second.applied
    assert second.status == "merged"
    assert second.acquisition_id == first.acquisition_id


@pytest.mark.asyncio
async def test_acquisition_uses_global_threshold_to_link_instead_of_create(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    existing, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Monthly reporting",
            payload=MemoryPayload(text="The reporting cadence is monthly."),
        )
    )
    monkeypatch.setattr(
        runtime_settings,
        "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD",
        0.99,
    )
    observed_thresholds: list[float | None] = []

    async def candidates(**kwargs: object) -> list[list[MemorySimilarityCandidate]]:
        observed_thresholds.append(
            cast(float | None, kwargs.get("minimum_similarity"))
        )
        return [[
            MemorySimilarityCandidate(
                memory_id=existing.id,
                revision=existing.revision,
                title=existing.title,
                memory_type="semantic",
                excerpt=existing.search_text,
                similarity=0.99,
            )
        ]]

    monkeypatch.setattr(
        acquisition_service,
        "find_similar_memory_candidates",
        candidates,
    )

    result = await acquisition_service.acquire_memory(
        MemoryAcquisitionCreate(
            agent_id=owner.id,
            title="Monthly reports",
            content="A report must be produced every month.",
            source_kind="task",
            source_ref="task:threshold-link",
        )
    )

    assert result.status == "merged"
    assert result.memory_id == existing.id
    assert observed_thresholds == [0.99]
    assert await db.scalar(select(func.count(MemoryItem.id))) == 1
    assert await service.source_refs(existing.id) == ["task:threshold-link"]


@pytest.mark.asyncio
async def test_manual_memory_creation_uses_the_same_global_merge_threshold(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    existing, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Monthly reporting",
            payload=MemoryPayload(text="The reporting cadence is monthly."),
        )
    )
    monkeypatch.setattr(
        runtime_settings,
        "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD",
        0.99,
    )
    observed_thresholds: list[float | None] = []

    async def candidates(**kwargs: object) -> list[list[MemorySimilarityCandidate]]:
        observed_thresholds.append(
            cast(float | None, kwargs.get("minimum_similarity"))
        )
        return [[
            MemorySimilarityCandidate(
                memory_id=existing.id,
                revision=existing.revision,
                title=existing.title,
                memory_type="semantic",
                excerpt=existing.search_text,
                similarity=0.99,
            )
        ]]

    monkeypatch.setattr(
        acquisition_service,
        "find_similar_memory_candidates",
        candidates,
    )

    item = await acquisition_service.create_manual_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Monthly reports",
            payload=MemoryPayload(text="A report must be produced every month."),
        )
    )

    assert item.id == existing.id
    assert observed_thresholds == [0.99]
    assert await db.scalar(select(func.count(MemoryItem.id))) == 1
    assert len(await service.source_refs(existing.id)) == 1


@pytest.mark.asyncio
async def test_acquisition_creates_when_no_candidate_reaches_global_threshold(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    monkeypatch.setattr(
        runtime_settings,
        "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD",
        0.99,
    )

    async def no_candidates(**_kwargs: object) -> list[list[MemorySimilarityCandidate]]:
        return [[]]

    monkeypatch.setattr(
        acquisition_service,
        "find_similar_memory_candidates",
        no_candidates,
    )

    result = await acquisition_service.acquire_memory(
        MemoryAcquisitionCreate(
            agent_id=owner.id,
            title="Distinct fact",
            content="This fact remains below the configured merge correlation.",
            source_kind="task",
            source_ref="task:threshold-create",
        )
    )

    assert result.status == "stored"
    assert result.memory_id is not None
    assert await db.scalar(select(func.count(MemoryItem.id))) == 1


@pytest.mark.asyncio
async def test_semantic_merge_keeps_existing_content_and_adds_provenance(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    existing, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Reporting preference",
            payload=MemoryPayload(text="The user wants a monthly report."),
        )
    )

    result = await acquisition_service.acquire_memory(
        MemoryAcquisitionCreate(
            agent_id=owner.id,
            action="create",
            target_item_id=existing.id,
            title="Monthly reporting",
            content="A report should be sent once every month.",
            source_kind="task",
            source_ref="task:semantic-duplicate",
            metadata={
                "memory_type": "semantic",
                "deduplication_decision": "merge",
                "semantic_similarity": 0.97,
            },
        )
    )

    assert result.status == "merged"
    assert result.memory_id == existing.id
    assert await db.scalar(select(func.count(MemoryItem.id))) == 1
    item, content, _access, _content_type, _media_type = await service.get_item(
        existing.id,
        agent_id=owner.id,
    )
    assert item.revision == 1
    assert visible_text(content.decode()) == "The user wants a monthly report."
    assert await service.source_refs(existing.id) == ["task:semantic-duplicate"]


@pytest.mark.asyncio
async def test_semantic_merge_can_link_a_source_managed_node_without_rewriting_it(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    profile = await service.upsert_source_managed_item(
        SourceMemoryDocument(
            source_kind="agent",
            source_ref=f"agent:{owner.id}",
            owner_agent_id=owner.id,
            memory_item_id=None,
            title="Agent profile",
            memory_type="core",
            content=(
                "The agent owns platform reliability and prefers small, "
                "verifiable changes."
            ),
            filename="agent.md",
            keywords=("reliability",),
            metadata={"memory_role": "agent"},
        )
    )
    original_created_at = profile.created_at

    result = await acquisition_service.acquire_memory(
        MemoryAcquisitionCreate(
            agent_id=owner.id,
            action="create",
            target_item_id=profile.id,
            title="Small changes",
            content="The agent prefers small, verifiable changes.",
            source_kind="task",
            source_ref="task:source-managed-link",
            metadata={"deduplication_decision": "merge"},
        ),
        memory_created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )

    item, content, _access, _content_type, _media_type = await service.get_item(
        profile.id,
        agent_id=owner.id,
    )
    assert result.status == "merged"
    assert result.memory_id == profile.id
    assert item.revision == 1
    assert item.created_at == original_created_at
    assert visible_text(content.decode()) == "The agent owns platform reliability and prefers small, verifiable changes."
    assert await service.source_refs(profile.id) == [
        f"agent:{owner.id}",
        "task:source-managed-link",
    ]


@pytest.mark.asyncio
async def test_semantic_merge_can_link_a_document_without_rewriting_it(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    document, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Release guide",
            payload=MemoryPayload(text="Production releases happen every Tuesday."),
            memory_type="working",
            node_kind="document",
        )
    )

    result = await acquisition_service.acquire_memory(
        MemoryAcquisitionCreate(
            agent_id=owner.id,
            action="create",
            target_item_id=document.id,
            title="Release schedule",
            content="Production releases happen every Tuesday.",
            source_kind="task",
            source_ref="task:document-link",
            metadata={"deduplication_decision": "merge"},
        )
    )

    item, content, _access, _content_type, _media_type = await service.get_item(
        document.id,
        agent_id=owner.id,
    )
    assert result.status == "merged"
    assert result.memory_id == document.id
    assert item.revision == 1
    assert visible_text(content.decode()) == "Production releases happen every Tuesday."
    assert await service.source_refs(document.id) == ["task:document-link"]


@pytest.mark.asyncio
async def test_acquisition_preserves_earliest_source_date_when_merging(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    existing, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Historical preference",
            payload=MemoryPayload(text="Use metric units in every report."),
        )
    )
    task_date = datetime(2026, 5, 12, 9, 30, tzinfo=timezone.utc)

    result = await acquisition_service.acquire_memory(
        MemoryAcquisitionCreate(
            agent_id=owner.id,
            title="Metric units",
            content="Use metric units in every report.",
            source_kind="task",
            source_ref="task:historical",
        ),
        memory_created_at=task_date,
    )

    assert result.status == "merged"
    assert result.memory_id == existing.id
    item, _content, _access, _content_type, _media_type = await service.get_item(
        existing.id,
        agent_id=owner.id,
    )
    assert item.created_at == task_date


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_type", "expected_type"),
    [
        (None, "semantic"),
        ("core", "core"),
        ("preference", "core"),
        ("decision", "semantic"),
        ("unknown", None),
    ],
)
async def test_pending_acquisition_is_resumed_without_human_review(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    stored_type: str | None,
    expected_type: str | None,
) -> None:
    del memory_storage
    owner, _peer = agents
    candidate, created = await acquisition_service._create_acquisition_record(  # pyright: ignore[reportPrivateUsage]
        MemoryAcquisitionCreate(
            agent_id=owner.id,
            title="Interrupted acquisition",
            content="A durable fact left pending by an older runtime.",
            source_kind="interrupted_runtime",
            source_ref="runtime-event:99",
            metadata={"memory_type": stored_type} if stored_type else {},
        )
    )
    assert created and candidate.status == "pending"

    applied, failed = await acquisition_service.resolve_pending_acquisitions()

    if expected_type is None:
        assert (applied, failed) == (0, 1)
        assert candidate.status == "pending"
        assert candidate.target_item_id is None
        return

    assert (applied, failed) == (1, 0)
    assert candidate.status == "accepted"
    assert candidate.target_item_id is not None
    item, content, *_ = await service.get_item(candidate.target_item_id, agent_id=owner.id)
    assert item.memory_type == expected_type
    assert visible_text(content.decode()) == "A durable fact left pending by an older runtime."
    assert candidate.metadata_.get("memory_type") == stored_type
    assert await acquisition_service.resolve_pending_acquisitions() == (0, 0)


@pytest.mark.asyncio
async def test_skip_acquisition_is_rejected_automatically(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    result = await acquisition_service.acquire_memory(
        MemoryAcquisitionCreate(
            agent_id=owner.id,
            action="skip",
            title="Temporary output",
            content="This content is not durable.",
            source_ref="task:temporary",
        )
    )

    assert result.status == "rejected"
    assert result.memory_id is None
    assert result.applied


@pytest.mark.asyncio
async def test_terminal_capture_is_durable_idempotent_and_redacts_secrets(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, _peer = agents
    monkeypatch.setattr(automation.runtime_settings, "MEMORY_CAPTURE_ENABLED", True)
    monkeypatch.setattr(automation.runtime_settings, "MEMORY_CAPTURE_MIN_CHARS", 20)
    task = Task(
        id=uuid4(),
        label="Configure integration",
        objective="Remember the durable integration rule.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        data={"language": "fr"},
    )
    task.set_execution_result(
        ExecutionResult(
            prompt="configure",
            result="The endpoint is stable and password=super-secret must never leak.",
            success=True,
            tools_used=["memory_search"],
        )
    )

    await automation.enqueue_terminal_capture(task)
    await automation.enqueue_terminal_capture(task)

    assert await db.scalar(select(func.count(MemoryAutomationJob.id))) == 1
    job = await db.scalar(select(MemoryAutomationJob))
    assert job is not None
    await automation._process_task_capture(job.payload)  # pyright: ignore[reportPrivateUsage]
    candidate = await db.scalar(select(MemoryAcquisition))
    assert candidate is not None
    assert candidate.status == "accepted"
    assert candidate.target_item_id is not None
    assert "super-secret" not in candidate.content
    assert "password=[redacted]" in candidate.content
    assert candidate.source_ref == f"task:{task.id}"
    assert candidate.metadata_["language"] == "fr"
    _item, content, _access, _content_type, _media_type = await service.get_item(
        candidate.target_item_id,
        agent_id=owner.id,
    )
    assert b"password=[redacted]" in content
    assert b"Demande utilisateur" in content
    assert b"R\xc3\xa9sultat" in content


@pytest.mark.asyncio
async def test_embedding_provider_failure_defers_only_semantic_jobs(
    db: AsyncSession,
) -> None:
    now = datetime.now(timezone.utc)
    semantic_index = MemoryAutomationJob(
        kind="semantic_index",
        idempotency_key=f"semantic-index-{uuid4()}",
        payload={},
        available_at=now,
    )
    semantic_reconcile = MemoryAutomationJob(
        kind="semantic_reconcile",
        idempotency_key=f"semantic-reconcile-{uuid4()}",
        payload={},
        available_at=now,
    )
    task_capture = MemoryAutomationJob(
        kind="task_capture",
        idempotency_key=f"task-capture-{uuid4()}",
        payload={},
        available_at=now,
    )
    db.add_all([semantic_index, semantic_reconcile, task_capture])
    await db.commit()

    await automation._defer_embedding_jobs_after_provider_failure()  # pyright: ignore[reportPrivateUsage]

    await db.refresh(semantic_index)
    await db.refresh(semantic_reconcile)
    await db.refresh(task_capture)
    minimum_retry_at = now + timedelta(minutes=4, seconds=55)
    assert semantic_index.available_at >= minimum_retry_at
    assert semantic_reconcile.available_at >= minimum_retry_at
    assert task_capture.available_at == now

    from app.memory.embedding import MemoryEmbeddingProviderUnavailableError
    claimed = automation._ClaimedJob(
        id=semantic_index.id, kind="semantic_index", payload={},
        attempts=automation.runtime_settings.MEMORY_AUTOMATION_MAX_ATTEMPTS,
    )
    await automation._mark_failure(claimed, MemoryEmbeddingProviderUnavailableError("unreachable"))
    await db.refresh(semantic_index)
    assert semantic_index.status == "pending"
    assert semantic_index.attempts < automation.runtime_settings.MEMORY_AUTOMATION_MAX_ATTEMPTS
    await automation._mark_failure(claimed, ValueError("invalid document"))
    await db.refresh(semantic_index)
    assert semantic_index.status == "error"


@pytest.mark.asyncio
async def test_terminal_capture_skips_ordinary_messenger_tasks_unless_opted_in(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, _peer = agents
    monkeypatch.setattr(automation.runtime_settings, "MEMORY_CAPTURE_ENABLED", True)
    monkeypatch.setattr(automation.runtime_settings, "MEMORY_CAPTURE_MIN_CHARS", 20)
    task = Task(
        id=uuid4(),
        label="Incoming Nextcloud message",
        objective="Can you explain this ordinary conversation in detail?",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        message_platform="nextcloud",
        message_group_id="room-42",
        data={"connection_id": 7, "message_id": "message-42"},
    )
    task.set_execution_result(
        ExecutionResult(
            prompt="explain",
            result="This is a sufficiently long answer, but it is still only session history.",
            success=True,
        )
    )

    await automation.enqueue_terminal_capture(task)

    assert await db.scalar(select(func.count(MemoryAutomationJob.id))) == 0

    task.data = {**(task.data or {}), "memory_capture": True}
    await automation.enqueue_terminal_capture(task)

    assert await db.scalar(select(func.count(MemoryAutomationJob.id))) == 1


@pytest.mark.asyncio
async def test_terminal_capture_does_not_duplicate_explicit_memory_tools(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, _peer = agents
    monkeypatch.setattr(automation.runtime_settings, "MEMORY_CAPTURE_ENABLED", True)
    monkeypatch.setattr(automation.runtime_settings, "MEMORY_CAPTURE_MIN_CHARS", 20)
    task = Task(
        id=uuid4(),
        label="Explicit memory acquisition",
        objective="Remember this durable preference for future conversations.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        data={},
    )
    task.set_execution_result(
        ExecutionResult(
            prompt="remember",
            result="The preference was already stored through the governed memory tool.",
            success=True,
            tools_used=["mcp__galaris__memory_remember"],
        )
    )

    await automation.enqueue_terminal_capture(task)

    assert await db.scalar(select(func.count(MemoryAutomationJob.id))) == 0


@pytest.mark.asyncio
async def test_terminal_capture_skips_goal_tasks_owned_by_source_projection(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, _peer = agents
    monkeypatch.setattr(automation.runtime_settings, "MEMORY_CAPTURE_ENABLED", True)
    monkeypatch.setattr(automation.runtime_settings, "MEMORY_CAPTURE_MIN_CHARS", 20)
    task = Task(
        id=uuid4(),
        label="Goal cycle task",
        objective="Advance the durable Goal with a sufficiently detailed action.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        goal_id=uuid4(),
        data={},
    )
    task.set_execution_result(
        ExecutionResult(
            prompt="advance",
            result="The cycle result belongs exclusively to the GoalCycle projection.",
            success=True,
        )
    )

    await automation.enqueue_terminal_capture(task)

    assert await db.scalar(select(func.count(MemoryAutomationJob.id))) == 0


def test_capture_rejects_private_keys() -> None:
    content = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    assert automation._redact_secrets(content) is None  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_acquisition_redacts_credentials_before_storage(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    acquired = await acquisition_service.acquire_memory(
        MemoryAcquisitionCreate(
            agent_id=owner.id,
            title="Sanitized integration note",
            content="Use endpoint A with token=not-for-storage.",
            source_ref="test:safety",
        )
    )
    candidate = await acquisition_service.get_acquisition_record(acquired.acquisition_id)
    assert candidate is not None
    assert candidate.status == "accepted"
    assert "not-for-storage" not in candidate.content
    assert "token=[redacted]" in candidate.content

    with pytest.raises(ValueError, match="metadata contains credential-like"):
        await acquisition_service.acquire_memory(
            MemoryAcquisitionCreate(
                agent_id=owner.id,
                title="Unsafe acquisition metadata",
                content="Visible text is safe.",
                source_ref="test:safety:metadata",
                metadata={"password": "must-not-persist"},
            )
        )


@pytest.mark.asyncio
async def test_capture_prefers_update_and_preserves_contradictions_as_linked_items(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    existing, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Deployment policy",
            payload=MemoryPayload(text="Deploy every Friday."),
        )
    )
    task_id = uuid4()
    await automation._process_task_capture(  # pyright: ignore[reportPrivateUsage]
        {
            "task_id": str(task_id),
            "agent_id": owner.id,
            "label": "Deployment policy",
            "objective": "Correction to the deployment policy",
            "answer": "Deployments are no longer allowed on Fridays.",
            "tools_used": [],
        }
    )
    candidate = await db.scalar(
        select(MemoryAcquisition).where(
            MemoryAcquisition.source_ref == f"task:{task_id}"
        )
    )
    assert candidate is not None
    assert candidate.action == "contradict"
    assert candidate.target_item_id == existing.id
    assert candidate.status == "accepted"
    result_memory_id = UUID(str(candidate.metadata_["result_memory_id"]))
    assert result_memory_id != existing.id
    links = await service.list_links(existing.id, actor_agent_id=owner.id)
    assert len(links) == 1
    assert links[0].relation_type == "contradicts"
    assert links[0].target_item_id == result_memory_id


@pytest.mark.asyncio
async def test_automatic_update_acquisition_uses_the_target_revision(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    existing, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Operational rule",
            payload=MemoryPayload(text="Initial rule."),
        )
    )
    await automation._process_task_capture(  # pyright: ignore[reportPrivateUsage]
        {
            "task_id": str(uuid4()),
            "agent_id": owner.id,
            "label": existing.title,
            "objective": "Clarify the operational rule",
            "answer": "Updated rule proposed by the completed task.",
            "tools_used": [],
        }
    )
    candidate = await db.scalar(
        select(MemoryAcquisition).where(
            MemoryAcquisition.target_item_id == existing.id
        )
    )
    assert candidate is not None
    assert candidate.metadata_["target_revision"] == 1
    assert candidate.status == "accepted"
    item, content, _access, _content_type, _media_type = await service.get_item(
        existing.id,
        agent_id=owner.id,
    )
    assert item.revision == 2
    assert b"Updated rule proposed by the completed task." in content


@pytest.mark.asyncio
async def test_task_capture_never_targets_a_source_managed_title_collision(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    generated = await service.upsert_source_managed_item(
        SourceMemoryDocument(
            source_kind="agent",
            source_ref=f"agent:test-collision:{owner.id}",
            owner_agent_id=owner.id,
            memory_item_id=None,
            title="Operational profile",
            memory_type="core",
            content="# Operational profile\n\nGenerated from canonical data.\n",
            filename=f"agent-test-{owner.id}.md",
            keywords=("agent", f"agent:{owner.id}"),
            metadata={"projection_version": 1},
        )
    )

    task_id = uuid4()
    await automation._process_task_capture(  # pyright: ignore[reportPrivateUsage]
        {
            "task_id": str(task_id),
            "agent_id": owner.id,
            "label": generated.title,
            "objective": "Remember a separate operational observation.",
            "answer": "This observation is ordinary agent-authored memory.",
            "tools_used": [],
        }
    )

    candidate = await db.scalar(
        select(MemoryAcquisition).where(
            MemoryAcquisition.source_ref == f"task:{task_id}"
        )
    )
    assert candidate is not None
    assert candidate.action == "create"
    assert candidate.target_item_id is not None
    assert candidate.target_item_id != generated.id
    target = await db.get(MemoryItem, candidate.target_item_id)
    assert target is not None
    assert not target.source_managed
    unchanged = await db.get(MemoryItem, generated.id)
    assert unchanged is not None
    assert unchanged.revision == 1
