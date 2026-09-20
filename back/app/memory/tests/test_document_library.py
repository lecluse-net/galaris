from __future__ import annotations

from core.user import HumanActor

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import AgentManagementScope
from app.agent.models import Agent
from app.memory import conversation_document_adapter, service
from app.memory.assertions import ManagedDocumentAccessAssertion
from app.memory.contracts import ResourceNotFoundError
from app.memory.router import (
    browse_managed_documents,
    change_document_owner,
    create_managed_document,
    export_managed_document_pdf,
    diff_managed_document_content_revision,
    list_managed_document_content_revisions,
    move_managed_document,
    read_recent_memories,
    read_document_folders,
    read_managed_document_content_revision,
    read_managed_document,
    remove_managed_document_grant,
    restore_managed_document_content_revision,
    set_managed_document_global_access,
    set_managed_document_grant,
    save_document_icon,
)
from app.memory.schemas import (
    DocumentFolderUpdate,
    DocumentCreate,
    DocumentPdfExport,
    DocumentGlobalAccessUpdate,
    DocumentLibraryRequest,
    DocumentOwnerUpdate,
    MemoryGrantUpdate,
    MemoryItemCreate,
    MemoryItemUpdate,
    MemoryPayload,
)
from app.memory.storage import get_storage
from core.authorize import Privileges
from core.user import UserModel


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_title", [False, True])
async def test_chat_keeps_only_deleted_document_title_without_restoring_access(
    db, agents, memory_storage, monkeypatch, legacy_title,
):
    from app.chat.document_previews import with_deleted_document_previews
    from app.conversation import document_metadata
    from app.messenger import MessageResourcePreview

    owner, peer = agents
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Rapport annuel", node_kind="document",
        memory_type="working", payload=MemoryPayload(text="Confidential body"),
    ))
    inaccessible, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Private live document", node_kind="document",
        memory_type="working", payload=MemoryPayload(text="Private body"),
    ))
    resource_id = item.resource_id
    await service.forget_item(item.id, actor_agent_id=owner.id)
    if legacy_title:
        item.title = "Forgotten memory"
        await db.commit()
    monkeypatch.setattr(document_metadata, "_resolver", conversation_document_adapter.resolve_conversation_document_metadata)
    uri = f"document://{item.id}"
    existing = MessageResourcePreview(uri="https://example.test", kind="web", title="Existing preview")
    previews = await with_deleted_document_previews(
        (uri, existing.uri, f"document://{inaccessible.id}", f"document://{uuid4()}", f"document://{item.id}/attachments/{uuid4()}"),
        [existing],
    )
    assert [preview.uri for preview in previews] == [uri, existing.uri]
    deleted = previews[0]
    assert deleted.deleted
    assert deleted.title == ("" if legacy_title else "Rapport annuel")
    assert deleted.content is None and deleted.description == "" and deleted.metadata == {}
    assert not deleted.image_available and not deleted.download_available
    for actor in (owner.id, peer.id):
        with pytest.raises(service.MemoryNotFoundError):
            await service.get_item(item.id, agent_id=actor)
    with pytest.raises(ResourceNotFoundError):
        await get_storage().read(resource_id)


