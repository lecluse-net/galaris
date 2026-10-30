"""The current HTML survives the Document-to-Goal contraction atomically."""
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.goal.dbadmin import content_complete, needs_content, transfer_content
from core.dbadmin import SchemaTransitionSet


@pytest_asyncio.fixture
async def legacy_content(db):
    # PostgreSQL temporary tables shadow only these tests' synthetic sources.
    await db.execute(text("""CREATE TEMP TABLE goals (
        id uuid PRIMARY KEY, description_document_id uuid, tracking_document_id uuid,
        description text) ON COMMIT PRESERVE ROWS"""))
    await db.execute(text("""CREATE TEMP TABLE documents (
        id uuid PRIMARY KEY, content text, provider_code text, resource_id text,
        media_type text, deleted_at timestamptz) ON COMMIT PRESERVE ROWS"""))
    goal, description, tracking = uuid4(), uuid4(), uuid4()
    await db.execute(text("INSERT INTO goals VALUES(:g,:d,:t,NULL)"),
                     {"g": goal, "d": description, "t": tracking})
    await db.execute(text("""INSERT INTO documents(id,content,media_type)
        VALUES (:d,'<h1>Current objective</h1>','text/html'),
               (:t,'<p>Latest progress &amp; evidence</p>','text/html')"""),
                     {"d": description, "t": tracking})
    await db.commit()
    try:
        yield db, goal, description, tracking
    finally:
        await db.rollback()
        await db.execute(text("DROP TABLE IF EXISTS pg_temp.goals, pg_temp.documents"))
        await db.commit()


def test_content_transfer_only_applies_to_document_reference_retirement():
    assert not needs_content(SchemaTransitionSet())
    assert needs_content(SchemaTransitionSet(removed_columns=frozenset({"goals.description_document_id"})))


@pytest.mark.asyncio
async def test_current_html_transfers_once_and_sources_retire_after_verification(legacy_content):
    db, goal, _, _ = legacy_content
    delta = SchemaTransitionSet()
    assert not await content_complete(db, delta)
    await transfer_content(db, delta)
    assert await content_complete(db, delta)
    await transfer_content(db, delta)
    assert await db.scalar(text("SELECT description FROM goals WHERE id=:id"), {"id": goal}) == "<h1>Current objective</h1>"
    assert await db.scalar(text("SELECT content FROM documents WHERE deleted_at IS NULL")) == "<p>Latest progress &amp; evidence</p>"
    assert await db.scalar(text("SELECT count(*) FROM documents WHERE deleted_at IS NULL")) == 1
    await db.execute(text("ALTER TABLE goals DROP COLUMN description_document_id"))
    assert await content_complete(db, delta)


@pytest.mark.asyncio
async def test_missing_source_rolls_back_both_content_and_retirement(legacy_content):
    db, _, description, _ = legacy_content
    await db.execute(text("DELETE FROM documents WHERE id=:id"), {"id": description})
    await db.commit()
    with pytest.raises(ValueError, match="missing"):
        async with db.begin_nested():
            await transfer_content(db, SchemaTransitionSet())
    assert await db.scalar(text("SELECT description FROM goals")) is None
    assert await db.scalar(text("SELECT count(*) FROM documents WHERE deleted_at IS NOT NULL")) == 0


@pytest.mark.asyncio
async def test_transfer_reads_latest_external_bytes_and_refuses_divergent_target(legacy_content, monkeypatch):
    from app.goal import dbadmin
    from unittest.mock import AsyncMock
    db, _, description, tracking = legacy_content
    await db.execute(text("""UPDATE documents SET content=NULL,provider_code='synthetic',
        resource_id='current-snapshot' WHERE id=:id"""), {"id": description})
    storage = AsyncMock()
    storage.read.return_value = b"<p>External current HTML</p>"
    monkeypatch.setattr(dbadmin, "get_storage", lambda _code: storage)
    await transfer_content(db, SchemaTransitionSet())
    storage.read.assert_awaited_once_with("current-snapshot")
    assert await db.scalar(text("SELECT description FROM goals")) == "<p>External current HTML</p>"
    assert await db.scalar(text("SELECT deleted_at FROM documents WHERE id=:id"), {"id": tracking}) is None
    await db.execute(text("UPDATE goals SET description='<p>Different</p>'"))
    with pytest.raises(ValueError, match="differ"):
        await transfer_content(db, SchemaTransitionSet())


@pytest.mark.asyncio
async def test_a_document_used_for_tracking_is_never_retired_as_a_description(legacy_content):
    db, _, _, tracking = legacy_content
    await db.execute(text("UPDATE goals SET description_document_id=:id"), {"id": tracking})
    with pytest.raises(ValueError, match="also used for tracking"):
        await transfer_content(db, SchemaTransitionSet())
    assert await db.scalar(text("SELECT count(*) FROM documents WHERE deleted_at IS NOT NULL")) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_source", [False, True])
