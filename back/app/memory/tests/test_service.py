from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from PIL import Image
from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent
from app.conversation import ConversationDocumentMetadata
from app.file_share import resource_service
from app.file_share.resource_contracts import ResourceContext
from app.memory import document_attachment_service, service
from app.memory.conversation_document_adapter import (
    resolve_conversation_document_metadata,
)
from app.memory.contracts import ResourceNotFoundError, SourceMemoryDocument
from app.memory.models import MemoryAssociation, MemoryItem, MemoryRevision, MemoryUsage
from app.memory.schemas import (
    MemoryGrantUpdate,
    MemoryGraphExpandRequest,
    MemoryGraphRootsRequest,
    MemoryItemCreate,
    MemoryItemUpdate,
    ManualMemoryLinkCreate,
    MemoryLinkCreate,
    MemoryPayload,
    MemorySearchRequest,
    MemorySortField,
    MemorySourceCreate,
)
from app.memory.storage import get_storage
from app.topic import TopicClassification, service as topic_service


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize("limit", [10, 20, 50, 100, 500])
def test_search_request_accepts_standard_application_page_sizes(limit: int) -> None:
    assert MemorySearchRequest(agent_id=1, limit=limit).limit == limit


def test_search_request_rejects_page_sizes_above_application_standard() -> None:
    with pytest.raises(ValidationError):
        MemorySearchRequest(agent_id=1, limit=501)


def test_search_request_rejects_unknown_sort_field() -> None:
    with pytest.raises(ValidationError):
        MemorySearchRequest.model_validate({"agent_id": 1, "sort_by": "unknown"})


@pytest.mark.asyncio
async def test_conversation_document_metadata_uses_canonical_memory_title(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    document, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Canonical document title",
            payload=MemoryPayload(text="Document content"),
            memory_type="working",
            node_kind="document",
        )
    )
    metadata = await resolve_conversation_document_metadata((document.id, uuid4()))

    assert metadata == {
        document.id: ConversationDocumentMetadata(
            id=document.id,
            title="Canonical document title",
            revision=document.revision,
            updated_at=document.updated_at,
        )
    }


@pytest.mark.parametrize(
    "relation_type",
    [
        "related_to",
        "supports",
        "contradicts",
        "depends_on",
        "precedes",
        "supersedes",
    ],
)
def test_manual_link_accepts_canonical_relation_types(relation_type: str) -> None:
    link = ManualMemoryLinkCreate(
        source_item_id=uuid4(),
        target_item_id=uuid4(),
        relation_type=relation_type,
    )

    assert link.relation_type == relation_type


def test_manual_link_rejects_free_form_relation_type() -> None:
    with pytest.raises(ValidationError):
        ManualMemoryLinkCreate(
            source_item_id=uuid4(),
            target_item_id=uuid4(),
            relation_type="whatever_the_user_typed",  # type: ignore[arg-type]
        )


def test_graph_requests_enforce_bounded_pages_and_known_nodes() -> None:
    with pytest.raises(ValidationError):
        MemoryGraphRootsRequest(agent_id=1, limit=101)
    with pytest.raises(ValidationError):
        MemoryGraphRootsRequest(
            agent_id=1,
            known_item_ids=[uuid4() for _index in range(501)],
        )
    with pytest.raises(ValidationError):
        MemoryGraphExpandRequest(agent_id=1, item_id=uuid4(), limit=101)
    assert len(
        MemoryGraphExpandRequest(
            agent_id=1,
            item_id=uuid4(),
            known_item_ids=[uuid4() for _index in range(3_000)],
        ).known_item_ids
    ) == 3_000
    with pytest.raises(ValidationError):
        MemoryGraphExpandRequest(
            agent_id=1,
            item_id=uuid4(),
            known_item_ids=[uuid4() for _index in range(3_001)],
        )


@pytest.mark.asyncio
async def test_document_writes_emit_content_free_realtime_events(
    monkeypatch: pytest.MonkeyPatch,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    events: list[tuple[str, str, dict[str, object], object]] = []

    async def emit(
        subject: str,
        action: str,
        data: dict[str, object],
        room: object,
    ) -> None:
        events.append((subject, action, data, room))

    monkeypatch.setattr(service.websocket, "emit", emit)
    document, created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Live document",
            payload=MemoryPayload(text="Initial content"),
            memory_type="working",
            node_kind="document",
        )
    )
    assert created
    await service.update_item(
        document.id,
        MemoryItemUpdate(
            expected_revision=document.revision,
            payload=MemoryPayload(text="Updated content"),
        ),
        actor_agent_id=owner.id,
    )
    await service.set_item_grant(
        document.id,
        peer.id,
        MemoryGrantUpdate(can_write=False),
        actor_agent_id=owner.id,
    )
    await service.forget_item(document.id, actor_agent_id=owner.id)

    assert [event[:2] for event in events] == [
        ("memory", "create"),
        ("memory", "update"),
        ("memory", "update"),
        ("memory", "delete"),
        ("memory", "invalidate"),
    ]
    assert all(event[3] is None for event in events)
    assert all(
        set(event[2])
        == {"id", "owner_agent_id", "owner_user_id", "node_kind", "revision", "lock_version", "media_type", "content_profile", "content_profile_version"}
        for event in events if event[1] != "invalidate"
    )
    assert all(event[2] == {} for event in events if event[1] == "invalidate")
    assert all(event[2]["id"] == str(document.id) for event in events if event[1] != "invalidate")


