"""Real schema expansion/resume and immutable binary revision lifetimes."""

from dataclasses import replace
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import select, text

from app.document import document_service, resource_service
from app.document.content import bind_binary_content
from app.document.data.models import Dataset, DatasetAppearance, DatasetAttachment, DatasetAppConsent, DatasetTag, DatasetTagAssignment, LegacyDataset, LegacyDatasetRevision
from app.document.models import Document, DocumentRevision, DocumentTag, DocumentTagAssignment, DocumentIcon, DocumentListPosition, DocumentAttachment, DocumentSource, DocumentURL
from app.share import ShareGrant
from app.document.unification import register
from core import settings as settings_module
from core.database import get_db_session
from core.dbadmin import DbAdminRegistry, DbAdminVerdict, orchestrator
from core.dbadmin._internal import atlas
from core.storage import FileAlias, file_path, get_storage, register_file, retire_file_reference, purge_retired_file
from core.user import UserModel, HumanActor


async def text_document_snapshot(connection, identity, folder, file):
    """Compare all persisted source fields except the explicit type/schema delta."""
    predicates = {
        "documents": "id=:id", "document_revisions": "document_id=:id",
        "document_tags": "id=:folder", "document_tag_assignments": "document_id=:id",
        "document_icons": "document_id=:id", "document_list_positions": "document_id=:id",
        "document_attachments": "document_id=:id", "document_sources": "document_id=:id",
        "document_urls": "document_id=:id", "files": "id=:file", "file_aliases": "file_id=:file",
        "share_configs": "id IN (SELECT share_id FROM documents WHERE id=:id UNION SELECT share_id FROM document_tags WHERE id=:folder)",
        "share_grants": "share_id IN (SELECT share_id FROM documents WHERE id=:id UNION SELECT share_id FROM document_tags WHERE id=:folder)",
    }
    excluded = {
        "documents": ["document_type", "storage_kind", "file_id", "creation_key", "creation_fingerprint", "summary_media_type"],
        "document_revisions": ["author_user_id", "storage_kind", "file_id", "document_source_revision_id"],
    }
    return {table: await connection.scalar(text(f"SELECT coalesce(jsonb_agg(to_jsonb(r) - CAST(:excluded AS text[]) ORDER BY r.id),'[]'::jsonb) FROM {table} r WHERE {predicate}"),
        {"id": identity, "folder": folder, "file": file, "excluded": excluded.get(table, [])}) for table, predicate in predicates.items()}


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_old_dataset_schema_upgrades_and_resumes_without_losing_sources(committed_database, monkeypatch, interrupted):
    engine = committed_database.kw["bind"]
    monkeypatch.setattr(atlas, "engine", engine)
    monkeypatch.setattr(orchestrator, "engine", engine)
    monkeypatch.setattr(settings_module, "POSTGRES_DB", engine.url.database)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    identity = uuid4()
    text_identity = uuid4()
    folder_identity = uuid4()
    attachment_identity, consent_identity = uuid4(), uuid4()
    text_folder, text_file = uuid4(), uuid4()
    prose_source = '<article lang="fr"><h1>Été — référence synthétique</h1>\r\n<form><input name="n" value="é"></form><script>const value = "<keep>";</script></article>'
    prose_history = '<p>Version initiale synthétique — é\u00a0fin.</p>\r\n'
    prose_summary = '<p>Description manuelle synthétique — conservée.</p>'
    attachment_bytes = b"synthetic-text-attachment\x00\xff\x01"
    attachment_path = file_path(text_file)
    attachment_path.parent.mkdir(parents=True, exist_ok=True)
    attachment_path.write_bytes(attachment_bytes)
    source = ' {"synthetic": [false, "é", null]}\n'
    # Reconstruct source FKs as well as columns: Atlas must only redirect these
    # populated references after the canonical Document identity exists.
    async with engine.begin() as connection:
        for table in ("dataset_attachments", "dataset_app_consents", "dataset_tag_assignments", "dataset_appearances"):
            await connection.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT {table}_dataset_id_fkey'))
            await connection.execute(text(f'ALTER TABLE {table} ADD CONSTRAINT {table}_dataset_id_fkey FOREIGN KEY(dataset_id) REFERENCES datasets(id)'))
    async with get_db_session() as session:
        owner = UserModel(email="synthetic-document-upgrade@example.test", hashed_password="unused", is_active=True)
        session.add(owner)
        await session.flush()
        session.add(LegacyDataset(id=identity, owner_user_id=owner.id, title="Synthetic old data",
            content=source, revision=1, keywords=["preserved"], metadata_={"synthetic": True}))
        session.add(Document(id=text_identity, owner_user_id=owner.id, title="Synthetic old HTML",
            stored_document_type="html", provider_code="native", resource_id=str(text_identity),
            content=prose_source, content_hash=sha256(prose_source.encode()).hexdigest(), size_bytes=len(prose_source.encode()), revision=2,
            keywords=["synthétique", "manuel"], metadata_={"synthetic": {"nested": [1, False, None]}},
            summary_content=prose_summary, summary_resource_id=str(uuid4()), summary_content_hash=sha256(prose_summary.encode()).hexdigest(),
            summary_size_bytes=len(prose_summary.encode()), summary_generated=False, summary_source_text="Synthetic baseline",
            content_type="text", media_type="text/html", content_profile_version=1))
        await session.flush()
        peer = UserModel(email="synthetic-document-upgrade-reader@example.test", hashed_password="unused", is_active=True)
        session.add_all([peer, DocumentTag(id=text_folder, user_id=owner.id, name="Synthetic Text folder", position=4)])
        await session.flush()
        prose = await session.get(Document, text_identity)
        session.add_all([
            DocumentTagAssignment(document_id=text_identity, tag_id=text_folder, position=11),
            DocumentIcon(user_id=owner.id, document_id=text_identity, icon="emoji:1F4D6"),
            DocumentListPosition(user_id=owner.id, document_id=text_identity, position=6, at_root=False),
            ShareGrant(share_id=prose.share_id, user_id=peer.id, can_write=False),
            DocumentSource(document_id=text_identity, source_kind="synthetic", source_ref="https://example.test/synthetic-proof", metadata_={"synthetic": True}),
            DocumentURL(document_id=text_identity, url="https://example.test/synthetic-location"),
            DocumentAttachment(id=text_file, document_id=text_identity),
        ])
        await register_file(text_file, name="synthetic-proof.bin", media_type="application/octet-stream", alias=f"document://{text_identity}/attachments/{text_file}")
        for version, content in ((1, prose_history), (2, prose_source)):
            session.add(DocumentRevision(document_id=text_identity, revision=version, provider_code="native", resource_id=str(uuid4()),
                content=content, content_hash=sha256(content.encode()).hexdigest(), title="Synthetic old HTML",
                content_type="text", media_type="text/html", content_profile_version=1, metadata_={"synthetic_revision": version}))
        session.add(LegacyDatasetRevision(dataset_id=identity, revision=1, content=source, author_user_id=owner.id))
        session.add(DatasetTag(id=folder_identity, user_id=owner.id, name="Synthetic source folder", icon="folder:blue", position=9))
        await session.flush()
        session.add_all([
            DatasetTagAssignment(dataset_id=identity, tag_id=folder_identity, position=7),
            DatasetAppearance(dataset_id=identity, user_id=owner.id, icon="emoji:1F680", position=3, at_root=False),
            DatasetAttachment(id=attachment_identity, dataset_id=identity, uri=f"file://{uuid4()}",
                name="synthetic.txt", media_type="text/plain", size_bytes=0),
            DatasetAppConsent(id=consent_identity, dataset_id=identity, document_id=text_identity,
                user_id=owner.id, app_key="synthetic-form", alias="values", document_revision=1, access="read"),
        ])
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE document_summary_revisions (id uuid PRIMARY KEY, document_id uuid, provider_code text, resource_id text, content text)"))
        await connection.execute(text("INSERT INTO document_summary_revisions SELECT :revision,id,'native',summary_resource_id,summary_content FROM documents WHERE id=:id"),
            {"revision": uuid4(), "id": text_identity})
        await connection.execute(text("INSERT INTO document_summary_revisions VALUES (:revision,:id,'native',:pointer,'<p>Previous synthetic description — é.</p>')"),
            {"revision": uuid4(), "id": text_identity, "pointer": str(uuid4())})
        before_summaries = await connection.scalar(text("SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM document_summary_revisions r"))
        for table in ("typed_document_sources", "typed_document_transfers", "typed_document_state", "typed_document_roles"):
            await connection.execute(text(f"DROP TABLE IF EXISTS galaris_migration.{table}"))
        for column in ("storage_kind", "file_id", "creation_key", "creation_fingerprint", "summary_media_type"):
            await connection.execute(text(f"ALTER TABLE documents DROP COLUMN {column} CASCADE"))
        for column in ("author_user_id", "storage_kind", "file_id", "document_source_revision_id"):
            await connection.execute(text(f"ALTER TABLE document_revisions DROP COLUMN {column} CASCADE"))
        before_text = await text_document_snapshot(connection, text_identity, text_folder, text_file)
    registry = DbAdminRegistry()
    register(registry)
    from app.document.summary_retirement import register as register_summary_retirement
    register_summary_retirement(registry)
    if interrupted:
        failed_registry = DbAdminRegistry()

        async def fail_after_expansion(session, delta):
            raise RuntimeError("Synthetic interruption after typed document expansion")

        for action in registry.actions:
            failed_registry.register_action(replace(action, handler=fail_after_expansion)
                if action.key == "app.document.typed_documents" else action)
        failed = await orchestrator.synchronize_database(target_registry=failed_registry)
        assert failed.verdict is DbAdminVerdict.FATAL
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT content FROM datasets WHERE id=:id"), {"id": identity}) == source
            assert await connection.scalar(text("SELECT content FROM documents WHERE id=:id"), {"id": identity}) == source
            assert await text_document_snapshot(connection, text_identity, text_folder, text_file) == before_text
            assert attachment_path.read_bytes() == attachment_bytes
            assert await connection.scalar(text("SELECT to_regclass('public.document_summary_revisions')")) is not None
            assert await connection.scalar(text("SELECT jsonb_agg(snapshot ORDER BY identity) FROM galaris_migration.document_summary_history_sources")) == before_summaries
    for _ in range(2):
        result = await orchestrator.synchronize_database(target_registry=registry)
        assert result.verdict is DbAdminVerdict.CONVERGED, result.issues
        async with get_db_session() as session:
            document = await session.get(Dataset, identity)
            assert document is not None and document.content == source
            assert document.document_type == "data" and document.storage_kind == "text"
            assert document.keywords == ["preserved"] and document.metadata_ == {"synthetic": True}
            prose = await session.get(Document, text_identity)
            assert prose.stored_document_type == "text" and prose.content == prose_source
            revision = await session.scalar(select(DocumentRevision).where(DocumentRevision.document_id == identity))
            assert revision.content == source and revision.author_user_id is not None
            folder = await session.get(DocumentTag, uuid5(NAMESPACE_URL, f"galaris:data-folder:{folder_identity}"))
            assert folder.name == "Synthetic source folder" and folder.position == 9
            assert await session.scalar(select(DocumentTagAssignment.position).where(
                DocumentTagAssignment.document_id == identity, DocumentTagAssignment.tag_id == folder.id)) == 7
            assert await session.scalar(select(DocumentIcon.icon).where(DocumentIcon.document_id == identity)) == "emoji:1F680"
            assert await session.scalar(select(DocumentListPosition.position).where(DocumentListPosition.document_id == identity)) == 3
            assert (await session.get(DatasetAttachment, attachment_identity)).dataset_id == identity
            assert (await session.get(DatasetAppConsent, consent_identity)).access == "read"
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT content FROM datasets WHERE id=:id"), {"id": identity}) == source
            assert await text_document_snapshot(connection, text_identity, text_folder, text_file) == before_text
            assert attachment_path.read_bytes() == attachment_bytes
            assert await connection.scalar(text("SELECT to_regclass('public.document_summary_revisions')")) is None
            assert await connection.scalar(text("SELECT jsonb_agg(snapshot ORDER BY identity) FROM galaris_migration.document_summary_history_sources")) == before_summaries
    # Historical content remains usable through the actual restore command.
    from app.document.inline_content import register_content
    register_content()
    async with get_db_session() as session:
        prose = await session.get(Document, text_identity)
        await resource_service.restore_document_content_revision(text_identity, 1,
            expected_revision=2, actor_agent_id=HumanActor(prose.owner_user_id))
        await session.refresh(prose)
        # Restoration creates a normalized editor version. The original archived
        # HTML, including trailing CRLF, remains available without alteration.
        assert prose.content == prose_history.rstrip() and prose.revision == 3
        archived = await resource_service.get_document_content_revision(text_identity, 1, actor_agent_id=HumanActor(prose.owner_user_id))
        assert archived.content == prose_history
        assert prose.summary_content == prose_summary and prose.keywords == ["synthétique", "manuel"]
        assert attachment_path.read_bytes() == attachment_bytes


