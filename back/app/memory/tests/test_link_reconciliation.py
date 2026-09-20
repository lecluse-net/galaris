from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import AgentManagementScope
from app.agent.models import Agent
from app.contact import service as contact_service
from app.memory import MessengerContactObservation, observe_messenger_contact, service
from app.memory import automation
from app.memory.link_reconciliation import (
    MemoryLinkReconciliationResult,
    reconcile_memory_links,
)
from app.memory.models import (
    MemoryAutomationJob,
    MemoryContactItem,
    MemoryLink,
    MemoryTopicContactItem,
)
from app.memory.schemas import MemoryItemCreate, MemoryPayload, MemorySourceCreate
from app.task import Task, TaskStatus
from app.topic import TopicClassification, service as topic_service


@pytest.mark.asyncio
async def test_targeted_reconciliation_creates_moves_and_removes_topic_links(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    first_topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Premier sujet")
    )
    second_topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Second sujet")
    )
    assert first_topic.memory_item_id is not None
    assert second_topic.memory_item_id is not None
    task = Task(
        label="Source thématique",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        topic_id=first_topic.id,
    )
    db.add(task)
    await db.flush()
    memory, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Souvenir thématique",
            payload=MemoryPayload(text="Une information durable liée au sujet."),
            source=MemorySourceCreate(
                source_kind="task",
                source_ref=f"task:{task.id}",
            ),
        )
    )

    first = await reconcile_memory_links(
        item_id=memory.id,
        families=frozenset({"canonical"}),
    )
    assert first.created == 1
    link = await db.scalar(
        select(MemoryLink).where(
            MemoryLink.target_item_id == memory.id,
            MemoryLink.relation_type == "topic_contains",
        )
    )
    assert link is not None
    assert link.source_item_id == first_topic.memory_item_id
    assert link.projection_key == "memory.topic_membership"

    unchanged = await reconcile_memory_links(
        item_id=memory.id,
        families=frozenset({"canonical"}),
    )
    assert unchanged.created == 0
    assert unchanged.updated == 0
    assert unchanged.removed == 0
    assert unchanged.unchanged == 1

    task.topic_id = second_topic.id
    await db.commit()
    moved = await reconcile_memory_links(
        item_id=memory.id,
        families=frozenset({"canonical"}),
    )
    assert moved.created == 1
    assert moved.removed == 1
    links = list(
        (
            await db.scalars(
                select(MemoryLink).where(
                    MemoryLink.target_item_id == memory.id,
                    MemoryLink.relation_type == "topic_contains",
                )
            )
        ).all()
    )
    assert [item.source_item_id for item in links] == [second_topic.memory_item_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("merge_contact", [False, True])
async def test_targeted_reconciliation_rebuilds_exact_contact_scope(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    merge_contact: bool,
) -> None:
    del memory_storage
    owner, _peer = agents
    topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Sujet conversationnel")
    )
    assert topic.memory_item_id is not None
    contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@contact:example.test",
            display_name="Contact",
        )
    )
    task = Task(
        label="Conversation classée",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        topic_id=topic.id,
        contact_memory_item_id=contact_id,
    )
    db.add(task)
    await db.flush()
    memory, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Préférence du contact",
            payload=MemoryPayload(text="Le contact préfère les réponses courtes."),
            source=MemorySourceCreate(
                source_kind="task",
                source_ref=f"task:{task.id}",
            ),
        )
    )

    result = await reconcile_memory_links(
        item_id=memory.id,
        families=frozenset({"canonical"}),
    )
    assert result.contact_memberships_created == 1
    assert result.topic_contact_memberships_created == 1
    assert result.created == 3
    contact = await db.scalar(
        select(MemoryContactItem).where(MemoryContactItem.item_id == memory.id)
    )
    assert contact is not None and contact.contact_item_id == contact_id
    topic_contact = await db.scalar(
        select(MemoryTopicContactItem).where(
            MemoryTopicContactItem.item_id == memory.id
        )
    )
    assert topic_contact is not None
    links = list(
        (
            await db.scalars(
                select(MemoryLink).where(MemoryLink.target_item_id == memory.id)
            )
        ).all()
    )
    assert {(link.relation_type, link.projection_key) for link in links} == {
        ("topic_contains", "memory.topic_membership"),
        ("contact_contains", "memory.contact_membership"),
    }
    topic_contact_link = await db.scalar(
        select(MemoryLink).where(
            MemoryLink.source_item_id == topic.memory_item_id,
            MemoryLink.target_item_id == contact_id,
            MemoryLink.relation_type == "topic_involves_contact",
        )
    )
    assert topic_contact_link is not None
    assert topic_contact_link.projection_key == "memory.topic_contact_membership"

    unchanged = await reconcile_memory_links(
        item_id=memory.id,
        families=frozenset({"canonical"}),
    )
    assert unchanged.created == 0
    assert unchanged.updated == 0
    assert unchanged.removed == 0
    assert unchanged.unchanged == 3

    if merge_contact:
        target_id = await observe_messenger_contact(
            MessengerContactObservation(
                owner_agent_id=owner.id,
                messaging_id="telegram",
                user_id="123456",
                display_name="Contact Telegram",
            )
        )
        merged = await contact_service.merge_contacts(
            source_contact_item_id=contact_id,
            target_contact_item_id=target_id,
        )
        assert merged.contact.linked_memory_count == 1
        assert merged.rewired["memory_links"] == 2
        reconciled = await reconcile_memory_links(
            item_id=memory.id,
            families=frozenset({"canonical"}),
        )
        assert reconciled.created == 0
        assert reconciled.removed == 0
        assert reconciled.unchanged == 3
        await db.refresh(contact)
        await db.refresh(topic_contact_link)
        assert contact.contact_item_id == target_id
        assert topic_contact_link.target_item_id == target_id
        contact_link = await db.scalar(
            select(MemoryLink).where(
                MemoryLink.source_item_id == target_id,
                MemoryLink.target_item_id == memory.id,
                MemoryLink.relation_type == "contact_contains",
            )
        )
        assert contact_link is not None

    task.contact_memory_item_id = None
    await db.commit()
    removed = await reconcile_memory_links(
        item_id=memory.id,
        families=frozenset({"canonical"}),
    )
    assert removed.contact_memberships_removed == 1
    assert removed.topic_contact_memberships_removed == 1
    assert removed.removed == 2
    assert await db.get(MemoryLink, topic_contact_link.id) is None


