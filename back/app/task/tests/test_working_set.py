import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db_session

from app.agent.contracts import (
    AgentContextRequest,
    AgentContextCandidate,
    AgentContextCapsule,
    AgentSnapshot,
    WorkingResource,
    WorkingSet,
)
from app.task.models import Task, TaskStatus
from app.task.agent_adapter import SqlAlchemyAgentTaskAdapter
from app.task.working_set import (
    freeze_context_capsule,
    get_context_capsule,
    get_working_set,
    interlocutor_context_candidates,
    render_working_set,
    upsert_working_resource,
    working_set_context_provider,
)


def _task(**values: object) -> Task:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "label": "Working set",
        "objective": "Create one document",
        "status": TaskStatus.PLAN,
        "paused": False,
        "ai": False,
        "cost": 0.0,
        "effort": "standard",
    }
    defaults.update(values)
    return Task(**defaults)


@pytest.mark.asyncio
@pytest.mark.parametrize("via_child", [False, True])
@pytest.mark.parametrize("first_write", ["resource", "checkpoint", "capsule", "heartbeat"])
async def test_resource_registration_preserves_concurrent_root_updates(
    committed_database, via_child: bool, first_write: str,
) -> None:
    checkpoint = {"driver_code": "internal", "data": {"receipt": "confirmed"}}
    capsule = AgentContextCapsule(
        contact_memory_item_id=uuid4(), rendered="Frozen context",
    )
    first = WorkingResource(
        resource_type="artifact", role="source", reference="https://example.test/source",
    )
    second = WorkingResource(
        resource_type="artifact", role="report", reference=f"document://{uuid4()}",
    )
    async with get_db_session() as db:
        root = _task(data={"existing": {"keep": True}}, lease_token=uuid4(),
                     lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30))
        child = _task(parent_id=root.id)
        db.add_all([root, child])
        await db.flush()
        root_id, target_id = root.id, child.id if via_child else root.id
        objective = str(root.objective)
        lease_token, prior_expiry = root.lease_token, root.lease_expires_at

    loaded = asyncio.Event()
    committed = asyncio.Event()

    async def register_from_old_snapshot() -> None:
        async with get_db_session() as db:
            # Keep the object alive: the ORM identity map must retain the old snapshot.
            stale_root = await db.get(Task, root_id)
            assert stale_root is not None
            revision = stale_root.revision
            loaded.set()
            await committed.wait()
            await upsert_working_resource(target_id, second)
            assert stale_root.revision > revision

    async def update_root() -> None:
        await loaded.wait()
        if first_write == "checkpoint":
            await SqlAlchemyAgentTaskAdapter().persist_agent_run_state(
                root_id,
                expected_objective=objective,
                data_patch={"_agent_run_checkpoint": checkpoint},
            )
        else:
            async with get_db_session():
                if first_write == "resource":
                    await upsert_working_resource(root_id, first)
                elif first_write == "heartbeat":
                    from app.task.scheduler import _renew_lease
                    assert await _renew_lease(root_id, lease_token)
                else:
                    await freeze_context_capsule(root_id, capsule)
        committed.set()

    async with asyncio.timeout(10), asyncio.TaskGroup() as group:
        group.create_task(register_from_old_snapshot())
        group.create_task(update_root())

    async with get_db_session() as db:
        root = await db.get(Task, root_id)
        assert root.data["existing"] == {"keep": True}
        working_set = await get_working_set(target_id)
        assert working_set.active("report")[0].producer_task_id == target_id
        if first_write == "resource":
            assert {item.reference for item in working_set.active()} == {
                first.reference, second.reference,
            }
        elif first_write == "capsule":
            assert await get_context_capsule(target_id) == capsule
        elif first_write == "heartbeat":
            assert root.lease_token == lease_token and root.lease_expires_at > prior_expiry
        else:
            assert root.data["_agent_run_checkpoint"] == checkpoint
        revision = root.revision
        # Redelivery only registers the resource; it must not create another version.
        await upsert_working_resource(target_id, second)
        assert root.revision == revision
        assert await get_working_set(target_id) == working_set


