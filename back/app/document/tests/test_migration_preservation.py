"""The final separation supersedes the old intermediate Document/Memory split."""

from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.document import Document
from app.document.independence import backup, backup_complete, transfer, transfer_complete
from app.share import ShareConfig, ShareGrant
from core.dbadmin import DbAdminRegistry, DbAdminVerdict, SchemaTransitionSet, orchestrator
from core.dbadmin._internal import atlas
from core import settings

from .test_independence_upgrade import old_schema


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["archive-corruption", "source-edit"])
async def test_preservation_refuses_corruption_and_edits_without_replacing_sources(committed_database, failure):
    async with committed_database() as session:
        expected = await old_schema(session)
        await backup(session, SchemaTransitionSet())
        await session.commit()
        assert await backup_complete(session, SchemaTransitionSet())
        await backup(session, SchemaTransitionSet())
        if failure == "archive-corruption":
            await session.execute(text("UPDATE galaris_migration.document_independence_rows SET snapshot=snapshot || '{\"content\":\"damaged\"}'::jsonb WHERE source='memory_items' AND identity=:id"), {"id": expected["id"]})
            assert not await backup_complete(session, SchemaTransitionSet())
            with pytest.raises(RuntimeError, match="archive integrity"):
                await backup(session, SchemaTransitionSet())
        else:
            await session.execute(text("UPDATE memory_items SET lock_version=lock_version+1 WHERE id=:id"), {"id": expected["id"]})
            with pytest.raises(RuntimeError, match="source changed"):
                await transfer(session, SchemaTransitionSet())
        assert await session.scalar(text("SELECT resource_id FROM memory_items WHERE id=:id"), {"id": expected["id"]}) == expected["summary_pointer"]


@pytest.mark.asyncio
async def test_shared_legacy_memory_keeps_its_access_and_later_document_edits_survive_replay(committed_database, monkeypatch):
    from app.document.independence import register_independence

    engine = committed_database.kw["bind"]
    monkeypatch.setattr(orchestrator, "engine", engine)
    monkeypatch.setattr(atlas, "engine", engine)
    monkeypatch.setattr(settings, "POSTGRES_DB", engine.url.database)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    async with committed_database() as session:
        expected = await old_schema(session)
        policy = await session.scalar(text("SELECT share_id FROM memory_items WHERE id=:id"), {"id":expected["private"]})
        session.add(ShareGrant(share_id=policy, agent_id=expected["reader"], can_write=True))
        await session.commit()
    registry = DbAdminRegistry()
    register_independence(registry)
    result = await orchestrator.synchronize_database(target_registry=registry)
    assert result.verdict is DbAdminVerdict.CONVERGED
    async with committed_database() as session:
        converted = await session.get(Document, expected["private"])
        assert converted is not None
        assert converted.content == "<p>Private synthetic memory.</p>"
        assert await session.scalar(select(ShareGrant.can_write).where(ShareGrant.share_id==converted.share_id, ShareGrant.agent_id==expected["reader"])) is True
        updated = "<p>Newly authored content after migration.</p>"
        await session.execute(text("UPDATE documents SET revision=revision+1,content=:content,content_hash=:digest,resource_id=:pointer WHERE id=:id"),
            {"id":expected["id"],"content":updated,"digest":sha256(updated.encode()).hexdigest(),"pointer":str(uuid4())})
        await session.commit()
        assert await transfer_complete(session, SchemaTransitionSet())
        await transfer(session, SchemaTransitionSet())
        assert await session.scalar(select(Document.content).where(Document.id==expected["id"])) == updated