@pytest.mark.asyncio
async def test_reconciliation_collapses_multiple_sources_in_the_same_exact_scope(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Sujet partagé")
    )
    assert topic.memory_item_id is not None
    contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@shared-contact:example.test",
            display_name="Shared contact",
        )
    )
    tasks = [
        Task(
            label=f"Conversation classée {index}",
            status=TaskStatus.SUCCESS,
            agent_id=owner.id,
            topic_id=topic.id,
            contact_memory_item_id=contact_id,
        )
        for index in range(2)
    ]
    db.add_all(tasks)
    await db.flush()
    source_refs = sorted(f"task:{task.id}" for task in tasks)
    memory, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Préférence confirmée",
            payload=MemoryPayload(text="Le contact confirme la même préférence."),
            source=MemorySourceCreate(
                source_kind="task",
                source_ref=source_refs[1],
            ),
        )
    )
    await service.add_item_source(
        memory.id,
        MemorySourceCreate(source_kind="task", source_ref=source_refs[0]),
        actor_agent_id=owner.id,
    )

    result = await reconcile_memory_links(
        item_id=memory.id,
        families=frozenset({"canonical"}),
    )

    memberships = list(
        (
            await db.scalars(
                select(MemoryTopicContactItem).where(
                    MemoryTopicContactItem.item_id == memory.id
                )
            )
        ).all()
    )
    assert result.topic_contact_memberships_created == 1
    assert len(memberships) == 1
    assert memberships[0].source_kind == "task"
    assert memberships[0].source_ref == source_refs[0]

    unchanged = await reconcile_memory_links(
        item_id=memory.id,
        families=frozenset({"canonical"}),
    )
    assert unchanged.topic_contact_memberships_created == 0
    assert unchanged.topic_contact_memberships_updated == 0


@pytest.mark.asyncio
async def test_reconciliation_never_acquires_a_matching_manual_link(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Sujet manuel")
    )
    assert topic.memory_item_id is not None
    task = Task(
        label="Source du lien manuel",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        topic_id=topic.id,
    )
    db.add(task)
    await db.flush()
    memory, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Souvenir lié explicitement",
            payload=MemoryPayload(text="Le triplet existe déjà sans projecteur."),
            source=MemorySourceCreate(
                source_kind="task",
                source_ref=f"task:{task.id}",
            ),
        )
    )
    manual = MemoryLink(
        source_item_id=topic.memory_item_id,
        target_item_id=memory.id,
        relation_type="topic_contains",
        confidence=0.7,
        suggested=False,
        created_by_agent_id=owner.id,
        metadata_={"reason": "explicit"},
    )
    db.add(manual)
    await db.commit()

    result = await reconcile_memory_links(
        item_id=memory.id,
        families=frozenset({"canonical"}),
    )
    await db.refresh(manual)
    assert result.manual_conflicts == 1
    assert manual.projection_key is None
    assert manual.confidence == 0.7
    assert manual.metadata_ == {"reason": "explicit"}


