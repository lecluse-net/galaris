"""Observable coverage, relation recall and attachment enrichment contracts (#168)."""

from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select

from app.memory import document_attachment_service as attachments, service, retrieval
from app.memory.attachment_description import record_attachment_description
from app.memory.document_structure import reconcile_document_structure, document_references
from app.memory.models import DocumentAttachment, MemoryAutomationJob, MemoryItem, MemoryLink
from app.memory.schemas import MemoryGraphRootsRequest, MemoryGrantUpdate, MemoryItemCreate, MemoryItemUpdate, MemoryPayload, MemoryRecallRequest


async def document(agent, title, content="<p>Content</p>"):
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=agent.id, title=title, node_kind="document", memory_type="working",
        media_type="text/html", payload=MemoryPayload(text=content),
    ))
    return item


def png():
    output = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_attachment_companion_preserves_description_across_reconciliation_and_live_revocation(db, agents, memory_storage):
    owner, reader = agents
    source = await document(owner, "Album")
    attachment = await attachments.add_document_attachment_bytes(
        source.id, actor_agent_id=owner.id, name="landscape.png", media_type="image/png", content=png(),
    )
    row = await db.get(DocumentAttachment, attachment.id)
    assert row is not None
    companion_id = row.memory_item_id
    before = (await service.get_item(companion_id, agent_id=owner.id))[1]
    assert before == b""
    await service.set_item_grant(source.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    uri = f"document://{source.id}/attachments/{attachment.id}"
    assert await record_attachment_description(uri, "Une montagne bleue.", agent_id=reader.id) == companion_id
    assert await db.scalar(select(MemoryAutomationJob.id).where(
        MemoryAutomationJob.kind == "semantic_index",
        MemoryAutomationJob.payload["item_id"].as_string() == str(companion_id),
    )) is not None
    await db.commit()
    described = await service.get_item(companion_id, agent_id=reader.id)
    revision = described[0].revision
    assert "montagne" in described[1].decode()
    assert described[0].node_kind == "attachment"
    for _ in range(3):
        await reconcile_document_structure()
        await db.commit()
    after = await service.get_item(companion_id, agent_id=reader.id)
    assert after[1] == described[1]
    assert after[0].revision == revision
    assert list(await db.scalars(select(DocumentAttachment.memory_item_id).where(DocumentAttachment.id == attachment.id))) == [companion_id]
    await service.remove_item_grant(source.id, reader.id, actor_agent_id=owner.id)
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(companion_id, agent_id=reader.id)
    with pytest.raises(service.MemoryPermissionError):
        await record_attachment_description(uri, "Must not be stored", agent_id=reader.id)
    assert (await service.get_item(companion_id, agent_id=owner.id))[1] == described[1]
    await attachments.delete_document_attachment(source.id, attachment.id, actor_agent_id=owner.id)
    await reconcile_document_structure()
    await db.commit()
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(companion_id, agent_id=owner.id)
    assert (await db.get(DocumentAttachment, attachment.id)).memory_item_id == companion_id
    graph = await service.list_graph_roots(MemoryGraphRootsRequest(agent_id=owner.id))
    assert companion_id not in {node.id for node in graph.nodes}


@pytest.mark.asyncio
async def test_structural_links_are_idempotent_without_admitting_unrelated_search_results(db, agents, memory_storage):
    owner, reader = agents
    target = await document(owner, "Unrelated appendix", "<p>Different words entirely.</p>")
    anchor = await document(owner, "Kestrel dossier", f'<p><a href="document://{target.id}">Annexe</a></p>')
    isolated = await document(owner, "Isolated")
    link = await db.scalar(select(MemoryLink).where(MemoryLink.source_item_id == anchor.id, MemoryLink.target_item_id == target.id))
    assert link is not None
    identity = link.id
    for _ in range(3):
        await reconcile_document_structure()
        await db.commit()
    links = list(await db.scalars(select(MemoryLink).where(MemoryLink.source_item_id == anchor.id, MemoryLink.target_item_id == target.id)))
    assert [link.id for link in links] == [identity]
    assert links[0].confidence == 1
    result = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query="Kestrel"))
    # A durable explicit link remains navigable, but is not evidence for Kestrel.
    assert target.id not in {hit.item.id for hit in result.hits}
    assert isolated.id not in {hit.item.id for hit in result.hits}
    await service.set_item_grant(anchor.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    result = await retrieval.recall_items(MemoryRecallRequest(agent_id=reader.id, query="Kestrel"))
    assert {hit.item.id for hit in result.hits} == {anchor.id}
    await service.update_item(anchor.id, MemoryItemUpdate(expected_revision=anchor.revision, payload=MemoryPayload(text="<p>No reference</p>")), actor_agent_id=owner.id)
    result = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query="Kestrel"))
    assert target.id not in {hit.item.id for hit in result.hits}


