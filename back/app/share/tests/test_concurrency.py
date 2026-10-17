"""Real PostgreSQL connections serialize ACL edits without lost updates."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.agent import Agent, AgentManagementScope
from app.agent.models import Title
from app.dataset import service as datasets, sharing as dataset_sharing
from app.dataset.models import Dataset
from app.memory import document_service, item_sharing, service as memories
from app.memory.models import MemoryItem
from app.process import native_sharing
from app.process.models import ProcessDefinition
from app.process.native_definitions import DefinitionConflictError
from app.share import ShareGrant, SharingUpdate
from app.tools import ToolModel
from core.database import get_db_session
from core.user import UserModel


async def seed_resources(domain):
    async with get_db_session() as db:
        manager = UserModel(
            email=f"synthetic-concurrent-{uuid4().hex}@example.test",
            hashed_password="unused",
            is_active=True,
        )
        title = Title(label="Synthetic concurrent sharing", gender="X")
        owner = Agent(
            user=manager,
            title=title,
            code=f"concurrent-{uuid4().hex}",
            first_name="Synthetic",
            last_name="Owner",
            agent_driver="internal",
        )
        db.add(owner)
        await db.flush()
        scope = AgentManagementScope(manager.id, frozenset({owner.id}))
        tool = await db.scalar(select(ToolModel.id).where(ToolModel.code == "galaris"))
        resources = []
        for index in range(2):
            if domain == "dataset":
                record = Dataset(
                    owner_agent_id=owner.id,
                    title=f"Synthetic concurrent {index}",
                    content="{}",
                )
            elif domain == "document":
                record = await document_service.create_document(
                    owner_agent_id=owner.id,
                    title=f"Synthetic concurrent {index}",
                    content="<p>Synthetic preserved content</p>",
                    task_id=None,
                )
            else:
                record = ProcessDefinition(
                    agent_id=owner.id,
                    tool_id=tool,
                    label=f"Synthetic concurrent {index}",
                    code=f"concurrent_{uuid4().hex}",
                    engine_process_id=f"synthetic_{index}",
                    bpmn_xml="<synthetic/>",
                )
            db.add(record)
            await db.flush()
            resources.append(
                (
                    record.id,
                    record.share_id,
                    record.lock_version,
                    record.code if domain == "process" else record.id,
                )
            )
        return scope, resources


async def write(domain, identity, scope, data):
    if domain == "dataset":
        return await dataset_sharing.update(identity, scope, data)
    if domain == "document":
        return await item_sharing.update_level(identity, data, scope)
    return await native_sharing.update(identity, scope, data)


async def wait_for_locks(session, pids):
    async with asyncio.timeout(10):
        while True:
            blocked = await session.scalar(
                text("""SELECT count(*) FROM pg_stat_activity
                WHERE pid = ANY(:pids) AND wait_event_type = 'Lock'"""),
                {"pids": pids},
            )
            if blocked == len(pids):
                return
            await asyncio.sleep(0.02)


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["dataset", "document", "process"])
async def test_concurrent_replacements_have_one_winner_and_stale_writes_cannot_restore_revoked_access(
    committed_database,
    memory_storage,
    domain,
):
    scope, resources = await seed_resources(domain)
    identity, share_id, version, key = resources[0]
    model = {"dataset": Dataset, "document": MemoryItem, "process": ProcessDefinition}[
        domain
    ]
    ready = [asyncio.Event(), asyncio.Event()]
    start = asyncio.Event()
    pids = []

    async def contender(index):
        try:
            async with get_db_session() as db:
                # A warm identity map must not bypass the version read after locking.
                record = await db.get(model, identity)
                assert record.lock_version == version
                pids.append(await db.scalar(text("SELECT pg_backend_pid()")))
                ready[index].set()
                await start.wait()
                await write(
                    domain,
                    key,
                    scope,
                    SharingUpdate(
                        level="public",
                        can_write=bool(index),
                        grants=[
                            {
                                "kind": "user",
                                "id": scope.user_id,
                                "can_write": bool(index),
                            }
                        ],
                        expected_lock_version=version,
                    ),
                )
                return index
        except (
            datasets.DatasetConflictError,
            memories.MemoryConflictError,
            DefinitionConflictError,
        ):
            return "conflict"

    async with committed_database() as blocker:
        await blocker.execute(
            select(model.id).where(model.id == identity).with_for_update()
        )
        tasks = [asyncio.create_task(contender(index)) for index in range(2)]
        try:
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in ready)), 10
            )
            start.set()
            await wait_for_locks(blocker, pids)
            await blocker.commit()
            outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 15)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    assert outcomes.count("conflict") == 1
    winner = next(value for value in outcomes if value != "conflict")
    async with get_db_session() as db:
        record = await db.get(model, identity)
        assert record.lock_version == version + 1
        assert record.share.global_access == (2 if winner else 1)
        assert (
            await db.execute(
                select(ShareGrant.user_id, ShareGrant.can_write).where(
                    ShareGrant.share_id == share_id,
                )
            )
        ).all() == [(scope.user_id, bool(winner))]
        await write(
            domain,
            key,
            scope,
            SharingUpdate(
                level="private", grants=[], expected_lock_version=record.lock_version
            ),
        )
    with pytest.raises(
        (
            datasets.DatasetConflictError,
            memories.MemoryConflictError,
            DefinitionConflictError,
        )
    ):
        async with get_db_session():
            await write(
                domain,
                key,
                scope,
                SharingUpdate(
                    level="public",
                    can_write=True,
                    grants=[],
                    expected_lock_version=version,
                ),
            )
    async with get_db_session() as db:
        record = await db.get(model, identity)
        assert record.share.global_access == 0
        assert record.lock_version == version + 2
        assert not list(
            await db.scalars(select(ShareGrant).where(ShareGrant.share_id == share_id))
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["dataset", "document", "process"])
async def test_locking_one_resource_does_not_block_independent_sharing(
    committed_database, memory_storage, domain
):
    scope, resources = await seed_resources(domain)
    model = {"dataset": Dataset, "document": MemoryItem, "process": ProcessDefinition}[
        domain
    ]
    identity, *_ = resources[0]
    other_id, _, version, key = resources[1]
    async with committed_database() as blocker:
        await blocker.execute(
            select(model.id).where(model.id == identity).with_for_update()
        )

        async def independent():
            async with get_db_session():
                await write(
                    domain,
                    key,
                    scope,
                    SharingUpdate(
                        level="public", grants=[], expected_lock_version=version
                    ),
                )

        await asyncio.wait_for(independent(), 10)
        await blocker.rollback()
    async with get_db_session() as db:
        assert (await db.get(model, identity)).share.global_access == 0
        assert (await db.get(model, other_id)).share.global_access == 1
