"""Real PostgreSQL connections serialize ACL edits without lost updates."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.agent import Agent, AgentManagementScope
from app.agent.models import Title
from app.dataset import service as datasets, sharing as dataset_sharing
from app.dataset.models import Dataset
from app.document import document_service, item_sharing
from app.document import resource_service as documents
from app.document.models import Document
from app.process import native_sharing
from app.process.models import ProcessDefinition
from app.process.native_definitions import DefinitionConflictError
from app.share import ShareGrant, SharingUpdate
from app.services import ServiceModel
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
        tool = await db.scalar(select(ServiceModel.id).where(ServiceModel.code == "galaris"))
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
                    service_id=tool,
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
async def test_account_activation_after_an_interruption_uses_last_committed_policy(committed_database):
    from sqlalchemy import event
    from app.share import ShareEffectiveAccess
    from core.database import lock_resource_sharing
    from core.user import HumanActor, UserUpdate, user_service

    scope, resources = await seed_resources("dataset")
    identity, share_id, version, key = resources[0]
    async with get_db_session() as db:
        reader = UserModel(email="account-race@example.test", hashed_password="unused", is_active=True)
        db.add(reader)
        await db.flush()
        user_id = reader.id
        state = await write("dataset", key, scope, SharingUpdate(level="public", can_write=True,
            grants=[], expected_lock_version=version))
    rights = select(ShareEffectiveAccess.can_write).where(
        ShareEffectiveAccess.share_id == share_id, ShareEffectiveAccess.user_id == user_id)

    def interrupt(session):
        assert session.scalar(rights) is None
        assert session.scalar(select(UserModel.is_active).where(UserModel.id == user_id)) is False
        raise RuntimeError("interrupted before commit")

    with pytest.raises(RuntimeError, match="interrupted before commit"):
        async with get_db_session() as db:
            event.listen(db.sync_session, "before_commit", interrupt, once=True)
            await user_service.update(user_id, UserUpdate(is_active=False))
    async with get_db_session() as db:
        assert await db.scalar(rights) is True
        assert (await datasets.record(identity, HumanActor(user_id), write=True)).id == identity

    ready = asyncio.get_running_loop().create_future()
    resume = asyncio.Event()

    async def reactivate():
        async with get_db_session() as session:
            # Authentication may already have loaded this account in the request.
            cached = await session.get(UserModel, user_id)
            assert cached.is_active
            ready.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            await resume.wait()
            await user_service.update(user_id, UserUpdate(is_active=True))

    async with asyncio.timeout(15), asyncio.TaskGroup() as group:
        group.create_task(reactivate())
        pid = await ready
        async with get_db_session() as db:
            await user_service.update(user_id, UserUpdate(is_active=False))
            assert await db.scalar(rights) is None
        async with get_db_session() as db:
            await lock_resource_sharing()
            resume.set()
            while not await db.scalar(text("SELECT pg_backend_pid() = ANY(pg_blocking_pids(:pid))"), {"pid": pid}):
                await asyncio.sleep(0.02)
            await write("dataset", key, scope, SharingUpdate(level="public", can_write=False,
                grants=[], expected_lock_version=state.lock_version))
    async with get_db_session() as db:
        assert await db.scalar(rights) is False
        assert (await datasets.record(identity, HumanActor(user_id))).id == identity
        with pytest.raises(datasets.DatasetNotFoundError):
            await datasets.record(identity, HumanActor(user_id), write=True)


@pytest.mark.asyncio
async def test_deactivation_includes_concurrently_created_private_document(committed_database):
    from app.share import ShareEffectiveAccess
    from core.user import HumanActor, UserUpdate, user_service

    async with get_db_session() as db:
        user = UserModel(email="concurrent-owner@example.test", hashed_password="unused", is_active=True)
        db.add(user)
        await db.flush()
        owner = user.id
    ready = asyncio.get_running_loop().create_future()

    async def deactivate():
        async with get_db_session() as session:
            ready.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            await user_service.update(owner, UserUpdate(is_active=False))

    async with asyncio.timeout(15), asyncio.TaskGroup() as group:
        async with get_db_session() as db:
            doc = await datasets.create(HumanActor(owner), title="New private data")
            rights = select(ShareEffectiveAccess.can_write).where(
                ShareEffectiveAccess.share_id == doc.share_id, ShareEffectiveAccess.user_id == owner)
            assert await db.scalar(rights) is True
            group.create_task(deactivate())
            pid = await ready
            while not await db.scalar(text("SELECT pg_backend_pid() = ANY(pg_blocking_pids(:pid))"), {"pid": pid}):
                await asyncio.sleep(0.02)
    async with get_db_session() as db:
        assert await db.scalar(rights) is None
        await user_service.update(owner, UserUpdate(is_active=True))
        assert await db.scalar(rights) is True


@pytest.mark.asyncio
async def test_membership_removal_observes_the_last_committed_document_rules(committed_database):
    from app.share import ShareEffectiveAccess
    from core.team import TeamModel, lock_team_sharing
    from core.team.service import set_human_membership
    from core.user import HumanActor

    scope, resources = await seed_resources("dataset")
    identity, share_id, version, key = resources[0]
    async with get_db_session() as db:
        team = TeamModel(name="Concurrent documentary sharing")
        reader = UserModel(email="team-reader@example.test", hashed_password="unused", is_active=True)
        db.add_all([team, reader])
        await db.flush()
        team_id, reader_id = team.id, reader.id
        await set_human_membership(team_id, reader_id, True)
        state = await write("dataset", key, scope, SharingUpdate(level="groups", expected_lock_version=version,
            grants=[{"kind": "team", "id": team_id, "can_write": True}]))

    member_access = select(ShareEffectiveAccess.can_write).where(
        ShareEffectiveAccess.share_id == share_id, ShareEffectiveAccess.user_id == reader_id)
    async with get_db_session() as interrupted:
        await set_human_membership(team_id, reader_id, False)
        assert await interrupted.scalar(member_access) is None
        # Drop this connection with both writes pending. PostgreSQL must
        # release the transaction lock and discard the membership and ACL edits.
        await interrupted.invalidate()
    async with get_db_session() as reopened:
        assert await reopened.scalar(member_access) is True
        assert (await datasets.record(identity, HumanActor(reader_id), write=True)).id == identity

    ready = asyncio.get_running_loop().create_future()

    async def leave():
        async with get_db_session() as session:
            ready.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            await set_human_membership(team_id, reader_id, False)

    async with asyncio.timeout(15), asyncio.TaskGroup() as group:
        async with get_db_session() as db:
            await lock_team_sharing()
            group.create_task(leave())
            pid = await ready
            while not await db.scalar(text("SELECT pg_backend_pid() = ANY(pg_blocking_pids(:pid))"), {"pid": pid}):
                await asyncio.sleep(0.02)
            await write("dataset", key, scope, SharingUpdate(level="groups", expected_lock_version=state.lock_version,
                grants=[{"kind": "team", "id": team_id, "can_write": True},
                        {"kind": "user", "id": reader_id, "can_write": False}]))
    async with get_db_session() as db:
        assert await db.scalar(member_access) is False
        assert (await datasets.record(identity, HumanActor(reader_id))).id == identity
        with pytest.raises(datasets.DatasetNotFoundError):
            await datasets.record(identity, HumanActor(reader_id), write=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["data_uri", "legacy"])
async def test_data_deletion_waits_for_a_sharing_edit_without_locking_its_row(committed_database, entry):
    from app.dataset.compatibility import LegacyDatasetAdapter
    from app.dataset.provider import DatasetProvider
    from app.document.sharing_inheritance import lock_sharing
    from app.file_share import ResourceContext, parse_resource_uri
    from app.share import ShareEffectiveAccess

    scope, resources = await seed_resources("dataset")
    identity, share_id, version, _ = resources[0]
    owner = next(iter(scope.agent_ids))
    ready = asyncio.get_running_loop().create_future()

    async def delete_current():
        async with get_db_session() as db:
            ready.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            if entry == "data_uri":
                await DatasetProvider().delete(ResourceContext(owner, "internal"), parse_resource_uri(f"data://{identity}"))
            else:
                await LegacyDatasetAdapter().remove(identity, owner)

    async with asyncio.timeout(15), asyncio.TaskGroup() as group:
        async with get_db_session() as db:
            await lock_sharing()
            group.create_task(delete_current())
            pid = await ready
            while not await db.scalar(text("SELECT pg_backend_pid() = ANY(pg_blocking_pids(:pid))"), {"pid": pid}):
                await asyncio.sleep(0.02)
            # The edit must be able to lock and publish the new revision even
            # when a file operation is already waiting to delete this document.
            await write("dataset", identity, scope, SharingUpdate(level="public", can_write=False,
                        grants=[], expected_lock_version=version))
    async with get_db_session() as db:
        assert await db.get(Dataset, identity) is None
        assert await db.scalar(select(ShareEffectiveAccess.id).where(ShareEffectiveAccess.share_id == share_id)) is None
        assert await db.get(Dataset, resources[1][0]) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["dataset", "document", "process"])
async def test_concurrent_replacements_have_one_winner_and_stale_writes_cannot_restore_revoked_access(
    committed_database,
    memory_storage,
    domain,
):
    scope, resources = await seed_resources(domain)
    identity, share_id, version, key = resources[0]
    model = {"dataset": Dataset, "document": Document, "process": ProcessDefinition}[
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
            documents.DocumentConflictError,
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
            documents.DocumentConflictError,
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
    model = {"dataset": Dataset, "document": Document, "process": ProcessDefinition}[
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