@pytest.mark.asyncio
async def test_retention_preview_counts_without_mutating_memories(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    inactive, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Ancienne note",
            payload=MemoryPayload(text="Souvenir inactif à prévisualiser."),
            memory_type="episodic",
        )
    )
    expired, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Note expirée",
            payload=MemoryPayload(text="Souvenir arrivé à échéance."),
            memory_type="semantic",
            valid_until=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    document, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Document de travail",
            payload=MemoryPayload(text="Notes de travail à conserver."),
            memory_type="working",
            node_kind="document",
        )
    )
    old = datetime.now(timezone.utc) - timedelta(days=400)
    await db.execute(
        update(MemoryItem)
        .where(MemoryItem.id.in_([inactive.id, document.id]))
        .values(created_at=old, updated_at=old, last_accessed_at=None)
    )
    await db.commit()

    preview = await service.preview_retention(365)

    assert preview.inactivity_enabled
    assert preview.inactive_count == 1
    assert preview.expired_count == 1
    assert preview.total_candidates == 2
    assert preview.by_memory_type == {"episodic": 1, "semantic": 1}
    assert preview.oldest_activity_at is not None
    assert await db.get(MemoryItem, inactive.id) is not None
    assert await db.get(MemoryItem, expired.id) is not None
    assert await db.get(MemoryItem, document.id) is not None

    assert (
        await service.forget_stale_item(
            document.id,
            expected_activity_at=document.activity_at,
            forget_after_days=365,
        )
        is None
    )

    expiry_only = await service.preview_retention(0)
    assert not expiry_only.inactivity_enabled
    assert expiry_only.inactive_count == 0
    assert expiry_only.expired_count == 1
    assert expiry_only.total_candidates == 1


@pytest.mark.asyncio
async def test_acl_search_revisions_links_and_physical_forget(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    owner, peer = agents
    item, created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="PostgreSQL deployment rule",
            payload=MemoryPayload(text="Always apply Atlas before deploying PostgreSQL."),
            memory_type="procedural",
            keywords=["postgresql", "atlas", "atlas"],
            source=MemorySourceCreate(
                source_kind="test",
                source_ref="test:procedure:1",
                excerpt="Atlas before deployment",
            ),
        )
    )
    assert created
    assert item.revision == 1
    assert item.keywords == ["postgresql", "atlas"]
    initial_resource_id = item.resource_id

    owner_page = await service.search_items(
        MemorySearchRequest(agent_id=owner.id, query="PostgreSQL Atlas")
    )
    assert [hit.item.id for hit in owner_page.hits] == [item.id]
    assert owner_page.total == 1
    assert owner_page.hits[0].source_refs == ["test:procedure:1"]

    peer_page = await service.search_items(
        MemorySearchRequest(agent_id=peer.id, query="PostgreSQL Atlas")
    )
    assert peer_page.hits == []
    assert peer_page.total == 0

    await service.set_item_grant(item.id, peer.id, MemoryGrantUpdate(can_write=False))
    peer_item, content, access, _content_type, _media_type = await service.get_item(
        item.id, agent_id=peer.id
    )
    assert peer_item.id == item.id
    assert content.startswith(b"<p>Always apply Atlas")
    assert access.can_read and not access.can_write
    public_item = service.item_to_public(peer_item, access)
    assert [(grant.agent_id, grant.can_write) for grant in public_item.grants] == [
        (peer.id, False)
    ]
    with pytest.raises(service.MemoryPermissionError):
        await service.update_item(
            item.id,
            MemoryItemUpdate(title="Unauthorized"),
            actor_agent_id=peer.id,
        )

    await service.set_item_grant(item.id, peer.id, MemoryGrantUpdate(can_write=True))
    updated = await service.update_item(
        item.id,
        MemoryItemUpdate(
            payload=MemoryPayload(text="Apply Atlas, then verify the generated schema."),
        ),
        actor_agent_id=peer.id,
    )
    updated_resource_id = updated.resource_id
    assert updated.revision == 4  # two ACL revisions plus the content revision
    revisions = await service.list_revisions(
        item.id, agent_id=owner.id
    )
    assert [revision.revision for revision in revisions] == [1, 2, 3, 4]
    assert all("reason" not in revision.model_dump() for revision in revisions)
    _old_item, old_content, _access, _content_type, _media_type = await service.get_item(
        item.id,
        agent_id=owner.id,
        revision=1,
    )
    assert old_content == b"<p>Always apply Atlas before deploying PostgreSQL.</p>"

    related, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Schema verification",
            payload=MemoryPayload(text="Run the architecture and schema checks."),
        )
    )
    link = await service.create_link(
        MemoryLinkCreate(
            source_item_id=item.id,
            target_item_id=related.id,
            relation_type="depends_on",
        ),
        actor_agent_id=owner.id,
    )
    assert (await service.list_links(item.id, actor_agent_id=owner.id))[0].id == link.id

    result = await service.forget_item(item.id, actor_agent_id=owner.id)
    assert result.resources_deleted == 2
    with pytest.raises(service.MemoryNotFoundError):
        await service.get_item(item.id, agent_id=owner.id)
    provider = get_storage()
    with pytest.raises(ResourceNotFoundError):
        await provider.read(initial_resource_id)
    with pytest.raises(ResourceNotFoundError):
        await provider.read(updated_resource_id)
    assert await db.scalar(
        select(MemoryRevision.id).where(MemoryRevision.item_id == item.id)
    ) is None
    tombstone = await db.scalar(
        select(MemoryItem)
        .where(MemoryItem.id == item.id)
        .execution_options(include_historized=True)
    )
    assert tombstone is not None
    assert tombstone.title == "Forgotten memory"
    assert tombstone.size_bytes == 0