@pytest.mark.asyncio
async def test_folder_roles_follow_metadata_and_real_access_not_names(
    agents: tuple[Agent, Agent], memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    for agent, path, goal, shared in [
        (owner, "Personal/Notes", False, False),
        (peer, "Personal/Notes", False, False),
        (owner, "Shared/Reports", False, True),
        (owner, "Objectifs/First", True, False),
        (owner, "Objectifs/Team", True, True),
        (owner, "Goals/Custom folder", False, False),
        (peer, "Hidden", True, False),
    ]:
        metadata: dict[str, object] = {"document_path": path}
        if goal:
            metadata["goal_document_kind"] = "description"
        item, _created = await service.create_item(MemoryItemCreate(
            owner_agent_id=agent.id, title=path, payload=MemoryPayload(text="Document"),
            memory_type="working", node_kind="document", metadata=metadata,
        ))
        if shared:
            await service.set_item_grant(item.id, peer.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)

    options = {folder.path: folder for folder in await service.list_document_folder_options(owner.id)}
    assert options["Personal"].kind == "custom"
    assert options["Personal"].shared is False
    assert options["Personal/Notes"].shared is False
    assert options["Shared"].shared is True
    assert options["Shared/Reports"].shared is True
    assert options["Objectifs"].kind == "goal"
    assert options["Objectifs"].shared is True
    assert options["Objectifs/First"].shared is False
    assert options["Objectifs/Team"].kind == "goal"
    assert options["Objectifs/Team"].shared is True
    assert options["Goals/Custom folder"].kind == "custom"
    assert "Hidden" not in options
    peer_options = {folder.path: folder for folder in await service.list_document_folder_options(peer.id)}
    assert peer_options["Shared/Reports"] == options["Shared/Reports"]
    assert peer_options["Personal/Notes"].shared is False
    # Existing clients still receive only stored paths, without ancestor entries.
    assert "Personal/Notes" in await service.list_document_folders(owner.id)
    assert "Personal" not in await service.list_document_folders(owner.id)


@pytest.mark.asyncio
async def test_folder_details_endpoint_preserves_agent_scope(
    agents: tuple[Agent, Agent], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.memory import router as memory_router

    owner, peer = agents
    monkeypatch.setattr(memory_router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(
        user_id=owner.user_id, agent_ids=frozenset({owner.id}),
    )))
    reader = AsyncMock(return_value=[])
    monkeypatch.setattr(service, "list_document_folder_options", reader)
    assert await read_document_folders(agent_id=owner.id, details=True) == []
    reader.assert_awaited_once_with(owner.id)
    with pytest.raises(HTTPException) as denied:
        await read_document_folders(agent_id=peer.id, details=True)
    assert denied.value.status_code == 404
    reader.assert_awaited_once()


@pytest.mark.asyncio
async def test_library_unites_owned_and_granted_documents(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    managed, peer = agents
    owned, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=managed.id,
            title="Owned document",
            payload=MemoryPayload(text="Owned"),
            memory_type="working",
            node_kind="document",
        )
    )
    shared, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=peer.id,
            title="Shared document",
            payload=MemoryPayload(text="Shared"),
            memory_type="working",
            node_kind="document",
        )
    )
    await service.set_item_grant(
        shared.id,
        managed.id,
        MemoryGrantUpdate(can_write=False),
        actor_agent_id=peer.id,
    )

    page = await service.browse_document_library(
        DocumentLibraryRequest(),
        managed_agent_ids=frozenset({managed.id}),
    )
    by_id = {entry.item.id: entry for entry in page.entries}

    assert set(by_id) == {owned.id, shared.id}
    assert by_id[owned.id].agent_ids == [managed.id]
    assert by_id[owned.id].writable_agent_ids == [managed.id]
    assert by_id[shared.id].agent_ids == [managed.id]
    assert by_id[shared.id].writable_agent_ids == []
    from sqlalchemy import inspect
    assert "revisions" in inspect(owned).unloaded
    assert "revisions" in inspect(shared).unloaded


@pytest.mark.asyncio
async def test_recent_memories_respect_management_scope_and_hide_documents(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    managed, peer = agents
    owned, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=managed.id,
            title="Recent owned memory",
            payload=MemoryPayload(text="Owned"),
        )
    )
    shared, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=peer.id,
            title="Recent shared memory",
            payload=MemoryPayload(text="Shared"),
        )
    )
    hidden, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=peer.id,
            title="Hidden peer memory",
            payload=MemoryPayload(text="Hidden"),
        )
    )
    document, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=managed.id,
            title="Recent document",
            payload=MemoryPayload(text="Document"),
            memory_type="working",
            node_kind="document",
        )
    )
    await service.set_item_grant(
        shared.id,
        managed.id,
        MemoryGrantUpdate(can_write=False),
        actor_agent_id=peer.id,
    )

    recent = await service.list_recent_memories(
        managed_agent_ids=frozenset({managed.id}),
        limit=50,
    )
    ids = {item.id for item in recent}

    assert owned.id in ids
    assert shared.id in ids
    assert hidden.id not in ids
    assert document.id not in ids


def test_recent_memories_require_a_memory_privilege() -> None:
    assert read_recent_memories._authorize_meta[  # pyright: ignore[reportFunctionMemberAccess]
        "privileges"
    ] == [
        Privileges.MEMORY_ACCESS,
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ]