async def test_real_schema_upgrade_preserves_tracking_and_resumes_after_failure(
    committed_database, monkeypatch, invalid_source,
):
    from app.agent import Agent, Title
    from app.document import DocumentTag, DocumentTagAssignment
    from app.document.document_service import create_document
    from app.goal.dbadmin import register_dbadmin
    from app.goal.models import Goal
    from app.share import ShareGrant
    from core import settings as settings_module
    from core.database import get_db_session
    from core.dbadmin import DbAdminRegistry, DbAdminVerdict, orchestrator
    from core.dbadmin._internal import atlas
    from core.user import UserModel

    engine = committed_database.kw["bind"]
    monkeypatch.setattr(atlas, "engine", engine)
    monkeypatch.setattr(orchestrator, "engine", engine)
    monkeypatch.setattr(settings_module, "POSTGRES_DB", engine.url.database)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    descriptions, tracking_ids = [], []
    async with get_db_session() as db:
        user = UserModel(email="synthetic-goal-upgrade@example.test", hashed_password="unused", is_active=True)
        title = Title(label="Synthetic title", gender="M")
        db.add_all([user, title])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code="synthetic-upgrade",
            first_name="Synthetic", last_name="Owner", agent_driver="internal")
        db.add(agent)
        await db.flush()
        folder = DocumentTag(user_id=user.id, name="Personal filing")
        db.add(folder)
        await db.flush()
        for index in (1, 2):
            description = await create_document(owner_agent_id=agent.id,
                title=f"Synthetic description {index}", content=f"<p>Objective {index} — é</p>",
                task_id=None, deletion_protected=True)
            tracking = await create_document(owner_agent_id=agent.id,
                title=f"Synthetic tracking {index}", content=f"<p>Progress {index}</p>",
                task_id=None, deletion_protected=True)
            descriptions.append(description.id)
            tracking_ids.append(tracking.id)
            db.add(Goal(id=UUID(int=index), title=f"Synthetic Goal {index}", agent_id=agent.id,
                description="", tracking_document_id=tracking.id))
            db.add_all([
                DocumentTagAssignment(tag_id=folder.id, document_id=tracking.id),
                ShareGrant(share_id=tracking.share_id, user_id=user.id, can_write=False),
            ])

    async def tracking_snapshot(connection):
        # Compare the complete stored tracking resources, revisions, ACLs and
        # personal filing, rather than just their text or generated identity.
        predicates = {
            "documents": "id=ANY(:ids)",
            "document_revisions": "document_id=ANY(:ids)",
            "share_configs": "id IN (SELECT share_id FROM documents WHERE id=ANY(:ids))",
            "share_grants": "share_id IN (SELECT share_id FROM documents WHERE id=ANY(:ids))",
            "document_tags": "id=:folder",
            "document_tag_assignments": "document_id=ANY(:ids)",
        }
        return {table: await connection.scalar(text(
            f"SELECT jsonb_agg(to_jsonb(r) ORDER BY r.id) FROM {table} r WHERE {predicate}"
        ), {"ids": tracking_ids, "folder": folder.id}) for table, predicate in predicates.items()}

    async with engine.begin() as connection:
        await connection.execute(text("ALTER TABLE goals ADD COLUMN description_document_id uuid UNIQUE REFERENCES documents(id)"))
        for index, identity in enumerate(descriptions, start=1):
            await connection.execute(text("UPDATE goals SET description_document_id=:description WHERE id=:id"),
                {"description": identity, "id": UUID(int=index)})
        await connection.execute(text("ALTER TABLE goals ALTER COLUMN description_document_id SET NOT NULL"))
        await connection.execute(text("ALTER TABLE goals DROP COLUMN description"))
        # Include a recoverable soft-deleted Goal in the transfer.
        await connection.execute(text("UPDATE goals SET deleted_at=now() WHERE id=:id"), {"id": UUID(int=2)})
        if invalid_source:
            await connection.execute(text("UPDATE documents SET media_type='application/octet-stream' WHERE id=:id"),
                {"id": descriptions[1]})
        before = await tracking_snapshot(connection)

    registry = DbAdminRegistry()
    register_dbadmin(registry)
    if invalid_source:
        failed = await orchestrator.synchronize_database(target_registry=registry)
        assert failed.verdict is DbAdminVerdict.FATAL
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM goals WHERE description IS NOT NULL")) == 0
            assert await connection.scalar(text("SELECT count(*) FROM documents WHERE id=ANY(:ids) AND deleted_at IS NOT NULL"),
                {"ids": descriptions}) == 0
            assert await tracking_snapshot(connection) == before
            await connection.execute(text("UPDATE documents SET media_type='text/html' WHERE id=:id"),
                {"id": descriptions[1]})
    for _ in range(2):
        result = await orchestrator.synchronize_database(target_registry=registry)
        assert result.verdict is DbAdminVerdict.CONVERGED, result.issues
        async with engine.connect() as connection:
            assert list(await connection.scalars(text("SELECT description FROM goals ORDER BY id"))) == [
                "<p>Objective 1 — é</p>", "<p>Objective 2 — é</p>",
            ]
            assert await connection.scalar(text("SELECT count(*) FROM documents WHERE id=ANY(:ids) AND deleted_at IS NOT NULL"),
                {"ids": descriptions}) == 2
            assert await connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_name='goals' AND column_name='description_document_id'")) == 0
            assert await connection.scalar(text("SELECT is_nullable FROM information_schema.columns WHERE table_name='goals' AND column_name='description'")) == "NO"
            assert await tracking_snapshot(connection) == before