@pytest.mark.asyncio
async def test_dream_completion_queues_each_affected_memory_node(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    task = Task(
        label="Dream source",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
    )
    db.add(task)
    await db.flush()
    memory, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Dream memory",
            payload=MemoryPayload(text="Mémoire créée par une opération Dream."),
            source=MemorySourceCreate(
                source_kind="task",
                source_ref=f"task:{task.id}",
            ),
        )
    )
    await db.commit()

    created = await automation.enqueue_dream_link_reconciliation(
        mechanism_key="memory.extract_task",
        subject_kind="task",
        subject_id=str(task.id),
        payload={},
    )
    assert created == 1
    job = await db.scalar(
        select(MemoryAutomationJob).where(
            MemoryAutomationJob.kind == "link_reconcile",
            MemoryAutomationJob.payload["item_id"].as_string() == str(memory.id),
        )
    )
    assert job is not None
    assert job.payload["trigger"] == "dream:memory.extract_task"


@pytest.mark.asyncio
async def test_scheduled_global_reconciliation_is_enqueued_once_while_idle(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        automation.runtime_settings,
        "MEMORY_LINK_RECONCILIATION_TRIGGER_MODE",
        "after_dream_and_scheduled",
    )
    monkeypatch.setattr(
        automation.runtime_settings,
        "MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS",
        24,
    )

    async def busy() -> bool:
        return True

    monkeypatch.setattr(automation, "_foreground_work_active", busy)
    monkeypatch.setattr(automation, "_last_scheduled_link_check", None)
    await automation._enqueue_scheduled_link_reconciliation()
    assert await db.scalar(
        select(MemoryAutomationJob.id).where(
            MemoryAutomationJob.kind == "link_reconcile"
        )
    ) is None

    async def idle() -> bool:
        return False

    monkeypatch.setattr(automation, "_foreground_work_active", idle)
    monkeypatch.setattr(automation, "_last_scheduled_link_check", None)
    await automation._enqueue_scheduled_link_reconciliation()
    monkeypatch.setattr(automation, "_last_scheduled_link_check", None)
    await automation._enqueue_scheduled_link_reconciliation()

    jobs = list(
        (
            await db.scalars(
                select(MemoryAutomationJob).where(
                    MemoryAutomationJob.idempotency_key.like(
                        "link_reconcile_global:scheduled:%"
                    )
                )
            )
        ).all()
    )
    assert len(jobs) == 1
    assert jobs[0].payload["item_id"] is None
    assert jobs[0].payload["trigger"] == "scheduled"


@pytest.mark.asyncio
async def test_manual_global_reconciliation_runs_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.memory import router as memory_router

    calls: list[tuple[object, object]] = []

    async def fake_reconcile(
        *, item_id: object, families: object
    ) -> MemoryLinkReconciliationResult:
        calls.append((item_id, families))
        return MemoryLinkReconciliationResult(
            scope_item_id=None,
            sources_scanned=3,
            created=2,
            unchanged=4,
        )

    monkeypatch.setattr(memory_router, "reconcile_memory_links", fake_reconcile)
    monkeypatch.setattr(
        memory_router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(7, None)),
    )

    result = await memory_router.launch_link_reconciliation()

    assert calls == [(None, None)]
    assert result.sources_scanned == 3
    assert result.created == 2
    assert result.unchanged == 4


@pytest.mark.asyncio
async def test_post_dream_reconciliation_respects_trigger_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        automation.runtime_settings,
        "MEMORY_LINK_RECONCILIATION_TRIGGER_MODE",
        "scheduled",
    )

    created = await automation.enqueue_dream_link_reconciliation(
        mechanism_key="memory.extract_task",
        subject_kind="task",
        subject_id=str(uuid4()),
        payload={},
    )

    assert created == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("item_id", [None, "00000000-0000-0000-0000-000000000001"])
async def test_graph_maintenance_defers_to_foreground_work(
    monkeypatch: pytest.MonkeyPatch, item_id: str | None,
) -> None:
    from app.memory import link_reconciliation

    reconcile = AsyncMock()
    monkeypatch.setattr(automation, "_foreground_work_active", AsyncMock(return_value=True))
    monkeypatch.setattr(link_reconciliation, "reconcile_memory_links", reconcile)
    with pytest.raises(automation._ForegroundWorkActive):
        await automation._process_link_reconciliation({"item_id": item_id})
    reconcile.assert_not_awaited()


def test_link_reconciliation_routes_have_explicit_privileges() -> None:
    from app.memory.router import (
        launch_link_reconciliation,
        read_link_reconciliation_status,
    )
    from core.authorize import Privileges

    assert launch_link_reconciliation._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        Privileges.MEMORY_ADMIN
    ]
    assert read_link_reconciliation_status._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        Privileges.PARAMS_ACCESS,
        Privileges.PARAMS_EDIT,
        Privileges.MEMORY_ADMIN,
    ]