def test_explicit_reference_normalization_does_not_invent_documents():
    from uuid import uuid4
    doc, attachment = uuid4(), uuid4()
    assert document_references(
        f'<a href="document://{doc}">One</a><a href="/memory/documents?document_id={doc}">Two</a>'
        f'<img src="document://{doc}/attachments/{attachment}"><p>document://{uuid4()}</p>'
        '<a href="https://outside.example/memory/documents?document_id=bad">External</a>'
    ) == {(doc, None), (doc, attachment)}


@pytest.mark.asyncio
async def test_image_read_saves_real_attachment_description_and_never_reports_success_when_storage_fails(db, agents, memory_storage, monkeypatch):
    from unittest.mock import AsyncMock
    from app.image import mcp as image_mcp
    from app.tools import RecoverableToolError
    from app.tools.mcp_loader import McpToolContext
    from app.memory.storage import get_storage

    owner, _ = agents
    source = await document(owner, "Gallery")
    attachment = await attachments.add_document_attachment_bytes(source.id, actor_agent_id=owner.id,
        name="sample.png", media_type="image/png", content=png())
    uri = f"document://{source.id}/attachments/{attachment.id}"
    monkeypatch.setattr(image_mcp, "_context_language", AsyncMock(return_value="fr"))
    vision = AsyncMock(return_value="Une forme bleue.")
    monkeypatch.setattr(image_mcp.image_service, "describe_image", vision)
    ctx = McpToolContext(agent_id=owner.id, runtime="internal")
    assert await image_mcp.describe_image(ctx, uri) == "Une forme bleue."
    row = await db.get(DocumentAttachment, attachment.id)
    content = (await service.get_item(row.memory_item_id, agent_id=owner.id))[1]
    assert "forme bleue" in content.decode()
    vision.return_value = "Another description"
    monkeypatch.setattr(get_storage("native"), "create", AsyncMock(side_effect=OSError("Storage unavailable")))
    with pytest.raises(RecoverableToolError):
        await image_mcp.describe_image(ctx, uri)
    assert (await service.get_item(row.memory_item_id, agent_id=owner.id))[1] == content


@pytest.mark.asyncio
async def test_external_image_description_is_private_stable_and_mandatory(db, agents, memory_storage):
    owner, reader = agents
    uri = "nextcloud://Photos/photo.png"
    identity = await record_attachment_description(uri, "A first description", agent_id=owner.id)
    assert await record_attachment_description(uri, "An updated description", agent_id=owner.id) == identity
    assert "updated" in (await service.get_item(identity, agent_id=owner.id))[1].decode()
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(identity, agent_id=reader.id)
    assert await record_attachment_description(uri, "Their own observation", agent_id=reader.id) != identity