@pytest.mark.asyncio
async def test_direct_grants_and_public_visibility_apply_before_ranking(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Shared incident record",
            payload=MemoryPayload(text="The service recovered after queue drainage."),
        )
    )
    private_page = await service.search_items(
        MemorySearchRequest(agent_id=peer.id, query="queue drainage")
    )
    assert private_page.hits == []
    with pytest.raises(service.MemoryConflictError, match="owner already"):
        await service.set_item_grant(
            item.id, owner.id, MemoryGrantUpdate(can_write=False)
        )

    await service.set_item_grant(
        item.id, peer.id, MemoryGrantUpdate(can_write=False)
    )
    page = await service.search_items(
        MemorySearchRequest(agent_id=peer.id, query="queue drainage")
    )
    assert [hit.item.id for hit in page.hits] == [item.id]
    assert not page.hits[0].item.access.can_write

    private_again = await service.remove_item_grant(item.id, peer.id)
    assert private_again.visibility == "private"
    removed_page = await service.search_items(
        MemorySearchRequest(agent_id=peer.id, query="queue drainage")
    )
    assert removed_page.hits == []

    public_item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Public convention",
            payload=MemoryPayload(text="Use ISO timestamps everywhere."),
            visibility="public",
        )
    )
    public_page = await service.search_items(
        MemorySearchRequest(agent_id=peer.id, query="ISO timestamps")
    )
    assert [hit.item.id for hit in public_page.hits] == [public_item.id]


@pytest.mark.asyncio
async def test_direct_durable_write_rejects_credentials(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    owner, _peer = agents
    with pytest.raises(ValueError, match="credential-like"):
        await service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title="Unsafe note",
                payload=MemoryPayload(text="production password=hunter2"),
            )
        )
    assert not list(memory_storage.rglob("*"))

    with pytest.raises(ValueError, match="metadata contains credential-like"):
        await service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title="Unsafe metadata",
                payload=MemoryPayload(text="Safe visible content"),
                metadata={"api_key": "must-not-persist"},
            )
        )


@pytest.mark.asyncio
async def test_owner_can_forget_a_read_only_memory(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Locked but forgettable",
            payload=MemoryPayload(text="The owner may erase this immutable note."),
            read_only=True,
        )
    )
    with pytest.raises(service.MemoryPermissionError):
        await service.update_item(
            item.id,
            MemoryItemUpdate(title="Must remain immutable"),
            actor_agent_id=owner.id,
        )
    forgotten = await service.forget_item(item.id, actor_agent_id=owner.id)
    assert forgotten.memory_id == item.id


@pytest.mark.asyncio
async def test_deletion_protection_is_distinct_from_read_only(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Protected working document",
            payload=MemoryPayload(text="Editable content"),
            memory_type="working",
            node_kind="document",
        ),
        deletion_protected=True,
    )
    updated = await service.update_item(
        item.id,
        MemoryItemUpdate(payload=MemoryPayload(text="Still editable")),
        actor_agent_id=owner.id,
    )
    assert updated.deletion_protected is True
    with pytest.raises(service.MemoryPermissionError, match="cannot be forgotten"):
        await service.forget_item(item.id, actor_agent_id=owner.id)
    with pytest.raises(service.MemoryPermissionError, match="cannot be forgotten"):
        await service.forget_item(
            item.id, actor_agent_id=None, administrative=True
        )


