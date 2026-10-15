"""Removing Dataset constraints preserves existing JSON, history and access."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.dataset import service
from app.dataset.models import DatasetAttachment
from core.database import get_db_session
from core import settings
from core.dbadmin import DbAdminRegistry, DbAdminVerdict
from core.dbadmin import orchestrator
from core.dbadmin._internal import atlas
from core.user import HumanActor, UserModel


@pytest.mark.asyncio
async def test_dbadmin_removes_populated_schema_bindings_without_changing_dataset_data(committed_database, monkeypatch):
    isolated = committed_database.kw["bind"]
    monkeypatch.setattr(orchestrator, "engine", isolated)
    monkeypatch.setattr(atlas, "engine", isolated)
    monkeypatch.setattr(settings, "POSTGRES_DB", isolated.url.database)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    async with get_db_session() as session:
        owner = UserModel(email=f"schema-removal-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
        reader = UserModel(email=f"schema-reader-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
        session.add_all([owner, reader])
        await session.flush()
        actor = HumanActor(owner.id)
        dataset = await service.create(actor, title="Synthetic legacy constrained data", content='{\n "accepted": false\n}\n')
        await service.replace(dataset.id, actor, content='{\n "accepted": true\n}\n', expected_revision=1)
        await service.set_grant(dataset.id, actor, kind="user", principal=reader.id, can_write=False, expected_lock_version=2)
        session.add(DatasetAttachment(dataset_id=dataset.id, uri="https://example.test/synthetic.pdf",
            name="Synthetic external attachment", media_type="application/pdf"))
        before = await service.describe(dataset, actor)
        sharing = await service.sharing(dataset.id, actor)
        await session.commit()

    # Reconstruct only the retired structures in this test's private database.
    schema = uuid4()
    async with isolated.begin() as connection:
        await connection.execute(text("CREATE TABLE dataset_schemas (id uuid PRIMARY KEY, definition jsonb NOT NULL)"))
        await connection.execute(text("CREATE TABLE dataset_schema_revisions (id uuid PRIMARY KEY, schema_id uuid REFERENCES dataset_schemas(id), revision integer, definition jsonb NOT NULL)"))
        await connection.execute(text("ALTER TABLE datasets ADD COLUMN schema_id uuid REFERENCES dataset_schemas(id), ADD COLUMN schema_revision integer, ADD COLUMN schema_snapshot jsonb, ADD COLUMN schema_mode varchar(20), ADD CHECK (schema_mode IS NULL OR schema_mode IN ('variables','records')), ADD CHECK ((schema_snapshot IS NULL AND schema_mode IS NULL) OR (schema_snapshot IS NOT NULL AND schema_mode IS NOT NULL))"))
        await connection.execute(text("CREATE INDEX ix_datasets_schema_id ON datasets (schema_id)"))
        await connection.execute(text("ALTER TABLE dataset_revisions ADD COLUMN schema_snapshot jsonb, ADD COLUMN schema_mode varchar(20)"))
        definition = '{"fields":[{"name":"accepted","type":"bool"}]}'
        await connection.execute(text("INSERT INTO dataset_schemas VALUES (:id, CAST(:definition AS jsonb))"), {"id": schema, "definition": definition})
        await connection.execute(text("INSERT INTO dataset_schema_revisions VALUES (:id, :schema, 1, CAST(:definition AS jsonb))"), {"id": uuid4(), "schema": schema, "definition": definition})
        await connection.execute(text("UPDATE datasets SET schema_id=:schema, schema_revision=1, schema_snapshot=CAST(:definition AS jsonb), schema_mode='variables' WHERE id=:id"), {"id": dataset.id, "schema": schema, "definition": definition})
        await connection.execute(text("UPDATE dataset_revisions SET schema_snapshot=CAST(:definition AS jsonb), schema_mode='variables' WHERE dataset_id=:id"), {"id": dataset.id, "definition": definition})

    for _ in range(2):
        result = await orchestrator.synchronize_database(target_registry=DbAdminRegistry())
        assert result.verdict is DbAdminVerdict.CONVERGED, result.issues
        async with isolated.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('dataset_schemas','dataset_schema_revisions')")) == 0
            assert await connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name IN ('datasets','dataset_revisions') AND column_name IN ('schema_id','schema_revision','schema_snapshot','schema_mode')")) == 0

    async with get_db_session() as session:
        current = await service.record(dataset.id, actor)
        assert await service.describe(current, actor) == before
        assert await service.sharing(dataset.id, actor) == sharing
        assert (await service.revision(dataset.id, actor, 1)).content == '{\n "accepted": false\n}\n'
        assert (await service.revision(dataset.id, actor, 2)).content == '{\n "accepted": true\n}\n'
        assert await service.record(dataset.id, HumanActor(reader.id)) is current
        from app.dataset.attachments import list_attachments
        attachments = await list_attachments(dataset.id, actor)
        assert len(attachments) == 1 and attachments[0]["uri"] == "https://example.test/synthetic.pdf"
        await service.replace(dataset.id, actor, content='[0,false,null,{"free":"JSON"}]', expected_revision=2)
        await service.restore(dataset.id, actor, number=1, expected_revision=3)
        assert current.content == '{\n "accepted": false\n}\n'
