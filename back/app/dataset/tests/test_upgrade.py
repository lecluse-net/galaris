"""Upgrade from documentary Datasets through the real DbAdmin/Atlas boundary."""

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.dataset.dbadmin import register_dbadmin
from app.dataset.models import Dataset, DatasetAppConsent, DatasetRevision, DatasetWriteBudget
from app.document import Document, DocumentAppGrant, DocumentAppWriteBudget, DocumentRevision
from app.share import ShareGrant
from core import settings
from core.database import get_db_session
from core.dbadmin import DbAdminRegistry, DbAdminVerdict, orchestrator
from core.dbadmin._internal import atlas
from core.dbadmin._internal.target import load_target_metadata
from core.storage import prepare_content
from core.user import UserModel


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_upgrade_preserves_dataset_app_references_and_resumes_after_expansion(
    committed_database, monkeypatch, memory_storage, interrupted,
):
    isolated = committed_database.kw["bind"]
    monkeypatch.setattr(atlas, "engine", isolated)
    monkeypatch.setattr(orchestrator, "engine", isolated)
    monkeypatch.setattr(settings, "POSTGRES_DB", isolated.url.database)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    target = load_target_metadata()
    dataset_tables = [name for name in target.tables if name == "datasets" or name.startswith("dataset_")]
    async with isolated.begin() as connection:
        for name in dataset_tables:
            await connection.execute(text(f'DROP TABLE "{name}" CASCADE'))
        # Native Process adds a dependency cycle in the same main -> dev delta.
        for name in ("process_node_runs", "process_node_attempts"):
            await connection.execute(text(f'DROP TABLE "{name}" CASCADE'))
        for name in ("document_app_grants", "document_app_write_budgets"):
            await connection.execute(text(
                f'ALTER TABLE "{name}" ADD CONSTRAINT "{name}_dataset_id_fkey" '
                'FOREIGN KEY (dataset_id) REFERENCES documents(id)'
            ))

    content = '{\n "synthetic": [false, 0, null]\n}\n'
    pointer, inline = await prepare_content(content.encode())
    async with get_db_session() as session:
        owner = UserModel(email="synthetic-dataset-upgrade@example.test", hashed_password="unused", is_active=True)
        reader = UserModel(email="synthetic-dataset-reader@example.test", hashed_password="unused", is_active=True)
        session.add_all([owner, reader])
        await session.flush()
        document = Document(id=uuid4(), owner_user_id=owner.id, title="Synthetic historical JSON",
            document_type="dataset", provider_code="native", resource_id=pointer, content=inline,
            content_type="text", media_type="application/json", content_hash=sha256(content.encode()).hexdigest(),
            size_bytes=len(content.encode()), keywords=[], metadata_={})
        session.add(document)
        await session.flush()
        session.add(DocumentRevision(document_id=document.id, revision=1, provider_code="native",
            resource_id=pointer, content=inline, content_type="text", media_type="application/json",
            content_hash=document.content_hash, title=document.title, keywords=[], metadata_={},
            document_content_version=True))
        session.add(ShareGrant(share_id=document.share_id, user_id=reader.id, can_write=False))
        consent = DocumentAppGrant(user_id=owner.id, document_id=document.id, dataset_id=document.id,
            app_key="synthetic-app", alias="answers", document_revision=1, access="write")
        window = datetime(2026, 1, 1, tzinfo=timezone.utc)
        session.add_all([consent, DocumentAppWriteBudget(user_id=owner.id, dataset_id=document.id,
            window_start=window, writes=3, bytes_written=128)])
        await session.commit()

    registry = DbAdminRegistry()
    register_dbadmin(registry)
    if interrupted:
        failed_registry = DbAdminRegistry()

        async def fail_before_transfer(session, delta):
            raise RuntimeError("Synthetic interruption after expansion")

        for action in registry.actions:
            failed_registry.register_action(replace(action, handler=fail_before_transfer))
        failed = await orchestrator.synchronize_database(target_registry=failed_registry)
        assert failed.verdict is DbAdminVerdict.FATAL
        assert any(issue.object_name == "app.dataset.legacy_documents" for issue in failed.issues)
        async with isolated.connect() as connection:
            assert await connection.scalar(text("SELECT to_regclass('public.datasets')")) == "datasets"
            for name in ("document_app_grants", "document_app_write_budgets"):
                assert await connection.scalar(text(
                    "SELECT confrelid::regclass::text FROM pg_constraint WHERE conname=:name"
                ), {"name": f"{name}_dataset_id_fkey"}) == "documents"

    for _ in range(2):
        result = await orchestrator.synchronize_database(target_registry=registry)
        assert result.verdict is DbAdminVerdict.CONVERGED, result.issues
        async with get_db_session() as session:
            dataset = await session.get(Dataset, document.id)
            assert dataset is not None and dataset.content == content
            assert dataset.owner_user_id == owner.id
            assert await session.scalar(select(DatasetRevision.content).where(
                DatasetRevision.dataset_id == document.id, DatasetRevision.revision == 1)) == content
            migrated_consent = await session.get(DatasetAppConsent, consent.id)
            assert migrated_consent is not None
            assert (migrated_consent.document_id, migrated_consent.dataset_id, migrated_consent.user_id,
                migrated_consent.app_key, migrated_consent.alias, migrated_consent.document_revision,
                migrated_consent.access) == (document.id, document.id, owner.id, "synthetic-app", "answers", 1, "write")
            budget = await session.scalar(select(DatasetWriteBudget).where(DatasetWriteBudget.dataset_id == document.id))
            assert budget is not None
            assert (budget.user_id, budget.window_start, budget.writes, budget.bytes_written) == (owner.id, window, 3, 128)
            assert await session.scalar(select(ShareGrant.can_write).where(
                ShareGrant.share_id == dataset.share_id, ShareGrant.user_id == reader.id)) is False
            assert await session.get(DocumentAppGrant, consent.id) is not None
            assert await session.scalar(select(DocumentAppWriteBudget.writes).where(
                DocumentAppWriteBudget.dataset_id == document.id)) == 3
        async with isolated.connect() as connection:
            for name in ("document_app_grants", "document_app_write_budgets"):
                assert await connection.scalar(text(
                    "SELECT confrelid::regclass::text FROM pg_constraint WHERE conname=:name"
                ), {"name": f"{name}_dataset_id_fkey"}) == "datasets"