@pytest.mark.asyncio
async def test_update_rejects_a_stale_revision(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    item, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Concurrent note",
            payload=MemoryPayload(text="Initial value"),
        )
    )
    updated = await service.update_item(
        item.id,
        MemoryItemUpdate(expected_revision=1, title="First editor"),
        actor_agent_id=owner.id,
    )
    assert updated.revision == 2
    with pytest.raises(service.MemoryConflictError, match="expected 1, current revision is 2"):
        await service.update_item(
            item.id,
            MemoryItemUpdate(expected_revision=1, title="Stale editor"),
            actor_agent_id=owner.id,
        )


@pytest.mark.asyncio
async def test_full_text_ranking_prefers_title_then_keywords_then_content(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    title_item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Déploiement contrôlé",
            payload=MemoryPayload(text="Une note de référence sans répétition."),
        )
    )
    keyword_item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Liste opérationnelle",
            payload=MemoryPayload(text="Une autre note de référence."),
            keywords=["déploiement"],
        )
    )
    content_item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Compte rendu",
            payload=MemoryPayload(text="Le déploiement a été vérifié."),
        )
    )

    page = await service.search_items(
        MemorySearchRequest(agent_id=owner.id, query="déploiement")
    )

    assert [hit.item.id for hit in page.hits] == [
        title_item.id,
        keyword_item.id,
        content_item.id,
    ]
    assert page.hits[0].score > page.hits[1].score > page.hits[2].score


@pytest.mark.asyncio
async def test_search_reports_total_and_pages_without_loading_every_item(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    created_ids = set()
    for index in range(3):
        item, _created = await service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title=f"Pagination note {index}",
                payload=MemoryPayload(text="Pagination marker shared by every note."),
            ),
            deduplicate=False,
        )
        created_ids.add(item.id)

    first_page = await service.search_items(
        MemorySearchRequest(
            agent_id=owner.id,
            query="Pagination marker",
            limit=2,
            offset=0,
        )
    )
    second_page = await service.search_items(
        MemorySearchRequest(
            agent_id=owner.id,
            query="Pagination marker",
            limit=2,
            offset=2,
        )
    )

    assert first_page.total == second_page.total == 3
    assert len(first_page.hits) == 2
    assert first_page.has_more
    assert len(second_page.hits) == 1
    assert not second_page.has_more
    assert {
        hit.item.id for hit in [*first_page.hits, *second_page.hits]
    } == created_ids


@pytest.mark.asyncio
async def test_search_filters_documents_before_counting_and_pagination(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    document, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Release document",
            payload=MemoryPayload(text="# Release\n\nCurrent draft."),
            memory_type="working",
            node_kind="document",
            keywords=["release", "draft"],
        )
    )
    await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Release memory",
            payload=MemoryPayload(text="A durable release fact."),
            keywords=["release"],
        )
    )
    await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Archived document",
            payload=MemoryPayload(text="An older working document."),
            memory_type="working",
            node_kind="document",
            keywords=["archive"],
        )
    )

    page = await service.search_items(
        MemorySearchRequest(
            agent_id=owner.id,
            query="Release",
            node_kinds=["document"],
            limit=50,
        )
    )

    assert page.total == 1
    assert not page.has_more
    assert [hit.item.id for hit in page.hits] == [document.id]

    keyword_page = await service.search_items(
        MemorySearchRequest(
            agent_id=owner.id,
            node_kinds=["document"],
            keyword="draft",
            limit=50,
        )
    )
    assert keyword_page.total == 1
    assert [hit.item.id for hit in keyword_page.hits] == [document.id]
    assert await service.list_document_keywords(owner.id) == [
        "archive",
        "draft",
        "release",
    ]
    assert await service.list_document_keywords(_peer.id) == []


@pytest.mark.asyncio
async def test_document_folders_only_include_readable_documents(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Nested document",
            payload=MemoryPayload(text="content"),
            memory_type="working",
            node_kind="document",
            metadata={"document_path": "Projects/Launch"},
        )
    )

    assert await service.list_document_folders(owner.id) == ["Projects/Launch"]
    assert await service.list_document_folders(peer.id) == []