def test_document_library_routes_use_the_dedicated_assertion() -> None:
    for endpoint in (
        browse_managed_documents,
        read_managed_document,
        export_managed_document_pdf,
        move_managed_document,
        change_document_owner,
        list_managed_document_content_revisions,
        read_managed_document_content_revision,
        diff_managed_document_content_revision,
        restore_managed_document_content_revision,
        set_managed_document_global_access,
        set_managed_document_grant,
        remove_managed_document_grant,
        save_document_icon,
    ):
        metadata = endpoint._authorize_meta  # pyright: ignore[reportFunctionMemberAccess]
        assert metadata["assertion"] is ManagedDocumentAccessAssertion


def test_document_create_requires_an_agent_owner_to_be_its_initial_editor() -> None:
    with pytest.raises(ValidationError):
        DocumentCreate(
            owner_kind="agent",
            owner_id=1,
            actor_agent_id=2,
            title="Invalid ownership",
        )


@pytest.mark.asyncio
async def test_pdf_export_requires_read_access_and_preserves_the_saved_revision(
    agents: tuple[Agent, Agent], memory_storage: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.memory import document_export, router as memory_router

    del memory_storage
    owner, peer = agents
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Exportable", memory_type="working", node_kind="document",
        media_type="text/html", payload=MemoryPayload(text="<p>Saved</p>"),
    ))
    revision = item.revision
    rendered = AsyncMock(return_value=b"%PDF-1.7\nexported")
    monkeypatch.setattr(document_export, "render_html_pdf", rendered)
    monkeypatch.setattr(memory_router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(
        user_id=1, agent_ids=frozenset({peer.id}),
    )))
    snapshot = DocumentPdfExport(html="<p>Unsaved current content</p>")
    with pytest.raises(HTTPException) as denied:
        await export_managed_document_pdf(item.id, snapshot)
    assert denied.value.status_code == 404
    rendered.assert_not_awaited()
    await service.set_item_grant(item.id, peer.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    response = await export_managed_document_pdf(item.id, snapshot)
    assert response.media_type == "application/pdf"
    assert response.body == b"%PDF-1.7\nexported"
    rendered.assert_awaited_once_with(snapshot.html)
    saved, content, _access, _type, _media = await service.get_item(item.id, agent_id=owner.id, record_llm_access=False)
    assert saved.revision == revision
    assert content == b"<p>Saved</p>"


@pytest.mark.asyncio
@pytest.mark.parametrize("document_type", ["html", "dataset"])
async def test_user_owned_document_is_created_with_a_writable_agent(
    agents: tuple[Agent, Agent],
    db: AsyncSession,
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    document_type,
) -> None:
    from app.memory import router as memory_router

    del memory_storage
    editor, _peer = agents
    user = UserModel(
        email="new-document-owner@example.test",
        display_name="New Document Owner",
        hashed_password="unused",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    monkeypatch.setattr(
        memory_router,
        "current_management_scope",
        AsyncMock(
            return_value=AgentManagementScope(
                user_id=user.id,
                agent_ids=frozenset({editor.id}),
            )
        ),
    )

    created = await create_managed_document(
        DocumentCreate(
            owner_kind="user",
            owner_id=user.id,
            actor_agent_id=editor.id,
            title="My document",
            document_type=document_type,
            folder="Projects",
        )
    )
    document, _content, access, _content_type, _media_type = await service.get_item(
        created.id,
        agent_id=HumanActor(user.id),
        record_llm_access=False,
    )

    assert document.owner_agent_id is None
    assert document.owner_user_id == user.id
    assert document.metadata_["document_path"] == "Projects"
    assert document.grants == []
    assert not (await service.effective_access(document, editor.id)).can_read
    assert access.can_write is True
    assert document.document_type == document_type
    assert _content == (b"{}" if document_type == "dataset" else b"")
    assert created.document_type == document_type


@pytest.mark.asyncio
async def test_document_creation_rejects_another_user_without_privilege(
    agents: tuple[Agent, Agent],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.memory import router as memory_router

    editor, _peer = agents
    current = UserModel(
        email="current-document-user@example.test",
        display_name="Current Document User",
        hashed_password="unused",
        is_active=True,
    )
    other = UserModel(
        email="other-document-user@example.test",
        display_name="Other Document User",
        hashed_password="unused",
        is_active=True,
    )
    db.add_all([current, other])
    await db.flush()
    monkeypatch.setattr(
        memory_router,
        "current_management_scope",
        AsyncMock(
            return_value=AgentManagementScope(
                user_id=current.id,
                agent_ids=frozenset({editor.id}),
            )
        ),
    )
    monkeypatch.setattr(memory_router, "check_privilege", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as exc_info:
        await create_managed_document(
            DocumentCreate(
                owner_kind="user",
                owner_id=other.id,
                actor_agent_id=editor.id,
                title="Forbidden owner",
            )
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_document_history_tracks_all_content_and_restores_forward(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    document, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Versioned document",
            media_type="text/html",
            payload=MemoryPayload(text="<p>Initial line</p>"),
            memory_type="working",
            node_kind="document",
        )
    )
    initial_revision = document.revision

    human_edit = await service.update_item(
        document.id,
        MemoryItemUpdate(
            expected_revision=document.revision,
            payload=MemoryPayload(text="<p>Human draft</p>"),
        ),
        actor_agent_id=owner.id,
    )
    assert human_edit.revision == initial_revision + 1
    assert [
        revision.revision
        for revision in (
            await service.list_document_content_revisions(
                document.id,
                actor_agent_id=owner.id,
            )
        ).items
    ] == [2, 1]

    agent_edit = await service.update_item(
        document.id,
        MemoryItemUpdate(
            expected_revision=human_edit.revision,
            payload=MemoryPayload(text="<p>Agent draft</p><p>Added line</p>"),
        ),
        actor_agent_id=owner.id,
        document_revision_author_agent_id=owner.id,
    )
    renamed = await service.update_item(
        document.id,
        MemoryItemUpdate(
            expected_revision=agent_edit.revision,
            title="Current title",
            keywords=["current", "document"],
            metadata={"document_path": "Projects"},
        ),
        actor_agent_id=owner.id,
    )
    assert renamed.revision == agent_edit.revision
    shared = await service.set_item_grant(
        document.id,
        peer.id,
        MemoryGrantUpdate(can_write=False),
        actor_agent_id=owner.id,
    )
    assert shared.revision == agent_edit.revision

    revisions = await service.list_document_content_revisions(
        document.id,
        actor_agent_id=owner.id,
    )
    assert [revision.revision for revision in revisions.items] == [3, 2, 1]
    assert revisions.total == 3
    assert revisions.has_more is False
    middle_page = await service.list_document_content_revisions(
        document.id,
        actor_agent_id=owner.id,
        limit=1,
        offset=1,
    )
    assert [revision.revision for revision in middle_page.items] == [2]
    assert middle_page.total == 3
    assert middle_page.has_more is True
    assert revisions.items[0].author_agent_id == owner.id
    detail = await service.get_document_content_revision(
        document.id,
        3,
        actor_agent_id=owner.id,
    )
    assert detail.content == "<p>Agent draft</p><p>Added line</p>"
    diff = await service.diff_document_content_revision(
        document.id,
        1,
        actor_agent_id=owner.id,
    )
    assert diff.current_revision == shared.revision
    assert diff.additions == 2
    assert diff.deletions == 1

    restored = await service.restore_document_content_revision(
        document.id,
        1,
        expected_revision=shared.revision,
        actor_agent_id=owner.id,
    )
    restored_item, restored_content, _access, _content_type, _media_type = (
        await service.get_item(document.id, agent_id=owner.id)
    )
    assert restored.id == restored_item.id
    assert restored_content == b"<p>Initial line</p>"
    assert restored_item.title == "Current title"
    assert restored_item.keywords == ["current", "document"]
    assert restored_item.metadata_["document_path"] == "Projects"
    assert [(grant.agent_id, grant.can_write) for grant in restored_item.grants] == [
        (peer.id, False)
    ]
    assert [
        revision.revision
        for revision in (
            await service.list_document_content_revisions(
                document.id,
                actor_agent_id=owner.id,
            )
        ).items
    ] == [restored.revision, 3, 2, 1]
    human_detail = await service.get_document_content_revision(
        document.id,
        2,
        actor_agent_id=owner.id,
    )
    assert human_detail.content == "<p>Human draft</p>"
    restored_revision = restored.revision
    restored_human = await service.restore_document_content_revision(
        document.id,
        2,
        expected_revision=restored_revision,
        actor_agent_id=owner.id,
    )
    _item, human_content, _access, _content_type, _media_type = (
        await service.get_item(document.id, agent_id=owner.id)
    )
    assert restored_human.revision == restored_revision + 1
    assert human_content == b"<p>Human draft</p>"


@pytest.mark.asyncio
async def test_document_lock_detects_metadata_and_grant_conflicts(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    document, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Concurrent document",
            payload=MemoryPayload(text="Body"),
            memory_type="working",
            node_kind="document",
        )
    )
    initial_lock_version = document.lock_version

    renamed = await service.update_item(
        document.id,
        MemoryItemUpdate(
            expected_revision=document.revision,
            expected_lock_version=initial_lock_version,
            title="Renamed",
        ),
        actor_agent_id=owner.id,
    )
    assert renamed.revision == document.revision
    renamed_lock_version = renamed.lock_version
    assert renamed_lock_version > initial_lock_version
    with pytest.raises(service.MemoryConflictError):
        await service.update_item(
            document.id,
            MemoryItemUpdate(
                expected_revision=document.revision,
                expected_lock_version=initial_lock_version,
                title="Stale metadata",
            ),
            actor_agent_id=owner.id,
        )

    shared = await service.set_item_grant(
        document.id,
        peer.id,
        MemoryGrantUpdate(
            can_write=False,
            expected_lock_version=renamed_lock_version,
        ),
        actor_agent_id=owner.id,
    )
    assert shared.revision == document.revision
    assert shared.lock_version > renamed_lock_version
    with pytest.raises(service.MemoryConflictError):
        await service.set_item_grant(
            document.id,
            peer.id,
            MemoryGrantUpdate(
                can_write=True,
                expected_lock_version=renamed_lock_version,
            ),
            actor_agent_id=owner.id,
        )


@pytest.mark.asyncio
async def test_chat_created_document_is_durable_and_follows_document_acl(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    room_id = uuid4()
    created = await conversation_document_adapter.create_conversation_room_document(
        room_id,
        owner.id,
        "Chat draft",
    )

    owner_documents = (
        await conversation_document_adapter.resolve_conversation_room_documents(
            room_id,
            owner.id,
        )
    )
    assert owner_documents == (created,)
    assert (
        await conversation_document_adapter.resolve_conversation_room_documents(
            room_id,
            peer.id,
        )
    ) == ()

    item, _content, _access, _content_type, _media_type = await service.get_item(
        created.id,
        agent_id=owner.id,
    )
    assert item.metadata_["conversation_room_id"] == str(room_id)
    await service.set_item_grant(
        created.id,
        peer.id,
        MemoryGrantUpdate(can_write=False),
        actor_agent_id=owner.id,
    )
    assert [
        document.id
        for document in await conversation_document_adapter.resolve_conversation_room_documents(
            room_id,
            peer.id,
        )
    ] == [created.id]


@pytest.mark.asyncio
async def test_document_owner_can_move_between_agent_and_user_without_losing_editor(
    agents: tuple[Agent, Agent],
    db: AsyncSession,
    memory_storage: Path,
) -> None:
    del memory_storage
    editor, target_agent = agents
    user = UserModel(
        email="document-owner@example.test",
        display_name="Document Owner",
        hashed_password="unused",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    document, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=editor.id,
            title="Transferable document",
            payload=MemoryPayload(text="Body"),
            memory_type="working",
            node_kind="document",
        )
    )

    user_owned = await service.transfer_document_owner(
        document.id,
        DocumentOwnerUpdate(
            expected_revision=document.revision,
            kind="user",
            id=user.id,
        ),
        actor_agent_id=editor.id,
    )
    assert user_owned.owner_agent_id is None
    assert user_owned.owner_user_id == user.id
    assert any(
        grant.agent_id == editor.id and grant.can_write
        for grant in user_owned.grants
    )
    assert user_owned.revision == document.revision

    agent_owned = await service.transfer_document_owner(
        document.id,
        DocumentOwnerUpdate(
            expected_revision=user_owned.revision,
            kind="agent",
            id=target_agent.id,
        ),
        actor_agent_id=editor.id,
    )
    assert agent_owned.owner_agent_id == target_agent.id
    assert agent_owned.owner_user_id is None
    assert any(
        grant.agent_id == editor.id and grant.can_write
        for grant in agent_owned.grants
    )
    assert agent_owned.revision == document.revision


@pytest.mark.asyncio
async def test_owner_options_only_expose_self_without_dedicated_privilege(
    agents: tuple[Agent, Agent],
    db: AsyncSession,
) -> None:
    current = UserModel(
        email="me@example.test",
        display_name="Current User",
        hashed_password="unused",
        is_active=True,
    )
    other = UserModel(
        email="other@example.test",
        display_name="Other User",
        hashed_password="unused",
        is_active=True,
    )
    db.add_all([current, other])
    await db.flush()

    restricted = await service.list_document_owner_options(
        current_user_id=current.id,
        include_all_users=False,
        managed_agent_ids=frozenset({agents[0].id}),
    )
    assert [option.id for option in restricted.users] == [current.id]
    assert restricted.users[0].is_current_user is True
    assert [option.id for option in restricted.agents] == [agents[0].id]

    privileged = await service.list_document_owner_options(
        current_user_id=current.id,
        include_all_users=True,
        managed_agent_ids=None,
        search="other",
    )
    assert [option.id for option in privileged.users] == [other.id]


@pytest.mark.asyncio
async def test_global_document_access_applies_to_current_and_future_agents(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    document, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Global document",
            payload=MemoryPayload(text="Shared with future agents"),
            memory_type="working",
            node_kind="document",
        )
    )

    readable = await service.set_document_global_access(
        document.id,
        DocumentGlobalAccessUpdate(
            expected_revision=document.revision,
            global_access=1,
        ),
        actor_agent_id=owner.id,
    )
    read_access = await service.effective_access(readable, peer.id)
    assert readable.global_access == 1
    assert readable.revision == document.revision
    assert readable.visibility == "shared"
    assert readable.grants == []
    library = await service.browse_document_library(
        DocumentLibraryRequest(), managed_agent_ids={owner.id, peer.id},
    )
    assert [entry.item.id for entry in library.entries] == [document.id]
    assert set(library.entries[0].agent_ids) == {owner.id, peer.id}
    assert read_access.can_read is True
    assert read_access.can_write is False
    with pytest.raises(service.MemoryPermissionError):
        await service.update_item(
            document.id,
            MemoryItemUpdate(title="Read-only Agent edit"),
            actor_agent_id=peer.id,
        )

    writable = await service.set_document_global_access(
        document.id,
        DocumentGlobalAccessUpdate(
            expected_revision=readable.revision,
            global_access=2,
        ),
        actor_agent_id=owner.id,
    )
    write_access = await service.effective_access(writable, peer.id)
    assert write_access.can_read is True
    assert write_access.can_write is True
    edited = await service.update_item(
        document.id,
        MemoryItemUpdate(title="Edited through global access"),
        actor_agent_id=peer.id,
    )
    assert edited.revision == document.revision

    private = await service.set_document_global_access(
        document.id,
        DocumentGlobalAccessUpdate(
            expected_revision=edited.revision,
            global_access=0,
        ),
        actor_agent_id=owner.id,
    )
    private_access = await service.effective_access(private, peer.id)
    assert private.global_access == 0
    assert private.revision == document.revision
    assert private.visibility == "private"
    assert private_access.can_read is False
    assert private_access.can_write is False


def test_folder_update_normalizes_root_and_rejects_parent_segments() -> None:
    assert DocumentFolderUpdate(expected_revision=1, folder=" /Projets// Été/ ").folder == "Projets/Été"
    assert DocumentFolderUpdate(expected_revision=1, folder=" // ").folder == ""
    with pytest.raises(ValidationError):
        DocumentFolderUpdate(expected_revision=1, folder="Projets/../Secret")


def test_document_content_diff_preserves_final_newline_changes() -> None:
    hunks, additions, deletions = service._content_diff_hunks("Same line\n", "Same line")

    assert hunks
    assert additions == 1
    assert deletions == 1