@pytest.mark.asyncio
async def test_folder_visibility_derives_recursively_from_documents_without_sharing(db, agents, memory_storage):
    from uuid import uuid4
    from app.agent import AgentManagementScope
    from app.memory import document_tags, item_sharing
    from app.memory.schemas import DocumentTagWrite
    from core.user import UserModel

    owner, reader = agents
    human = UserModel(email=f"structure-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(human)
    await db.flush()
    scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
    root = await document_tags.write_tag(human.id, DocumentTagWrite(name="ZephyrRoot"))
    child = await document_tags.write_tag(human.id, DocumentTagWrite(name="Child", parent_id=root.id))
    other = await document_tags.write_tag(human.id, DocumentTagWrite(name="Other"))
    source = await document(owner, "Remote appendix")
    secret = await document(owner, "Secret member")
    await document_tags.assign_tag(scope, source.id, child.id)
    await document_tags.assign_tag(scope, secret.id, child.id)
    await service.set_item_grant(source.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    assert not (await item_sharing.sharing(root.memory_item_id, scope)).can_manage
    hits = await retrieval.recall_items(MemoryRecallRequest(agent_id=reader.id, query="ZephyrRoot", limit=20))
    # Folder ACL inheritance is preserved; an exact folder search no longer
    # promotes all descendants as relevant answers.
    assert {hit.item.id for hit in hits.hits} == {root.memory_item_id}
    assert (await service.get_item(source.id, agent_id=reader.id))[0].id == source.id
    # Multi-membership preserves identity; only ancestors of readable documents remain.
    await document_tags.assign_tag(scope, source.id, other.id)
    await document_tags.write_tag(human.id, DocumentTagWrite(name="Renamed", parent_id=other.id), child.id)
    assert (await document_tags.require_tag(human.id, child.id)).memory_item_id == child.memory_item_id
    hits = await retrieval.recall_items(MemoryRecallRequest(agent_id=reader.id, query="ZephyrRoot", limit=20))
    assert not hits.hits
    await document_tags.remove_tag(human.id, child.id, confirmed=True)
    assert await service.document_record(source.id) is not None
    assert not list(await db.scalars(select(MemoryLink).where(MemoryLink.target_item_id == child.memory_item_id)))


@pytest.mark.asyncio
async def test_agent_sees_each_personal_tree_but_users_keep_their_own_classification(db, agents, memory_storage):
    from uuid import uuid4
    from app.agent import AgentManagementScope
    from app.memory import document_tags
    from app.memory.access import effective_access, human_item_access
    from app.memory.schemas import DocumentTagWrite
    from core.user import UserModel

    owner, reader = agents
    source = await document(owner, "Shared across trees")
    private = await document(owner, "Hidden sibling")
    await service.set_item_grant(source.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    trees = []
    for _ in range(3):
        human = UserModel(email=f"tree-{uuid4()}@example.test", hashed_password="unused", is_active=True)
        db.add(human)
        await db.flush()
        scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
        root = await document_tags.write_tag(human.id, DocumentTagWrite(name="Root"))
        child = await document_tags.write_tag(human.id, DocumentTagWrite(name="Child", parent_id=root.id))
        hidden = await document_tags.write_tag(human.id, DocumentTagWrite(name="Private sibling", parent_id=root.id))
        await document_tags.assign_tag(scope, source.id, child.id)
        await document_tags.assign_tag(scope, private.id, hidden.id)
        trees.append((human, root, child, hidden))
    for human, root, child, hidden in trees:
        assert {folder.id for folder in await document_tags.list_tags(human.id)} == {root.id, child.id, hidden.id}
        assert (await effective_access(await service.item_record(root.memory_item_id), reader.id)).can_read
        assert not (await effective_access(await service.item_record(hidden.memory_item_id), reader.id)).can_read
        other = next(user for user, *_ in trees if user.id != human.id)
        assert not (await human_item_access(await service.item_record(root.memory_item_id), other.id)).can_read
    graph = await service.list_graph_roots(MemoryGraphRootsRequest(agent_id=reader.id))
    assert {node.id for node in graph.nodes} == {source.id, *(folder.memory_item_id for _, root, child, _ in trees for folder in (root, child))}
    await service.remove_item_grant(source.id, reader.id, actor_agent_id=owner.id)
    assert not (await service.list_graph_roots(MemoryGraphRootsRequest(agent_id=reader.id))).nodes


@pytest.mark.asyncio
async def test_hidden_intermediate_never_changes_visible_recall_or_graph_counts(db, agents, memory_storage):
    owner, reader = agents
    anchor = await document(owner, "ObsidianAnchor")
    destination = await document(owner, "Faraway")
    for item in (anchor, destination):
        await service.set_item_grant(item.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    request = MemoryRecallRequest(agent_id=reader.id, query="ObsidianAnchor")
    before = await retrieval.recall_items(request)
    hidden = await document(owner, "Hidden bridge", f'<a href="document://{destination.id}">Continue</a>')
    await service.update_item(anchor.id, MemoryItemUpdate(expected_revision=anchor.revision,
        payload=MemoryPayload(text=f'<a href="document://{hidden.id}">Continue</a>')), actor_agent_id=owner.id)
    after = await retrieval.recall_items(request)
    assert [hit.item.id for hit in before.hits] == [hit.item.id for hit in after.hits] == [anchor.id]
    graph = await service.list_graph_roots(MemoryGraphRootsRequest(agent_id=reader.id))
    assert all(node.relation_count == 0 for node in graph.nodes)
    assert not graph.edges


@pytest.mark.asyncio
async def test_all_attachment_types_and_document_forget_remove_acquired_payloads(db, agents, memory_storage):
    from app.memory.models import MemoryRevision
    owner, _ = agents
    source = await document(owner, "Mixed files")
    files = []
    for name, mime, payload in (("image.png", "image/png", png()), ("audio.ogg", "audio/ogg", b"audio"), ("report.pdf", "application/pdf", b"pdf")):
        files.append(await attachments.add_document_attachment_bytes(source.id, actor_agent_id=owner.id,
            name=name, media_type=mime, content=payload))
    rows = list(await db.scalars(select(DocumentAttachment).where(DocumentAttachment.document_id == source.id)))
    assert len(rows) == 3
    companion_id = await record_attachment_description(f"document://{source.id}/attachments/{files[0].id}",
        "Forget this description too", agent_id=owner.id)
    resource = (await service.item_record(companion_id)).resource_id
    await service.forget_item(source.id, actor_agent_id=owner.id)
    assert await service.item_record(companion_id) is None
    assert not list(await db.scalars(select(MemoryRevision).where(MemoryRevision.item_id == companion_id)))
    assert not (memory_storage / resource).exists()
    await reconcile_document_structure()
    assert await service.item_record(companion_id) is None


@pytest.mark.asyncio
async def test_structure_inventory_and_replay_do_not_call_models_or_overwrite_manual_links(db, agents, memory_storage, monkeypatch):
    from unittest.mock import AsyncMock
    from app.llm import facade as llm
    from app.memory import embedding
    forbidden = AsyncMock(side_effect=AssertionError("Structural synchronization must never call a model"))
    monkeypatch.setattr(llm, "start_inference", forbidden)
    monkeypatch.setattr(llm, "run_text_inference", forbidden)
    monkeypatch.setattr(embedding, "embed_many", forbidden)
    owner, reader = agents
    target = await document(owner, "Appendix")
    anchor = await document(owner, "Root", f'<a href="document://{target.id}">Appendix</a>')
    isolated = await document(owner, "Isolated")
    edge = await db.scalar(select(MemoryLink).where(MemoryLink.source_item_id == anchor.id, MemoryLink.target_item_id == target.id))
    edge.projection_key = None
    edge.projection_version = None
    edge.confidence = 0.82
    await db.commit()
    for item in (target, anchor, isolated):
        await service.set_item_grant(item.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    await service.update_item(anchor.id, MemoryItemUpdate(expected_revision=anchor.revision,
        payload=MemoryPayload(text="<p>Link removed</p>")), actor_agent_id=owner.id)
    for _ in range(3):
        await reconcile_document_structure()
        await db.commit()
    assert edge.deleted_at is None and edge.projection_key is None and edge.confidence == 0.82
    seen = []
    cursor = None
    while True:
        page = await service.list_graph_roots(MemoryGraphRootsRequest(agent_id=reader.id, limit=1, cursor=cursor))
        seen.extend(node.id for node in page.nodes)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert set(seen) == {target.id, anchor.id, isolated.id}
    assert len(seen) == 3
    forbidden.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_repair_and_stale_dream_replay_use_current_source(inference_db, memory_storage):
    import asyncio
    from uuid import uuid4
    from app.agent.models import Agent, Title
    from app.dream.contracts import DreamClaim
    from app.dream.mechanisms.document_structure import document_structure_mechanism
    from app.memory.facade import reconcile_structure_subject
    from core.database import get_db_session

    db = inference_db
    title = Title(label=f"Structure {uuid4()}", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(title_id=title.id, first_name="Concurrent", last_name="Structure",
        code=f"structure-{uuid4().hex[:8]}", agent_driver="internal")
    db.add(owner)
    await db.flush()
    target = await document(owner, "Destination")
    source = await document(owner, "Source", f'<a href="document://{target.id}">Target</a>')
    attachment = await attachments.add_document_attachment_bytes(source.id, actor_agent_id=owner.id,
        name="photo.png", media_type="image/png", content=png())
    uri = f"document://{source.id}/attachments/{attachment.id}"
    source_id, owner_id = source.id, owner.id
    await db.commit()

    async def enrich():
        async with get_db_session():
            return await record_attachment_description(uri, "Concurrent description", agent_id=owner_id)

    identities = await asyncio.gather(enrich(), enrich(), enrich())
    assert len(set(identities)) == 1
    claim = DreamClaim(receipt_id=uuid4(), lease_token=uuid4(), subject_kind="document",
        subject_id=f"document:{source_id}:old", attempts=1, prepared_payload=None)
    prepared = await document_structure_mechanism.prepare(claim)
    await service.update_item(source_id, MemoryItemUpdate(expected_revision=source.revision,
        payload=MemoryPayload(text="<p>No target any more</p>")), actor_agent_id=owner_id)
    await document_structure_mechanism.apply(claim, prepared.payload)

    async def repair():
        async with get_db_session():
            return await reconcile_structure_subject("document", source_id)

    assert await asyncio.gather(repair(), repair()) == [1, 1]
    async with get_db_session() as check:
        assert not list(await check.scalars(select(MemoryLink).where(
            MemoryLink.source_item_id == source_id, MemoryLink.target_item_id == target.id,
        )))
        item, content, *_ = await service.get_item(identities[0], agent_id=owner_id)
        assert item.revision == 2
        assert b"Concurrent description" in content