@pytest.mark.asyncio
async def test_document_attachments_follow_document_acl_without_content_revision(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    document, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Document with attachment",
            payload=MemoryPayload(text="content"),
            memory_type="working",
            node_kind="document",
        )
    )
    initial_revision = document.revision
    await service.set_item_grant(
        document.id,
        peer.id,
        MemoryGrantUpdate(can_write=False),
        actor_agent_id=owner.id,
    )
    attachment = await document_attachment_service.add_document_attachment(
        document.id,
        actor_agent_id=owner.id,
        upload=UploadFile(
            file=BytesIO(_png_bytes()),
            filename="preview.png",
            headers={"content-type": "image/png"},
        ),
    )

    visible = await document_attachment_service.list_document_attachments(
        document.id,
        actor_agent_id=peer.id,
    )
    assert visible == [attachment]
    metadata, content = await document_attachment_service.read_document_attachment(
        document.id,
        attachment.id,
        actor_agent_id=peer.id,
    )
    assert metadata.name == "preview.png"
    assert metadata.media_type == "image/png"
    assert content == _png_bytes()

    current, _content, _access, _content_type, _media_type = await service.get_item(
        document.id,
        agent_id=owner.id,
    )
    assert current.revision == initial_revision
    await service.update_item(
        document.id,
        MemoryItemUpdate(
            expected_revision=current.revision,
            metadata={"document_path": "Projects"},
        ),
        actor_agent_id=owner.id,
    )
    current_after_metadata, _content, _access, _content_type, _media_type = (
        await service.get_item(document.id, agent_id=owner.id)
    )
    assert current_after_metadata.revision == initial_revision
    assert await document_attachment_service.list_document_attachments(
        document.id,
        actor_agent_id=owner.id,
    ) == [attachment]

    with pytest.raises(service.MemoryPermissionError):
        await document_attachment_service.delete_document_attachment(
            document.id,
            attachment.id,
            actor_agent_id=peer.id,
        )
    await document_attachment_service.delete_document_attachment(
        document.id,
        attachment.id,
        actor_agent_id=owner.id,
    )
    assert await document_attachment_service.list_document_attachments(
        document.id,
        actor_agent_id=owner.id,
    ) == []
    assert await get_storage("native").read(str(attachment.id)) == _png_bytes()

    retained = await document_attachment_service.add_document_attachment(
        document.id,
        actor_agent_id=owner.id,
        upload=UploadFile(
            file=BytesIO(b"content deleted with its document"),
            filename="retained.txt",
            headers={"content-type": "text/plain"},
        ),
    )
    await service.forget_item(document.id, actor_agent_id=owner.id)
    with pytest.raises(ResourceNotFoundError):
        await get_storage("native").read(str(retained.id))


@pytest.mark.asyncio
async def test_document_attachments_are_file_resources_guarded_by_document_acl(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    tmp_path: Path,
) -> None:
    del memory_storage
    owner, reader = agents
    document, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Document attachments",
            payload=MemoryPayload(text="Body"),
            memory_type="working",
            node_kind="document",
        )
    )
    await service.set_item_grant(
        document.id,
        reader.id,
        MemoryGrantUpdate(can_write=False),
        actor_agent_id=owner.id,
    )
    collection_uri = f"document://{document.id}/attachments/"
    owner_ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    reader_ctx = ResourceContext(agent_id=reader.id, runtime="internal")
    image_content = _png_bytes()

    created = await resource_service.resource_create(
        owner_ctx,
        collection_uri,
        image_content,
        name="preview.png",
    )
    copied = await resource_service.resource_copy(
        owner_ctx,
        created.uri,
        collection_uri,
    )
    listing = await resource_service.resource_list(reader_ctx, collection_uri)
    info = await resource_service.resource_info(reader_ctx, created.uri)
    read = await resource_service.resource_read(reader_ctx, created.uri)
    materialized_path = tmp_path / "preview.png"
    materialized = await resource_service.materialize_resource(
        reader_ctx,
        created.uri,
        materialized_path,
        max_bytes=1_024,
    )

    assert {entry.uri for entry in listing.entries} == {created.uri, copied.uri}
    assert info.name == "preview.png"
    assert info.media_type == "image/png"
    assert "read" in info.capabilities
    assert "delete" not in info.capabilities
    assert read.encoding == "base64"
    assert materialized.media_type == "image/png"
    assert materialized_path.read_bytes() == image_content

    with pytest.raises(service.MemoryPermissionError):
        await resource_service.resource_create(
            reader_ctx,
            collection_uri,
            b"forbidden",
            name="forbidden.txt",
        )
    with pytest.raises(service.MemoryPermissionError):
        await resource_service.resource_delete(reader_ctx, created.uri)

    deleted = await resource_service.resource_delete(owner_ctx, created.uri)
    assert deleted.state == "deleted"
    await resource_service.resource_delete(owner_ctx, copied.uri)
    assert (await resource_service.resource_list(owner_ctx, collection_uri)).entries == []


