from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.agent import AgentManagementScope
from app.chat.document_conversation import read_document_conversation, write_document_conversation
from app.chat.models import ChatDocumentConversation
from app.chat import router
from app.chat.schemas import DocumentConversationPreference
from app.document import Document
from app.messenger import create_internal_room
from app.messenger.models import Room
from core.user import UserModel

from .test_native_facade import _scope


async def _document(db, owner, *, global_access=0):
    document = Document(title="Synthetic working document", provider_code="native",
                        resource_id=str(uuid4()), content_hash="synthetic", owner_user_id=owner.id,
                        global_access=global_access)
    db.add(document)
    await db.flush()
    return document


@pytest.mark.asyncio
async def test_document_conversation_rejects_an_agent_without_document_access(db):
    agent, owner, _ = await _scope(db)
    document = await _document(db, owner, global_access=0)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room
    scope = AgentManagementScope(owner.id, frozenset({agent.id}))
    with pytest.raises(PermissionError):
        await write_document_conversation(document.id, room.id, scope)
    document.global_access = 1
    await db.flush()
    await write_document_conversation(document.id, room.id, scope)
    assert await read_document_conversation(document.id, scope) == room.id
    document.global_access = 0
    await db.flush()
    assert await read_document_conversation(document.id, scope) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("access", ["owner", "read", "edit", "team", "global"])
async def test_document_chat_filters_before_pagination_and_checks_creation(db, monkeypatch, access):
    from unittest.mock import AsyncMock
    from app.chat.schemas import RoomCreate
    from app.document.interface import document_access
    from app.share import ShareGrant
    from app.agent import AgentTeamModel
    from core.team import TeamModel

    allowed, owner, outsider = await _scope(db)
    denied, _, _ = await _scope(db)
    document = await _document(db, owner, global_access=0)
    if access == "owner":
        document.owner_user_id = None
        document.owner_agent_id = allowed.id
    elif access == "global":
        document.global_access = 1
    elif access == "team":
        team = TeamModel(name="Synthetic document readers")
        db.add(team)
        await db.flush()
        db.add(AgentTeamModel(agent_id=allowed.id, team_id=team.id))
        db.add(ShareGrant(share_id=document.share_id, team_id=team.id, can_write=False))
    else:
        db.add(ShareGrant(share_id=document.share_id, agent_id=allowed.id, can_write=access == "edit"))
    await db.flush()
    first = await create_internal_room(actor_user_id=owner.id, agent_id=allowed.id)
    second = await create_internal_room(actor_user_id=owner.id, agent_id=allowed.id)
    blocked = await create_internal_room(actor_user_id=owner.id, agent_id=denied.id)
    assert first and second and blocked
    management = AgentManagementScope(owner.id, frozenset({allowed.id}))
    dialogue = AgentManagementScope(owner.id, frozenset({allowed.id, denied.id}))
    monkeypatch.setattr(router.user_service, "get_current_user", AsyncMock(return_value=owner))
    monkeypatch.setattr(router, "check_privilege", AsyncMock(return_value=True))
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=management))
    monkeypatch.setattr(router, "current_dialogue_scope", AsyncMock(return_value=dialogue))
    async def rooms(page=1, document_id=document.id):
        return await router.read_rooms(agent_id=None, page=page, page_size=1, search="", include_external=False,
                                       include_archived=False, recent_days=None, document_id=document_id)
    expected = {first.id, second.id} | ({blocked.id} if access == "global" else set())
    pages = [await rooms(page) for page in range(1, len(expected) + 1)]
    assert all(page.total == len(expected) for page in pages)
    assert {room.id for page in pages for room in page.items} == expected
    assert (await rooms(document_id=None)).total == 3
    recipients = await router.read_recipients(search="", page=1, page_size=500, document_id=document.id)
    assert {agent.agent_id for agent in recipients.agents} == ({allowed.id, denied.id} if access == "global" else {allowed.id})
    assert recipients.total == len(recipients.agents)
    selected = await router.read_room(first.id, agent_id=None, document_id=document.id)
    assert selected.id == first.id
    created = await router.create_room(RoomCreate(agent_id=allowed.id, document_id=document.id))
    assert created.agent_id == allowed.id
    if access != "global":
        before = await db.scalar(select(func.count()).select_from(Room))
        for operation in (router.create_room(RoomCreate(agent_id=denied.id, document_id=document.id)),
                          router.read_room(blocked.id, agent_id=None, document_id=document.id)):
            with pytest.raises(HTTPException) as error:
                await operation
            assert error.value.status_code == 403
        assert await db.scalar(select(func.count()).select_from(Room)) == before
        assert not (await document_access(document.id, denied.id)).can_read
        # Human document access does not override the separate dialogue policy.
        monkeypatch.setattr(router, "current_dialogue_scope", AsyncMock(return_value=AgentManagementScope(owner.id, frozenset())))
        assert (await router.read_recipients(search="", page=1, page_size=500, document_id=document.id)).total == 0
    # Document authorization remains mandatory even when the Chat room is visible.
    monkeypatch.setattr(router, "check_privilege", AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as error:
        await rooms()
    assert error.value.status_code == 403
    if access != "global":
        monkeypatch.setattr(router, "check_privilege", AsyncMock(return_value=True))
        monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(outsider.id, frozenset())))
        with pytest.raises(HTTPException) as error:
            await rooms()
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_last_conversation_is_nullable_unique_and_personal_per_document(db):
    agent, owner, other = await _scope(db)
    first = await _document(db, owner, global_access=1)
    second = await _document(db, owner, global_access=1)
    # Agent-scoped readers may save their personal UI preference without editing the Document.
    managed = Document(title="Agent document", provider_code="native", resource_id=str(uuid4()),
                       content_hash="synthetic", owner_agent_id=agent.id)
    db.add(managed)
    await db.flush()
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    another = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    other_room = await create_internal_room(actor_user_id=other.id, agent_id=agent.id)
    assert room and another and other_room
    scope = AgentManagementScope(owner.id, frozenset())
    other_scope = AgentManagementScope(other.id, frozenset({agent.id}))
    assert await read_document_conversation(first.id, scope) is None
    await write_document_conversation(first.id, room.id, scope)
    await write_document_conversation(second.id, another.id, scope)
    await write_document_conversation(managed.id, other_room.id, other_scope)
    await write_document_conversation(managed.id, room.id, AgentManagementScope(owner.id, frozenset({agent.id})))
    assert await read_document_conversation(managed.id, other_scope) == other_room.id
    assert await read_document_conversation(first.id, scope) == room.id
    assert await read_document_conversation(second.id, scope) == another.id
    await write_document_conversation(first.id, another.id, scope)
    await write_document_conversation(first.id, None, scope)
    assert await read_document_conversation(first.id, scope) is None
    assert await db.scalar(select(func.count()).select_from(ChatDocumentConversation).where(
        ChatDocumentConversation.document_id == first.id, ChatDocumentConversation.user_id == owner.id,
    )) == 1


