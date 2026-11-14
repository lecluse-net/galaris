"""Topic navigation derives only from readable documents; moves are atomic."""

from uuid import uuid4

import pytest

from app.agent import AgentManagementScope
from app.document import resource_service as documents, document_tags
from app.document.models import Document
from app.document.schemas import DocumentItemCreate, DocumentPayload, DocumentLibraryRequest, DocumentTopicMove, DocumentTagWrite
from app.document.schemas import DocumentGrantUpdate
from app.topic.service import document_library as catalog, move_library_document as move
from app.topic import Topic
from core.user import UserModel


async def setup_library(db, agents):
    owner, peer = agents
    user = UserModel(email=f"topic-library-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    topics = [Topic(title=title, description="Synthetic topic", keywords=[]) for title in ("Synthetic Alpha", "Synthetic Beta")]
    db.add_all(topics)
    await db.flush()
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({owner.id}))
    items = []
    for title, agent, topic, keywords, kind in (
        ("Synthetic plan", owner, topics[0], ["common", "source", "retained"], "text"),
        ("Synthetic figures", owner, topics[0], ["common"], "data"),
        ("Synthetic plain", owner, topics[0], [], "text"),
        ("Synthetic target", owner, topics[1], ["common", "target"], "text"),
        ("Synthetic private", peer, topics[1], ["private-tag"], "text"),
        ("Synthetic inbox", owner, None, ["inbox"], "text"),
    ):
        item, _ = await documents.create_item(DocumentItemCreate(owner_agent_id=agent.id,
            title=title, document_type=kind, media_type="application/json" if kind == "data" else "text/html",
            keywords=keywords, payload=DocumentPayload(text="{}" if kind == "data" else "<p>Synthetic content</p>")))
        item.topic_id = topic.id if topic else None
        items.append(item)
    await db.commit()
    return scope, topics, items


@pytest.mark.asyncio
async def test_catalog_and_branches_use_all_readable_documents_independent_of_manual_folders(db, agents, memory_storage):
    scope, topics, items = await setup_library(db, agents)
    folder = await document_tags.write_tag(scope.user_id, DocumentTagWrite(name="Synthetic folder"))
    await document_tags.move_document(scope, items[0].id, folder.id)
    branches = {branch.id: branch for branch in await catalog(scope)}
    assert branches[topics[0].id].keywords == ["common", "retained", "source"]
    assert branches[topics[0].id].document_count == 3
    assert branches[topics[0].id].without_keywords_count == 1
    assert branches[topics[1].id].keywords == ["common", "target"]

    async def ids(**filters):
        result = await documents.browse_document_library(DocumentLibraryRequest(**filters),
            managed_agent_ids=scope.agent_ids, user_id=scope.user_id)
        return {entry.item.id for entry in result.entries}, result.total

    assert await ids(topic_id=topics[0].id) == ({item.id for item in items[:3]}, 3)
    assert await ids(topic_id=topics[0].id, keyword="common") == ({item.id for item in items[:2]}, 2)
    assert await ids(topic_id=topics[1].id, keyword="common") == ({items[3].id}, 1)
    assert await ids(topic_id=topics[0].id, without_keywords=True) == ({items[2].id}, 1)
    assert await ids(topic_classification="unclassified") == ({items[5].id}, 1)
    assert await ids(topic_id=topics[0].id, offset=500) == (set(), 3)
    # Targeted reconciliation returns only requested, currently readable summaries.
    assert await ids(document_ids=[items[0].id, items[4].id, uuid4()]) == ({items[0].id}, 1)
    assert await ids(document_ids=[]) == (set(), 0)
    assert await ids(document_ids=[items[0].id], topic_id=topics[1].id) == (set(), 0)


@pytest.mark.asyncio
async def test_keyword_merge_and_removal_preserve_documents_and_other_tags(db, agents, memory_storage):
    from app.document.keyword_actions import replace_keywords
    from app.document.schemas import DocumentKeywordChange

    scope, _, items = await setup_library(db, agents)
    before = [(item.revision, item.content, item.topic_id) for item in items[:2]]
    await replace_keywords(DocumentKeywordChange(documents=[{"id": item.id, "expected_lock_version": item.lock_version} for item in items[:2]],
        source_keywords=["common", "source"], keyword="retained"), scope)
    assert [item.keywords for item in items[:2]] == [["retained"], ["retained"]]
    assert [(item.revision, item.content, item.topic_id) for item in items[:2]] == before
    await replace_keywords(DocumentKeywordChange(documents=[{"id": item.id, "expected_lock_version": item.lock_version} for item in items[:2]],
        source_keywords=["retained"], keyword=None), scope)
    assert [item.keywords for item in items[:2]] == [[], []]
    assert [(item.revision, item.content, item.topic_id) for item in items[:2]] == before