@pytest.mark.asyncio
async def test_concurrent_context_freeze_returns_first_committed_capsule(
    committed_database,
) -> None:
    first = AgentContextCapsule(contact_memory_item_id=uuid4(), rendered="First")
    competing = first.model_copy(update={"rendered": "Must not replace"})
    async with get_db_session() as db:
        root = _task()
        db.add(root)
        await db.flush()
        root_id = root.id

    loaded = asyncio.Event()
    committed = asyncio.Event()

    async def freeze_from_old_snapshot() -> None:
        async with get_db_session() as db:
            stale_root = await db.get(Task, root_id)
            assert stale_root is not None and stale_root.data is None
            loaded.set()
            await committed.wait()
            assert await freeze_context_capsule(root_id, competing) == first

    async def freeze_first() -> None:
        await loaded.wait()
        async with get_db_session():
            await freeze_context_capsule(root_id, first)
        committed.set()

    async with asyncio.timeout(10), asyncio.TaskGroup() as group:
        group.create_task(freeze_from_old_snapshot())
        group.create_task(freeze_first())

    async with get_db_session() as db:
        root = await db.get(Task, root_id)
        assert await get_context_capsule(root_id) == first
        assert root.revision == 2


@pytest.mark.asyncio
async def test_registration_preserves_pending_changes_and_rolls_back_with_caller(
    committed_database,
) -> None:
    async with get_db_session() as db:
        root = _task(data={"existing": True})
        db.add(root)
        await db.flush()
        root_id = root.id

    async with get_db_session() as db:
        root = await db.get(Task, root_id)
        root.data = {**root.data, "pending": "keep"}
        await upsert_working_resource(root_id, WorkingResource(
            resource_type="artifact", role="source", reference="https://example.test/source",
        ))

    with pytest.raises(RuntimeError, match="Caller failed"):
        async with get_db_session():
            await upsert_working_resource(root_id, WorkingResource(
                resource_type="artifact", role="report", reference="https://example.test/report",
            ))
            raise RuntimeError("Caller failed")

    async with get_db_session() as db:
        root = await db.get(Task, root_id)
        assert root.data["existing"] is True
        assert root.data["pending"] == "keep"
        working_set = await get_working_set(root_id)
        assert working_set.version == 1
        assert [item.role for item in working_set.active()] == ["source"]


@pytest.mark.asyncio
async def test_child_resources_are_persisted_on_root_and_inherited(
    db: AsyncSession,
) -> None:
    root = _task()
    child = _task(parent_id=root.id, status=TaskStatus.EXEC)
    db.add_all([root, child])
    await db.flush()
    document_id = uuid4()

    recorded = await upsert_working_resource(
        child.id,
        WorkingResource(
            resource_type="memory_document",
            role="primary_working_document",
            reference=str(document_id),
            label="Canonical draft",
            revision=1,
        ),
    )

    inherited = await get_working_set(child.id)
    assert recorded.producer_task_id == child.id
    assert inherited.version == 1
    assert inherited.active("primary_working_document")[0].reference == str(document_id)
    assert root.data is not None
    assert root.data["working_set"]["version"] == 1
    assert child.data is None


@pytest.mark.asyncio
async def test_interlocutor_capsule_is_frozen_once_on_root(
    db: AsyncSession,
) -> None:
    root = _task()
    child = _task(parent_id=root.id, status=TaskStatus.EXEC)
    db.add_all([root, child])
    await db.flush()
    contact_id = uuid4()
    first = AgentContextCapsule(
        contact_memory_item_id=contact_id,
        entries=[
            AgentContextCandidate(
                key="task:prior",
                kind="task",
                reference="prior",
                title="Prior task",
            )
        ],
        rendered="frozen-first",
    )
    competing = AgentContextCapsule(
        contact_memory_item_id=contact_id,
        rendered="must-not-replace",
    )

    stored = await freeze_context_capsule(child.id, first)
    unchanged = await freeze_context_capsule(root.id, competing)

    assert stored == first
    assert unchanged == first
    assert await get_context_capsule(child.id) == first
    assert root.data is not None
    assert root.data["interlocutor_context"]["rendered"] == "frozen-first"
    assert child.data is None