@pytest.mark.asyncio
async def test_search_sorts_every_list_column_in_both_directions(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    unused, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=peer.id,
            title="Charlie memory",
            payload=MemoryPayload(text="This memory has not been read directly."),
            memory_type="working",
            visibility="public",
        )
    )
    once, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Alpha memory",
            payload=MemoryPayload(text="This memory has one direct read."),
            memory_type="semantic",
            visibility="private",
        )
    )
    twice, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Bravo memory",
            payload=MemoryPayload(text="This memory has two direct reads."),
            memory_type="core",
            visibility="shared",
        )
    )

    await service.get_item(
        once.id,
        agent_id=owner.id,
        record_llm_access=True,
    )
    await service.get_item(
        twice.id,
        agent_id=owner.id,
        record_llm_access=True,
    )
    await service.get_item(
        twice.id,
        agent_id=owner.id,
        record_llm_access=True,
    )

    once.last_accessed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    twice.last_accessed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    unused.last_accessed_at = None
    once.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    twice.updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    unused.updated_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    await db.commit()

    async def sorted_ids(
        sort_by: MemorySortField, *, descending: bool
    ) -> list[UUID]:
        page = await service.search_items(
            MemorySearchRequest(
                agent_id=owner.id,
                sort_by=sort_by,
                sort_desc=descending,
            )
        )
        return [hit.item.id for hit in page.hits]

    expected_orders: dict[
        MemorySortField, tuple[list[UUID], list[UUID]]
    ] = {
        "title": (
            [once.id, twice.id, unused.id],
            [unused.id, twice.id, once.id],
        ),
        "memory_type": (
            [twice.id, once.id, unused.id],
            [unused.id, once.id, twice.id],
        ),
        "visibility": (
            [once.id, unused.id, twice.id],
            [twice.id, unused.id, once.id],
        ),
        "access_count": (
            [unused.id, once.id, twice.id],
            [twice.id, once.id, unused.id],
        ),
        "last_accessed_at": (
            [once.id, twice.id, unused.id],
            [twice.id, once.id, unused.id],
        ),
        "updated_at": (
            [once.id, twice.id, unused.id],
            [unused.id, twice.id, once.id],
        ),
    }
    for sort_by, (ascending, descending) in expected_orders.items():
        assert await sorted_ids(sort_by, descending=False) == ascending
        assert await sorted_ids(sort_by, descending=True) == descending

    owner_ascending = await service.search_items(
        MemorySearchRequest(
            agent_id=owner.id,
            sort_by="owner",
            sort_desc=False,
        )
    )
    assert [hit.item.owner_agent_id for hit in owner_ascending.hits] == [
        owner.id,
        owner.id,
        peer.id,
    ]
    owner_descending = await service.search_items(
        MemorySearchRequest(
            agent_id=owner.id,
            sort_by="owner",
            sort_desc=True,
        )
    )
    assert [hit.item.owner_agent_id for hit in owner_descending.hits] == [
        peer.id,
        owner.id,
        owner.id,
    ]


@pytest.mark.asyncio
async def test_only_explicit_llm_reads_update_memory_usage(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="LLM-only usage",
            payload=MemoryPayload(text="Initial durable content."),
        )
    )
    content_updated = await service.update_item(
        item.id,
        MemoryItemUpdate(
            expected_revision=item.revision,
            payload=MemoryPayload(text="Updated durable content."),
        ),
        actor_agent_id=owner.id,
    )
    content_updated_at = content_updated.updated_at
    assert content_updated_at is not None

    await service.get_item(item.id, agent_id=owner.id)
    await service.search_items(MemorySearchRequest(agent_id=owner.id))
    await db.refresh(content_updated)
    assert content_updated.access_count == 0
    assert content_updated.last_accessed_at is None
    assert content_updated.updated_at == content_updated_at

    task_id = uuid4()
    llm_read, _content, _access, _content_type, _media_type = (
        await service.get_item(
            item.id,
            agent_id=owner.id,
            record_llm_access=True,
            task_id=task_id,
        )
    )
    assert llm_read.access_count == 1
    assert llm_read.last_accessed_at is not None
    assert llm_read.updated_at == content_updated_at

    await service.search_items(
        MemorySearchRequest(agent_id=owner.id, task_id=task_id),
        record_llm_access=True,
    )
    await db.refresh(llm_read)
    assert llm_read.access_count == 2
    assert llm_read.last_accessed_at is not None
    assert llm_read.updated_at == content_updated_at
    assert (
        await db.scalar(
            select(func.count(MemoryUsage.id)).where(
                MemoryUsage.item_id == item.id
            )
        )
        == 2
    )
    usage_kinds = await db.scalars(
        select(MemoryUsage.access_kind)
        .where(MemoryUsage.item_id == item.id)
        .order_by(MemoryUsage.access_kind)
    )
    assert list(usage_kinds.all()) == ["read", "search"]