@pytest.mark.asyncio
async def test_agent_keyword_move_rejects_a_stale_version_without_partial_changes(db, agents, memory_storage):
    from pydantic import ValidationError
    from app.document.schemas import DocumentOwnerUpdate
    from app.document.resource_service import DocumentConflictError

    _, _, items = await setup_library(db, agents)
    item, owner, peer = items[0], agents[0], agents[1]
    version, keywords = item.lock_version, list(item.keywords)
    with pytest.raises(ValidationError):
        DocumentOwnerUpdate(kind="agent", id=peer.id, expected_revision=item.revision, keywords=["replacement"])
    with pytest.raises(DocumentConflictError):
        await documents.transfer_document_owner(item.id, DocumentOwnerUpdate(kind="agent", id=peer.id,
            expected_revision=item.revision, expected_lock_version=version + 1, keywords=["replacement"]), actor_agent_id=owner.id)
    assert item.owner_agent_id == owner.id
    assert item.keywords == keywords and item.lock_version == version


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["version", "readonly", "denied"])
async def test_keyword_batch_refusal_preserves_every_document(db, agents, memory_storage, failure):
    from app.document.keyword_actions import replace_keywords
    from app.document.schemas import DocumentKeywordChange
    from app.document.resource_service import DocumentConflictError, DocumentNotFoundError, DocumentPermissionError

    scope, _, items = await setup_library(db, agents)
    selected = [items[0], items[4] if failure == "denied" else items[1]]
    if failure == "readonly":
        selected[1].read_only = True
    await db.commit()
    before = [(item.id, list(item.keywords), item.lock_version) for item in selected]
    request = DocumentKeywordChange(documents=[{"id": item.id, "expected_lock_version": item.lock_version + int(failure == "version" and index == 1)}
        for index, item in enumerate(selected)], source_keywords=["common"], keyword="replacement")
    with pytest.raises((DocumentConflictError, DocumentNotFoundError, DocumentPermissionError)):
        await replace_keywords(request, scope)
    assert [(item.id, item.keywords, item.lock_version) for item in selected] == before


