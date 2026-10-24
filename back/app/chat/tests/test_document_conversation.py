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


async def _document(db, owner):
    document = Document(title="Synthetic working document", provider_code="native",
                        resource_id=str(uuid4()), content_hash="synthetic", owner_user_id=owner.id)
    db.add(document)
    await db.flush()
    return document


@pytest.mark.asyncio
async def test_last_conversation_is_nullable_unique_and_personal_per_document(db):
    agent, owner, other = await _scope(db)
    first = await _document(db, owner)
    second = await _document(db, owner)
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
    agent, owner, other = await _scope(db)
    document = await _document(db, owner)
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