@pytest.mark.asyncio
async def test_llm_read_usage_stays_in_the_callers_transaction(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Transactional usage",
            payload=MemoryPayload(text="Durable content."),
        )
    )
    item_id = item.id

    await service.get_item(
        item_id,
        agent_id=owner.id,
        record_llm_access=True,
        task_id=uuid4(),
    )
    await db.rollback()

    reloaded = await db.get(MemoryItem, item_id)
    assert reloaded is not None
    assert reloaded.access_count == 0
    assert reloaded.last_accessed_at is None
    assert (
        await db.scalar(
            select(func.count(MemoryUsage.id)).where(MemoryUsage.item_id == item_id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_repeated_task_read_records_one_usage_without_conflict(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Idempotent usage",
            payload=MemoryPayload(text="Durable content."),
        )
    )
    task_id = uuid4()

    for _index in range(2):
        await service.get_item(
            item.id,
            agent_id=owner.id,
            record_llm_access=True,
            task_id=task_id,
        )
    await db.commit()

    assert (
        await db.scalar(
            select(func.count(MemoryUsage.id)).where(
                MemoryUsage.item_id == item.id,
                MemoryUsage.task_id == task_id,
                MemoryUsage.access_kind == "read",
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_llm_retrieval_does_not_learn_from_co_injection(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    first, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="First retrieved memory",
            payload=MemoryPayload(text="First content."),
        )
    )
    second, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Second retrieved memory",
            payload=MemoryPayload(text="Second content."),
        )
    )

    await service.record_llm_retrieval(
        agent_id=owner.id,
        item_scores=((first.id, 0.9), (second.id, 0.8)),
        query="shared retrieval",
        task_id=uuid4(),
    )

    association_count = await db.scalar(select(func.count(MemoryAssociation.id)))
    assert association_count == 0


@pytest.mark.asyncio
async def test_memory_updated_at_tracks_only_payload_or_keyword_changes(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Content timestamp",
            payload=MemoryPayload(text="Initial content."),
        )
    )
    assert item.updated_at is None

    title_updated = await service.update_item(
        item.id,
        MemoryItemUpdate(
            expected_revision=item.revision,
            title="Renamed memory",
        ),
        actor_agent_id=owner.id,
    )
    assert title_updated.updated_at is None

    grant_updated = await service.set_item_grant(
        item.id,
        peer.id,
        MemoryGrantUpdate(can_write=False),
    )
    assert grant_updated.updated_at is None

    content_updated = await service.update_item(
        item.id,
        MemoryItemUpdate(
            expected_revision=grant_updated.revision,
            payload=MemoryPayload(text="Meaningfully changed content."),
        ),
        actor_agent_id=owner.id,
    )
    content_updated_at = content_updated.updated_at
    assert content_updated_at is not None

    metadata_updated = await service.update_item(
        item.id,
        MemoryItemUpdate(
            expected_revision=content_updated.revision,
            metadata={"audit": "technical"},
        ),
        actor_agent_id=owner.id,
    )
    assert metadata_updated.updated_at == content_updated_at

    keyword_updated = await service.update_item(
        item.id,
        MemoryItemUpdate(
            expected_revision=metadata_updated.revision,
            keywords=["durable", "procedure"],
        ),
        actor_agent_id=owner.id,
    )
    keyword_updated_at = keyword_updated.updated_at
    assert keyword_updated_at is not None
    assert keyword_updated_at >= content_updated_at

    unchanged_keywords = await service.update_item(
        item.id,
        MemoryItemUpdate(
            expected_revision=keyword_updated.revision,
            keywords=["durable", "procedure"],
        ),
        actor_agent_id=owner.id,
    )
    assert unchanged_keywords.updated_at == keyword_updated_at


@pytest.mark.asyncio
async def test_graph_roots_use_activity_keysets_and_hide_inaccessible_edges(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents

    async def create(
        title: str,
        *,
        owner_agent_id: int = owner.id,
    ) -> MemoryItem:
        item, _created = await service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner_agent_id,
                title=title,
                payload=MemoryPayload(text=f"Graph payload for {title}"),
            )
        )
        return item

    newest = await create("Newest")
    middle = await create("Middle")
    oldest = await create("Oldest")
    hidden = await create("Hidden", owner_agent_id=peer.id)
    newest.updated_at = datetime(2030, 1, 4, tzinfo=timezone.utc)
    middle.updated_at = datetime(2030, 1, 3, tzinfo=timezone.utc)
    oldest.updated_at = datetime(2030, 1, 2, tzinfo=timezone.utc)
    hidden.updated_at = datetime(2030, 1, 5, tzinfo=timezone.utc)
    await db.commit()

    newest_middle = await service.create_link(
        MemoryLinkCreate(
            source_item_id=newest.id,
            target_item_id=middle.id,
            relation_type="related_to",
        ),
        actor_agent_id=owner.id,
    )
    middle_oldest = await service.create_link(
        MemoryLinkCreate(
            source_item_id=middle.id,
            target_item_id=oldest.id,
            relation_type="precedes",
        ),
        actor_agent_id=owner.id,
    )
    await service.create_link(
        MemoryLinkCreate(
            source_item_id=newest.id,
            target_item_id=hidden.id,
            relation_type="must_stay_hidden",
        ),
        actor_agent_id=None,
        administrative=True,
    )

    first = await service.list_graph_roots(
        MemoryGraphRootsRequest(agent_id=owner.id, limit=2)
    )
    assert [node.id for node in first.nodes] == [newest.id, middle.id]
    assert all(node.entity_kind == "memory" for node in first.nodes)
    assert [edge.id for edge in first.edges] == [newest_middle.id]
    assert all(node.has_relations for node in first.nodes)
    assert [node.relation_count for node in first.nodes] == [1, 2]
    assert first.has_more
    assert first.next_cursor is not None

    second = await service.list_graph_roots(
        MemoryGraphRootsRequest(
            agent_id=owner.id,
            limit=2,
            cursor=first.next_cursor,
            known_item_ids=[node.id for node in first.nodes],
        )
    )
    assert [node.id for node in second.nodes] == [oldest.id]
    assert [edge.id for edge in second.edges] == [middle_oldest.id]
    assert second.nodes[0].relation_count == 1
    assert not second.has_more
    assert second.next_cursor is None


