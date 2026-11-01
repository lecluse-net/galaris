"""Exclusive policies, resource authorization, and lossless PostgreSQL upgrades."""

from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.dataset import service as datasets
from app.dataset.models import Dataset
from app.document.data.models import LegacyDataset
from app.dataset import sharing as dataset_sharing
from app.document import document_service
from app.memory.models import MemoryItem
from app.document import Document
from app.process.models import ProcessDefinition
from app.tools import ToolModel
from app.share import ShareConfig, ShareGrant, SharingUpdate
from app.share.dbadmin import needs_transfer
from app.share.migration import transfer, complete
from core.dbadmin import SchemaTransitionSet
from core.team import TeamModel
from core.user import UserModel


def test_transfer_is_bound_to_sharing_schema_expansion():
    assert needs_transfer(SchemaTransitionSet(added_tables=frozenset({"share_configs"})))
    assert needs_transfer(SchemaTransitionSet(added_columns=frozenset({"documents.share_id"})))
    assert not needs_transfer(SchemaTransitionSet())


@pytest.mark.asyncio
async def test_policies_are_exclusive_and_shared_editor_cannot_reshare(db, agents):
    owner, reader = agents
    first = await datasets.create(owner.id, title="Synthetic first resource", content="{}")
    second = await datasets.create(owner.id, title="Synthetic second resource", content="{}")
    assert first.share_id != second.share_id
    first_id, second_id, share_id = first.id, second.id, first.share_id
    await datasets.set_grant(first_id, owner.id, kind="agent", principal=reader.id,
        can_write=True, expected_lock_version=first.lock_version)
    state = await dataset_sharing.read(first_id, reader.id)
    assert not state.can_manage and not state.options
    with pytest.raises(datasets.DatasetNotFoundError):
        await dataset_sharing.update(first_id, reader.id, SharingUpdate(level="public", can_write=True,
            grants=[], expected_lock_version=state.lock_version))
    with pytest.raises(datasets.DatasetNotFoundError):
        await datasets.record(second_id, reader.id)
    async with db.begin_nested() as savepoint:
        with pytest.raises(IntegrityError):
            await db.execute(update(Dataset).where(Dataset.id == second_id).values(share_id=share_id))
        await savepoint.rollback()


@pytest.mark.asyncio
async def test_cross_type_policy_reuse_is_rejected_and_document_projection_has_one_identity(db, agents, memory_storage):
    owner, _ = agents
    dataset = await datasets.create(owner.id, title="Synthetic JSON", content="{}")
    document = await document_service.create_document(owner_agent_id=owner.id,
        title="Synthetic prose", content="<p>Synthetic</p>", task_id=None)
    record = await db.get(Document, document.id)
    assert record.share_id == document.share_id
    async with db.begin_nested() as savepoint:
        with pytest.raises(IntegrityError):
            await db.execute(update(Document).where(Document.id == document.id).values(share_id=dataset.share_id))
            await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await savepoint.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dataset", "document", "process"])