@pytest.mark.asyncio
async def test_replacement_supersedes_previous_role_without_losing_provenance(
    db: AsyncSession,
) -> None:
    root = _task()
    db.add(root)
    await db.flush()
    first = uuid4()
    second = uuid4()

    await upsert_working_resource(
        root.id,
        WorkingResource(
            resource_type="memory_document",
            role="primary_working_document",
            reference=str(first),
        ),
    )
    await upsert_working_resource(
        root.id,
        WorkingResource(
            resource_type="memory_document",
            role="primary_working_document",
            reference=str(second),
        ),
    )

    working_set = await get_working_set(root.id)
    assert working_set.version == 2
    assert working_set.active("primary_working_document")[0].reference == str(second)
    assert any(
        resource.reference == str(first) and resource.state == "superseded"
        for resource in working_set.resources
    )


def test_rendered_working_set_requires_exact_reuse() -> None:
    producer_task_id = uuid4()
    resource = WorkingResource(
        resource_type="artifact",
        role="file:console://report.html",
        reference="console://report.html",
        label="report.html",
        producer_task_id=producer_task_id,
    )

    rendered = render_working_set(WorkingSet(version=3, resources=[resource]))

    assert '<working_set version="3">' in rendered
    assert "reference: console://report.html" in rendered
    assert f"producer_task: galaris://task/{producer_task_id}" in rendered
    assert "producer_task_id:" not in rendered
    assert "do not rediscover or recreate" in rendered


def test_rendered_working_set_hides_retired_workspace_references() -> None:
    working_set = WorkingSet(
        version=4,
        resources=[
            WorkingResource(
                resource_type="workspace_file",
                role="legacy",
                reference="workspace://old/report.html",
            ),
            WorkingResource(
                resource_type="artifact",
                role="current",
                reference="nextcloud://Shared/report.html",
            ),
        ],
    )

    rendered = render_working_set(working_set)

    assert "workspace://" not in rendered
    assert "nextcloud://Shared/report.html" in rendered


@pytest.mark.asyncio
async def test_recent_contact_documents_reach_conversation_and_voice_context(
    db: AsyncSession,
) -> None:
    from app.agent.models import Agent, Title
    from app.memory import MessengerContactObservation, observe_messenger_contact

    title = Title(label=f"Recent documents {uuid4()}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Document",
        last_name="Agent",
        code=f"recent-doc-{str(uuid4())[:8]}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=agent.id,
            messaging_id="nextcloud",
            user_id="nicolas",
            display_name="Nicolas",
        )
    )
    prior = _task(
        agent_id=agent.id,
        contact_memory_item_id=contact_id,
        label="Rapport trimestriel",
    )
    db.add(prior)
    await db.flush()
    document_id = uuid4()
    await upsert_working_resource(
        prior.id,
        WorkingResource(
            resource_type="memory_document",
            role="primary_working_document",
            reference=str(document_id),
            label="Rapport annoté",
            revision=4,
        ),
    )
    await upsert_working_resource(
        prior.id,
        WorkingResource(
            resource_type="artifact",
            role="temporary_export",
            reference="console://exports/rapport.pdf",
        ),
    )

    direct_candidates = await interlocutor_context_candidates(
        None,
        agent_id=agent.id,
        contact_memory_item_id=contact_id,
        documents_only=True,
    )
    assert [item.reference for item in direct_candidates] == [
        f"document://{document_id}"
    ]
    await db.commit()

    contribution = await working_set_context_provider(
        AgentContextRequest(
            task_id=None,
            agent=AgentSnapshot(
                id=agent.id,
                code=agent.code,
                first_name=agent.first_name,
                last_name=agent.last_name,
                driver_code="internal",
            ),
            objective="Live realtime voice conversation",
            contact_memory_item_id=contact_id,
        )
    )

    assert [item.reference for item in contribution.candidates] == [
        f"document://{document_id}"
    ]
    assert contribution.metadata["recent_document_count"] == 1