@pytest.mark.asyncio
async def test_graph_exposes_structural_roles_but_not_agent_projection(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    agent_item = await service.upsert_source_managed_item(
        SourceMemoryDocument(
            source_kind="agent",
            source_ref=f"agent:{owner.id}",
            owner_agent_id=owner.id,
            memory_item_id=None,
            title="Agent structurel",
            memory_type="core",
            content="# Agent",
            filename="agent.md",
            keywords=("agent",),
            metadata={},
        )
    )
    contact_item = await service.upsert_source_managed_item(
        SourceMemoryDocument(
            source_kind="messenger_contact",
            source_ref=f"contact:test:{owner.id}",
            owner_agent_id=owner.id,
            memory_item_id=None,
            title="Contact structurel",
            memory_type="social",
            content="# Contact",
            filename="contact.md",
            keywords=("contact",),
            metadata={},
        )
    )
    topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Topic structurel")
    )
    assert topic.memory_item_id is not None
    document, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Document structurel",
            payload=MemoryPayload(text="Document visible dans le graphe."),
            memory_type="working",
            node_kind="document",
        )
    )
    await service.ensure_topic_memory_link(
        topic_item_id=topic.memory_item_id,
        memory_item_id=document.id,
    )

    page = await service.list_graph_roots(
        MemoryGraphRootsRequest(agent_id=owner.id, limit=100)
    )
    by_id = {node.id: node.entity_kind for node in page.nodes}

    assert agent_item.id not in by_id
    assert by_id[contact_item.id] == "contact"
    assert by_id[topic.memory_item_id] == "topic"
    assert by_id[document.id] == "document"


@pytest.mark.asyncio
async def test_graph_expansion_pages_recent_visible_neighbors(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents

    async def create(
        title: str,
        *,
        owner_agent_id: int = owner.id,
    ) -> MemoryItem:
        item, _created = await service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner_agent_id,
                title=title,
                payload=MemoryPayload(text=f"Expandable graph payload for {title}"),
            )
        )
        return item

    focus = await create("Focus")
    newest = await create("Newest neighbor")
    middle = await create("Middle neighbor")
    oldest = await create("Oldest neighbor")
    hidden = await create("Hidden neighbor", owner_agent_id=peer.id)
    focus.updated_at = datetime(2030, 2, 1, tzinfo=timezone.utc)
    newest.updated_at = datetime(2030, 1, 4, tzinfo=timezone.utc)
    middle.updated_at = datetime(2030, 1, 3, tzinfo=timezone.utc)
    oldest.updated_at = datetime(2030, 1, 2, tzinfo=timezone.utc)
    hidden.updated_at = datetime(2030, 1, 5, tzinfo=timezone.utc)
    await db.commit()

    for neighbor in (newest, middle, oldest):
        await service.create_link(
            MemoryLinkCreate(
                source_item_id=focus.id,
                target_item_id=neighbor.id,
                relation_type=f"relation_{neighbor.title.split()[0].lower()}",
            ),
            actor_agent_id=owner.id,
        )
    await service.create_link(
        MemoryLinkCreate(
            source_item_id=focus.id,
            target_item_id=hidden.id,
            relation_type="must_stay_hidden",
        ),
        actor_agent_id=None,
        administrative=True,
    )

    first = await service.expand_graph_node(
        MemoryGraphExpandRequest(
            agent_id=owner.id,
            item_id=focus.id,
            limit=2,
        )
    )
    assert [node.id for node in first.nodes] == [newest.id, middle.id]
    assert len(first.edges) == 2
    assert all(node.has_relations for node in first.nodes)
    assert all(node.relation_count == 1 for node in first.nodes)
    assert first.has_more
    assert first.next_cursor is not None

    second = await service.expand_graph_node(
        MemoryGraphExpandRequest(
            agent_id=owner.id,
            item_id=focus.id,
            limit=2,
            cursor=first.next_cursor,
        )
    )
    assert [node.id for node in second.nodes] == [oldest.id]
    assert len(second.edges) == 1
    assert not second.has_more
    assert second.next_cursor is None
    assert {
        node.id for node in [*first.nodes, *second.nodes]
    } == {newest.id, middle.id, oldest.id}

    unseen = await service.expand_graph_node(
        MemoryGraphExpandRequest(
            agent_id=owner.id,
            item_id=focus.id,
            limit=2,
            known_item_ids=[newest.id, middle.id],
        )
    )
    assert [node.id for node in unseen.nodes] == [oldest.id]
    assert len(unseen.edges) == 1
    assert not unseen.has_more
