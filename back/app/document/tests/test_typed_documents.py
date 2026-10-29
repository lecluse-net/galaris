"""One identity, library, history and live policy for Text and Data documents."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.document import document_service, resource_service
from app.document.models import Document, DocumentRevision, DocumentTag, DocumentTagAssignment
from app.document.data import service as data_service
from app.document.data.models import Dataset, LegacyDataset, LegacyDatasetRevision
from app.document.library_queries import browse_document_library
from app.document.schemas import DocumentLibraryRequest, DocumentPayload, DocumentUpdate
from app.document.unification import preserve, finalize, complete, needed
from app.share import ShareGrant
from core.dbadmin import SchemaTransitionSet
from core.user import HumanActor, UserModel


@pytest.mark.asyncio
async def test_types_share_library_content_history_and_current_metadata(db, agents, memory_storage):
    owner, reader = agents
    prose = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic prose",
        content="<p>Notes</p>", task_id=None)
    values = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic values",
        content=' {"value": 1}\n', task_id=None, document_type="data")
    assert prose.document_type == "text" and values.document_type == "data"
    assert Dataset.__table__ is Document.__table__
    for kind, identity in (("text", prose.id), ("data", values.id)):
        result = await browse_document_library(DocumentLibraryRequest(document_type=kind),
            managed_agent_ids=(owner.id,), user_id=owner.user_id)
        assert [entry.item.id for entry in result.entries] == [identity]
    identity = values.id
    changed = await resource_service.update_item(identity, DocumentUpdate(expected_revision=1,
        payload=DocumentPayload(text='{"value":2}')), actor_agent_id=owner.id)
    assert changed.revision == 2
    assert (await data_service.record(identity, owner.id)).content == '{"value":2}'
    with pytest.raises((resource_service.DocumentPermissionError, resource_service.DocumentNotFoundError)):
        await resource_service.get_item(identity, agent_id=reader.id)
    with pytest.raises(ValueError):
        await resource_service.update_item(identity, DocumentUpdate(expected_revision=2,
            payload=DocumentPayload(text='{"invalid":')), actor_agent_id=owner.id)
    assert (await data_service.record(identity, owner.id)).content == '{"value":2}'
    await data_service.metadata(identity, owner.id, expected_lock_version=changed.lock_version,
        values={"title": "Synthetic renamed values", "keywords": ["current"]})
    restored = await data_service.restore(identity, owner.id, number=1, expected_revision=2)
    assert restored.content == ' {"value": 1}\n' and restored.revision == 3
    assert restored.title == "Synthetic renamed values" and restored.keywords == ["current"]
    assert await db.scalar(select(func.count()).select_from(DocumentRevision).where(DocumentRevision.document_id == identity)) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("projection", [False, True])
async def test_migration_preserves_exact_sources_rights_history_and_replay(db, agents, memory_storage, projection):
    owner, reader = agents
    owner_id, reader_id = owner.id, reader.id
    identity = uuid4()
    old = LegacyDataset(id=identity, owner_agent_id=owner_id, title="Synthetic migration source",
        content=' {"é": 2}\n', revision=2, lock_version=4, keywords=["synthetic"],
        metadata_={"preserved": True}, summary_content="Synthetic current description")
    db.add(old)
    if projection:
        db.add(Document(id=identity, owner_agent_id=owner_id, title="Synthetic old projection", document_type="dataset",
            provider_code="native", resource_id=str(identity), content="{}", content_hash="0"*64,
            content_type="text", media_type="application/json", revision=1))
    await db.flush()
    outsider = UserModel(email=f"synthetic-migration-outsider-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
    db.add(outsider)
    await db.flush()
    outsider_id = outsider.id
    if projection:
        obsolete = DocumentTag(user_id=owner.user_id, name="Synthetic obsolete shared placement", global_access=1)
        db.add(obsolete)
        await db.flush()
        db.add(DocumentTagAssignment(tag_id=obsolete.id, document_id=identity))
    db.add_all([LegacyDatasetRevision(dataset_id=identity, revision=1, content=' {"é": 1}\n', author_agent_id=owner_id),
                LegacyDatasetRevision(dataset_id=identity, revision=2, content=old.content, author_user_id=owner.user_id),
                ShareGrant(share_id=old.share_id, agent_id=reader_id, can_write=True)])
    await db.commit()
    # An old installation has not yet finalized the common classification.
    await db.execute(text("DELETE FROM galaris_migration.typed_document_state"))
    delta = SchemaTransitionSet(added_columns=frozenset({"documents.storage_kind"}))
    assert needed(delta) and not needed(SchemaTransitionSet())
    await preserve(db, delta)
    await finalize(db, delta)
    from app.document.sharing_inheritance import reconcile_sharing
    await reconcile_sharing()
    assert await complete(db, delta)
    await db.commit()
    db.expunge_all()
    migrated = await data_service.record(identity, reader_id, write=True)
    with pytest.raises(data_service.DatasetNotFoundError):
        await data_service.record(identity, HumanActor(outsider_id))
    assert migrated.content == ' {"é": 2}\n' and migrated.revision == 2
    assert migrated.keywords == ["synthetic"] and migrated.summary_content == "Synthetic current description"
    assert migrated.summary_media_type == "text/plain"
    assert (await data_service.revision(identity, owner_id, 1)).content == ' {"é": 1}\n'
    assert (await data_service.revision(identity, owner_id, 2)).author_user_id is not None
    await data_service.replace(identity, owner_id, content='{"later":true}', expected_revision=2)
    await data_service.set_grant(identity, owner_id, kind="agent", principal=reader_id,
        can_write=None, expected_lock_version=migrated.lock_version)
    await db.commit()
    await preserve(db, delta)
    await finalize(db, delta)
    await db.commit()
    assert (await data_service.record(identity, owner_id)).content == '{"later":true}'
    with pytest.raises(data_service.DatasetNotFoundError):
        await data_service.record(identity, reader_id)
    assert await db.scalar(text("SELECT content FROM datasets WHERE id=:id"), {"id": identity}) == ' {"é": 2}\n'


@pytest.mark.asyncio
async def test_migration_rejects_identity_collision_and_rolls_back(db, agents, memory_storage):
    owner, _ = agents
    prose = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic independent identity",
        content="<p>Keep me</p>", task_id=None)
    identity = prose.id
    db.add(LegacyDataset(id=identity, owner_agent_id=owner.id, title="Synthetic conflicting source", content="{}"))
    await db.commit()
    with pytest.raises(ValueError, match="unrelated"):
        await preserve(db, SchemaTransitionSet())
    await db.rollback()
    assert await db.scalar(select(Document.content).where(Document.id == identity)) == "<p>Keep me</p>"


@pytest.mark.asyncio
async def test_common_http_data_creation_restore_and_write_budget_share_one_record(client, monkeypatch):
    credentials = {"email": "synthetic-typed-owner@example.com", "password": "Synthetic-typed-password-123"}
    registered = await client.post("/api/auth/register", json=credentials)
    assert registered.status_code == 201, registered.text
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": "Bearer " + login.json()["access_token"], "X-Editorial-Profile-Version": "1"}
    created = await client.post("/api/documents", headers=headers, json={
        "owner_kind": "user", "owner_id": registered.json()["id"], "title": "Synthetic common Data", "document_type": "data"})
    assert created.status_code == 201, created.text
    identity = created.json()["id"]
    path = f"/api/documents/{identity}"
    invalid = await client.patch(path, headers=headers, json={"expected_revision": 1, "payload": {"text": "{"}})
    assert invalid.status_code == 422, invalid.text
    saved = await client.patch(path, headers=headers, json={"expected_revision": 1, "payload": {"text": '{"value":2}'}})
    assert saved.status_code == 200, saved.text
    conflict = await client.post(path + "/content-revisions/1/restore", headers=headers, json={"expected_revision": 1})
    assert conflict.status_code == 409, conflict.text
    restored = await client.post(path + "/content-revisions/1/restore", headers=headers, json={"expected_revision": 2})
    assert restored.status_code == 200, restored.text
    # A fresh HTTP request observes the committed restoration through both APIs.
    assert (await client.get(path, headers=headers)).json()["item"]["payload"]["text"] == "[]"
    assert (await client.get(f"/api/datasets/{identity}", headers=headers)).json()["content"] == "[]"
    monkeypatch.setattr(data_service, "MAX_WRITES", 2)
    for url, method, body in ((path, client.patch, {"payload": {"text": "null"}}),
                             (f"/api/datasets/{identity}/content", client.put, {"content": "null"})):
        limited = await method(url, headers=headers, json={"expected_revision": 3, **body})
        assert limited.status_code == 429, limited.text
    assert (await client.get(f"/api/datasets/{identity}", headers=headers)).json()["content"] == "[]"