@pytest.mark.asyncio
async def test_agent_catalog_and_branches_preserve_document_access_and_human_ownership(db, agents, memory_storage):
    from app.document.agent_library import catalog as agent_catalog

    scope, topics, items = await setup_library(db, agents)
    owner, peer = agents
    owner.avatar = b"synthetic-avatar-bytes"
    await db.flush()
    human_item, _ = await documents.create_item(DocumentItemCreate(title="Synthetic human-owned document",
        keywords=["human-only"], payload=DocumentPayload(text="<p>Synthetic personal content</p>")), owner_user_id=scope.user_id)
    branches = await agent_catalog(scope)
    assert [branch.id for branch in branches] == [owner.id]
    assert branches[0].document_count == 5
    assert branches[0].without_keywords_count == 1
    assert branches[0].keywords == ["common", "inbox", "retained", "source", "target"]
    assert branches[0].title.strip()
    assert branches[0].has_avatar is True
    page = await documents.browse_document_library(DocumentLibraryRequest(owner_kind="agent", owner=owner.id, keyword="common"),
        managed_agent_ids=scope.agent_ids, user_id=scope.user_id)
    assert {entry.item.id for entry in page.entries} == {items[0].id, items[1].id, items[3].id}
    page = await documents.browse_document_library(DocumentLibraryRequest(agent_classification="unclassified"),
        managed_agent_ids=scope.agent_ids, user_id=scope.user_id)
    assert [entry.item.id for entry in page.entries] == [human_item.id]
    page = await documents.browse_document_library(DocumentLibraryRequest(owner_kind="agent", owner=owner.id, without_keywords=True),
        managed_agent_ids=scope.agent_ids, user_id=scope.user_id)
    assert [entry.item.id for entry in page.entries] == [items[2].id]
    await documents.set_item_grant(items[4].id, owner.id, DocumentGrantUpdate(can_write=False), actor_agent_id=peer.id)
    branches = {branch.id: branch for branch in await agent_catalog(scope)}
    assert branches[peer.id].keywords == ["private-tag"]
    assert branches[peer.id].has_avatar is False
    await documents.remove_item_grant(items[4].id, owner.id, actor_agent_id=peer.id)
    assert [branch.id for branch in await agent_catalog(scope)] == [owner.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_target", [None, "target", "TARGET"])
async def test_move_replaces_source_tag_preserves_other_tags_content_and_manual_folder(db, agents, memory_storage, existing_target):
    scope, topics, items = await setup_library(db, agents)
    item = items[0]
    if existing_target:
        item.keywords = [*item.keywords, existing_target]
        await db.commit()
    folder = await document_tags.write_tag(scope.user_id, DocumentTagWrite(name="Synthetic folder"))
    await document_tags.move_document(scope, item.id, folder.id)
    before = (item.revision, item.content_hash, item.lock_version)
    await move(item.id, DocumentTopicMove(topic_id=topics[1].id, expected_topic_id=topics[0].id,
        expected_lock_version=item.lock_version, source_keyword="source", keyword="target"), scope)
    await db.refresh(item)
    assert item.topic_id == topics[1].id and item.keywords == ["common", "retained", "target"]
    assert (item.revision, item.content_hash) == before[:2]
    assert item.lock_version > before[2]
    assert item.metadata_["topic_assignment"] == {"origin": "manual", "topic_id": str(topics[1].id)}
    page = await documents.browse_document_library(DocumentLibraryRequest(tag_id=folder.id),
        managed_agent_ids=scope.agent_ids, user_id=scope.user_id)
    assert [entry.item.id for entry in page.entries] == [item.id]
    await move(item.id, DocumentTopicMove(topic_id=None, expected_topic_id=topics[1].id,
        expected_lock_version=item.lock_version), scope)
    await db.refresh(item)
    assert item.topic_id is None and item.keywords == ["common", "retained", "target"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["version", "topic", "permission", "missing", "limit"])
async def test_failed_move_never_changes_either_topic_or_tags(db, agents, memory_storage, failure):
    scope, topics, items = await setup_library(db, agents)
    item = items[4] if failure == "permission" else items[0]
    if failure == "limit":
        item.keywords = [f"synthetic-{i}" for i in range(50)]
        await db.commit()
    before = (item.topic_id, list(item.keywords), item.lock_version)
    data = DocumentTopicMove(topic_id=uuid4() if failure == "missing" else topics[1].id,
        expected_topic_id=topics[1].id if failure == "topic" else item.topic_id,
        expected_lock_version=item.lock_version - 1 if failure == "version" else item.lock_version,
        source_keyword=None if failure == "limit" else "source", keyword="new-tag")
    from app.topic.service import TopicNotFoundError
    with pytest.raises((documents.DocumentConflictError, documents.DocumentPermissionError, documents.DocumentNotFoundError, TopicNotFoundError)):
        await move(item.id, data, scope)
    identity = item.id
    await db.rollback()
    restored = await db.get(Document, identity)
    assert (restored.topic_id, restored.keywords, restored.lock_version) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("rights, status", [
    (["DOCUMENT_ACCESS"], 403),
    (["DOCUMENT_EDIT"], 403),
    (["TOPIC_EDIT"], 403),
    (["DOCUMENT_EDIT", "TOPIC_EDIT"], 204),
])
@pytest.mark.parametrize("batch", [False, True])
async def test_classification_http_requires_both_topic_and_document_editing(client, memory_storage, rights, status, batch):
    from sqlalchemy import select
    from core.authorize.models import Assignment, Privilege, Role
    from core.database import get_db_session
    from core.user.auth_service import create_access_token

    async with get_db_session() as db:
        user = UserModel(email=f"synthetic-topic-http-{uuid4()}@example.test", hashed_password="unused", is_active=True)
        role = Role(code=f"synthetic-topic-{uuid4().hex}", privileges=list(await db.scalars(select(Privilege).where(Privilege.code.in_(rights)))))
        topic = Topic(title="Synthetic HTTP topic", description="", keywords=[])
        db.add_all([user, role, topic])
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id))
        item, _ = await documents.create_item(DocumentItemCreate(title="Synthetic HTTP document", keywords=["before"],
            payload=DocumentPayload(text="<p>Synthetic body</p>")), owner_user_id=user.id)
        headers = {"Authorization": f"Bearer {create_access_token({'sub': user.email, 'user_id': user.id, 'role_id': role.id})}"}
        identity, version, topic_id = item.id, item.lock_version, topic.id
    command = {
        "topic_id": str(topic_id), "expected_topic_id": None, "expected_lock_version": version,
        "source_keyword": "before", "keyword": "after",
    }
    response = await client.post("/api/topics/documents/classification-batch", headers=headers,
        json={"documents": [{"id": str(identity), **command}]}) if batch else await client.put(
        f"/api/topics/documents/{identity}/classification", headers=headers, json=command)
    assert response.status_code == status, response.text
    async with get_db_session() as db:
        item = await db.get(Document, identity)
        assert item.topic_id == (topic_id if status == 204 else None)
        assert item.keywords == (["after"] if status == 204 else ["before"])
        version = item.lock_version
    keyword_request = {"documents": [{"id": str(identity), "expected_lock_version": version}],
        "source_keywords": ["after" if status == 204 else "before"], "keyword": "renamed"}
    response = await client.post("/api/documents/library/keywords", headers=headers, json=keyword_request)
    assert response.status_code == (204 if "DOCUMENT_EDIT" in rights else 403), response.text
    response = await client.post("/api/documents/library/keywords", json=keyword_request)
    assert response.status_code == 401
    if "DOCUMENT_EDIT" in rights:
        response = await client.post("/api/documents/library", headers=headers,
            json={"document_ids": [str(identity), str(uuid4())], "include_keywords": False})
        assert response.status_code == 200, response.text
        assert [row["item"]["id"] for row in response.json()["entries"]] == [str(identity)]
    if "DOCUMENT_ACCESS" in rights or "DOCUMENT_EDIT" in rights:
        response = await client.get("/api/topics/document-library", headers=headers)
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()] == ([str(topic_id)] if status == 204 else [])
        response = await client.get("/api/documents/library/agents", headers=headers)
        assert response.status_code == 200 and response.json() == []