@pytest.mark.asyncio
async def test_preference_requires_current_document_and_room_access(db):
    from app.share import ShareGrant

    agent, owner, other = await _scope(db)
    document = await _document(db, owner)
    db.add(ShareGrant(share_id=document.share_id, agent_id=agent.id, can_write=False))
    await db.flush()
    scope = AgentManagementScope(owner.id, frozenset())
    outsider = AgentManagementScope(other.id, frozenset())
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    foreign_room = await create_internal_room(actor_user_id=other.id, agent_id=agent.id)
    assert room and foreign_room
    for operation in (
        read_document_conversation(document.id, outsider),
        write_document_conversation(document.id, None, outsider),
        write_document_conversation(document.id, foreign_room.id, scope),
        write_document_conversation(document.id, uuid4(), scope),
    ):
        with pytest.raises(PermissionError):
            await operation
    await write_document_conversation(document.id, room.id, scope)
    record = await db.get(Room, room.id)
    record.soft_delete()
    await db.commit()
    assert await read_document_conversation(document.id, scope) is None
    with pytest.raises(PermissionError):
        await write_document_conversation(document.id, room.id, scope)
    document.soft_delete()
    await db.commit()
    with pytest.raises(FileNotFoundError):
        await read_document_conversation(document.id, scope)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["document", "user", "room"])
async def test_preference_cascades_when_any_referenced_entity_is_deleted(db, target):
    agent, owner, _ = await _scope(db)
    document = await _document(db, owner)
    user = UserModel(email=f"preference-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room
    db.add(ChatDocumentConversation(document_id=document.id, user_id=user.id, room_id=room.id))
    await db.flush()
    model, identity = {"document": (Document, document.id), "user": (UserModel, user.id), "room": (Room, room.id)}[target]
    await db.execute(delete(model).where(model.id == identity))
    await db.flush()
    assert await db.scalar(select(func.count()).select_from(ChatDocumentConversation).where(
        ChatDocumentConversation.document_id == document.id,
    )) == 0


@pytest.mark.asyncio
async def test_preference_routes_require_both_chat_and_document_privileges(db, monkeypatch):
    from unittest.mock import AsyncMock

    _, owner, _ = await _scope(db)
    monkeypatch.setattr(router.user_service, "get_current_user", AsyncMock(return_value=owner))
    monkeypatch.setattr(router, "check_privilege", AsyncMock(return_value=False))
    for handler, args in (
        (router.read_document_conversation_preference, (uuid4(),)),
        (router.update_document_conversation_preference, (uuid4(), DocumentConversationPreference(room_id=None))),
    ):
        with pytest.raises(HTTPException) as denied:
            await handler(*args)
        assert denied.value.status_code == 403
    # The shared authorization contract separately verifies CHAT_ACCESS on both routes.
    monkeypatch.setattr(router, "check_privilege", AsyncMock(return_value=True))
    scope = AgentManagementScope(owner.id, frozenset())
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=scope))
    document = await _document(db, owner)
    assert (await router.read_document_conversation_preference(document.id)).room_id is None
    assert (await router.update_document_conversation_preference(
        document.id, DocumentConversationPreference(room_id=None),
    )).room_id is None