@pytest.mark.asyncio
async def test_binary_historical_reference_preserves_exact_bytes(db, agents, memory_storage):
    owner, _ = agents
    document = await document_service.create_document(owner_agent_id=owner.id,
        title="Synthetic storage lifetime", content="<p>Initial</p>", task_id=None)
    identity = uuid4()
    path = file_path(identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    source = b"synthetic-binary\x00\xff\x01"
    path.write_bytes(source)
    file = await register_file(identity, name="synthetic.bin", media_type="application/octet-stream", alias="file://synthetic-source")
    document.revision = 2
    await bind_binary_content(document, identity)
    db.add(DocumentRevision(document_id=document.id, revision=2, file_id=identity, storage_kind="file",
        provider_code="native", resource_id=str(identity), content=None, content_type="binary",
        media_type=file.media_type, content_hash=file.sha256, title=document.title))
    await db.commit()
    assert await get_storage("native").read(str(identity)) == source
    document.file_id, document.storage_kind = None, "text"
    document.content, document.resource_id = "<p>Later</p>", str(uuid4())
    await db.commit()
    await retire_file_reference("file://synthetic-source")
    await db.commit()
    assert not await purge_retired_file(identity)
    assert await get_storage("native").read(str(identity)) == source
    assert path.read_bytes() == source
    await resource_service.delete_document(document.id, actor_agent_id=owner.id)
    assert document.file_id is None and document.storage_kind == "text"
    assert await db.scalar(select(FileAlias.id).where(FileAlias.file_id == identity)) is None