@pytest.mark.parametrize("public", [0, 1, 2])
@pytest.mark.parametrize("deleted", [False, True])
async def test_acl_upgrade_preserves_existing_access_tombstones_and_replays_without_reviving_grants(
        db, agents, memory_storage, kind, public, deleted):
    owner, reader = agents
    human = UserModel(email="synthetic-legacy-share@example.test", hashed_password="unused", is_active=True)
    team = TeamModel(name="Synthetic migration recipients")
    db.add_all([human, team])
    await db.flush()
    if kind == "dataset":
        # The retained grant ORM now references canonical Documents. Recreate the
        # historical FK before seeding the source Dataset in this transaction.
        await db.execute(text("ALTER TABLE dataset_grants DROP CONSTRAINT dataset_grants_dataset_id_fkey"))
        await db.execute(text("ALTER TABLE dataset_grants ADD CONSTRAINT dataset_grants_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES datasets(id)"))
        resource = LegacyDataset(owner_agent_id=owner.id, title="Synthetic old resource", content="{}")
        db.add(resource)
        await db.flush()
        model, table, legacy, foreign = LegacyDataset, "datasets", "dataset_grants", "dataset_id"
    elif kind == "document":
        resource = await document_service.create_document(owner_agent_id=owner.id,
            title="Synthetic old resource", content="<p>Synthetic preserved prose</p>", task_id=None)
        model, table, legacy, foreign = Document, "documents", "memory_item_grants", "item_id"
        db.add(MemoryItem(id=resource.id, node_kind="document", owner_agent_id=owner.id,
            resource_id=str(resource.id), content_hash=resource.content_hash,
            search_title="Synthetic old resource", search_text="Synthetic preserved prose"))
        await db.flush()
        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await db.execute(text("ALTER TABLE memory_items ADD COLUMN share_id uuid, ADD COLUMN share_kind varchar(30)"))
        await db.execute(text("ALTER TABLE documents ADD COLUMN memory_item_id uuid"))
        await db.execute(text("ALTER TABLE documents ADD COLUMN global_access integer DEFAULT 0, ADD COLUMN group_access integer DEFAULT 0"))
        await db.execute(text("UPDATE documents SET memory_item_id = id WHERE id = :id"), {"id": resource.id})
        for source, principal in (("memory_item_grants", "agent"), ("document_user_grants", "user"), ("document_team_grants", "team")):
            await db.execute(text(f"CREATE TABLE {source} (item_id uuid, {principal}_id integer, can_write boolean)"))
    else:
        tool = await db.scalar(select(ToolModel.id).where(ToolModel.code == "galaris"))
        resource = ProcessDefinition(agent_id=owner.id, tool_id=tool, label="Synthetic old resource",
            code="synthetic_migration", engine_process_id="synthetic_migration")
        db.add(resource)
        await db.flush()
        model, table, legacy, foreign = ProcessDefinition, "process_definitions", "process_definition_grants", "process_id"
    if deleted:
        resource.soft_delete()
        await db.flush()
    identity, original_share = resource.id, resource.share_id
    reader_id, human_id, team_id = reader.id, human.id, team.id
    # Reproduce the former physical schema in the test transaction only. The db
    # fixture rolls back DDL and service commits, preserving test isolation.
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    for target in (table, "memory_items") if kind == "document" else (table,):
        await db.execute(text(f"ALTER TABLE {target} ALTER COLUMN share_id DROP NOT NULL"))
        await db.execute(text(f"ALTER TABLE {target} ALTER COLUMN share_kind DROP NOT NULL"))
        await db.execute(text(f"UPDATE {target} SET share_id = NULL, share_kind = NULL WHERE id = :id"), {"id": identity})
    await db.execute(text(f"UPDATE {table} SET global_access = :public, group_access = :groups WHERE id = :id"),
        {"id": identity, "public": public, "groups": 2 if public == 0 else 0})
    for principal, recipient, write in (("agent", reader_id, True), ("user", human_id, False), ("team", team_id, True)):
        source = legacy
        column = foreign
        parameters = {"resource": identity, "recipient": recipient, "write": write}
        if kind == "document":
            source = {"agent": "memory_item_grants", "user": "document_user_grants", "team": "document_team_grants"}[principal]
        elif kind == "dataset":
            parameters["id"] = uuid4()
        key_columns, key_values = ("id,", ":id,") if kind == "dataset" else ("", "")
        await db.execute(text(f"INSERT INTO {source} ({key_columns}{column},{principal}_id,can_write) VALUES ({key_values}:resource,:recipient,:write)"), parameters)
    assert not await complete(db)
    await transfer(db)
    assert await complete(db)
    db.expire_all()
    migrated = await db.get(model, identity, execution_options={"include_historized": True})
    assert migrated.share_id != original_share
    policy = await db.get(ShareConfig, migrated.share_id)
    assert policy.group_access == (2 if public == 0 else 0) and policy.global_access == public
    if not deleted:
        assert migrated.group_access == policy.group_access and migrated.global_access == public
    assert bool(migrated.deleted_at) == deleted
    grants = list(await db.scalars(select(ShareGrant).where(ShareGrant.share_id == migrated.share_id)))
    assert {(g.agent_id, g.user_id, g.team_id, g.can_write) for g in grants} == {
        (reader_id, None, None, True), (None, human_id, None, False), (None, None, team_id, True)}
    grant = next(g for g in grants if g.agent_id == reader_id)
    migrated_id = migrated.share_id
    await db.delete(grant)
    await db.flush()
    await transfer(db)
    assert await complete(db)
    assert not await db.scalar(select(ShareGrant.id).where(ShareGrant.share_id == migrated_id, ShareGrant.agent_id == reader_id))
    assert len(list(await db.scalars(select(ShareGrant.id).where(ShareGrant.share_id == migrated_id)))) == 2
    assert (await db.get(ShareConfig, migrated_id)).legacy_acl_hash


@pytest.mark.asyncio
async def test_interrupted_acl_transfer_rolls_back_and_resumes_without_losing_legacy_grants(db, agents, monkeypatch):
    owner, reader = agents
    await db.execute(text("ALTER TABLE dataset_grants DROP CONSTRAINT dataset_grants_dataset_id_fkey"))
    await db.execute(text("ALTER TABLE dataset_grants ADD CONSTRAINT dataset_grants_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES datasets(id)"))
    resource = LegacyDataset(owner_agent_id=owner.id, title="Synthetic interrupted upgrade", content="{}")
    db.add(resource)
    await db.flush()
    identity = resource.id
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db.execute(text("ALTER TABLE datasets ALTER COLUMN share_id DROP NOT NULL"))
    await db.execute(text("ALTER TABLE datasets ALTER COLUMN share_kind DROP NOT NULL"))
    await db.execute(text("UPDATE datasets SET share_id = NULL, share_kind = NULL WHERE id = :id"), {"id": identity})
    await db.execute(text("INSERT INTO dataset_grants (id,dataset_id,agent_id,can_write) VALUES (:id,:resource,:reader,true)"),
        {"id": uuid4(), "resource": identity, "reader": reader.id})
    await db.commit()
    configs_before = await db.scalar(text("SELECT count(*) FROM share_configs"))
    execute = db.execute

    async def interrupted(statement, *args, **kwargs):
        if "INSERT INTO public.share_grants" in str(statement):
            raise RuntimeError("Synthetic interrupted grant copy")
        return await execute(statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(db, "execute", interrupted)
        with pytest.raises(RuntimeError, match="Synthetic interrupted"):
            async with db.begin_nested():
                await transfer(db)
    assert not await complete(db)
    assert await db.scalar(text("SELECT share_id FROM datasets WHERE id = :id"), {"id": identity}) is None
    assert await db.scalar(text("SELECT count(*) FROM share_configs")) == configs_before
    assert await db.scalar(text("SELECT count(*) FROM dataset_grants WHERE dataset_id = :id"), {"id": identity}) == 1
    await transfer(db)
    assert await complete(db)
