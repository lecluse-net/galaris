"""Multipart binding, resource ACLs and persistence through the actual Chat API."""

import json
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.chat import storage
from app.conversation import facade as conversation_facade
from app.file_share import ResourceContext, resource_create
from app.messenger import create_internal_room, journal
from app.messenger.models import Message
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user.auth_service import create_access_token

from .test_native_facade import _scope


@pytest_asyncio.fixture
async def attachment_context(committed_database, monkeypatch, tmp_path):
    from core.database import middleware
    from main import app

    # Journal admission uses independent commits. A shared rollback connection
    # cannot represent those transactions or prove persistence across requests.
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(storage, "root", lambda: tmp_path / "chat")
    monkeypatch.setattr(conversation_facade, "wake", Mock())
    async with get_db_session() as db:
        agent, owner, _ = await _scope(db)
        other_agent, _, _ = await _scope(db)
        role = Role(code=f"synthetic-chat-{uuid4().hex}", privileges=list(await db.scalars(select(Privilege))))
        db.add(role)
        await db.flush()
        db.add(Assignment(user_id=owner.id, role_id=role.id))
        room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
        source = await resource_create(ResourceContext(agent.id, "internal"), "file://",
            b"Synthetic internal attachment", name="internal.txt")
        denied = await resource_create(ResourceContext(other_agent.id, "internal"), "file://",
            b"Synthetic private attachment", name="private.txt")
        token = create_access_token({"sub": owner.email, "user_id": owner.id, "role_id": role.id})
        context = {
            "url": f"/api/chat/rooms/{room.id}/attachments",
            "room_id": room.id, "connection_id": room.connection_id, "room_external_id": room.external_id,
            "headers": {"Authorization": f"Bearer {token}"}, "uri": source.uri,
            "denied_uri": denied.uri, "root": tmp_path / "chat",
        }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        yield {**context, "client": client}


@pytest.mark.asyncio
@pytest.mark.parametrize("references", ["omitted", "empty", "mixed"])
async def test_multipart_upload_preserves_internal_references_and_uploaded_bytes(attachment_context, references):
    ctx = attachment_context
    identifier = str(uuid4())
    data = {"client_message_id": identifier, "text": "Synthetic attachments", "language": "en"}
    expected = [ctx["uri"]] if references == "mixed" else []
    if references != "omitted":
        data["resource_uris"] = json.dumps(expected)
    response = await ctx["client"].post(ctx["url"], headers=ctx["headers"], data=data,
        files={"files": ("external.txt", b"Synthetic external attachment", "text/plain")})
    assert response.status_code == 201, response.text
    message = response.json()
    assert message["resource_uris"] == expected
    assert message["text"] == data["text"]
    assert len(message["files"]) == 1 and message["files"][0]["name"] == "external.txt"
    async with get_db_session() as db:
        stored = await db.get(Message, UUID(message["id"]))
        assert stored is not None and stored.resource_uris == expected
        hydrated = (await journal.hydrate_messages([stored]))[0]
        assert len(hydrated.files) == 1
        assert await storage.read_bytes(hydrated.files[0].id) == b"Synthetic external attachment"
    reopened = await ctx["client"].get(f'/api/chat/rooms/{ctx["room_id"]}/messages', headers=ctx["headers"])
    assert reopened.status_code == 200, reopened.text
    assert any(item["id"] == message["id"] and item["resource_uris"] == expected
               and item["files"] == message["files"] for item in reopened.json()["items"])


@pytest.mark.asyncio
@pytest.mark.parametrize("references, status", [
    ("malformed", 422), ("object", 422), ("non_string", 422), ("too_many", 422), ("denied", 403),
])
async def test_invalid_internal_references_publish_nothing_and_store_no_upload(attachment_context, references, status):
    ctx = attachment_context
    identifier = str(uuid4())
    payload = {"malformed": "[", "object": "{}", "non_string": "[123]",
        "too_many": json.dumps([ctx["uri"]] * 21), "denied": json.dumps([ctx["denied_uri"]])}[references]
    response = await ctx["client"].post(ctx["url"], headers=ctx["headers"],
        data={"client_message_id": identifier, "resource_uris": payload},
        files={"files": ("external.txt", b"Synthetic external attachment", "text/plain")})
    assert response.status_code == status, response.text
    assert not ctx["root"].exists() or not list(ctx["root"].rglob("*"))
    async with get_db_session() as db:
        assert await db.scalar(select(Message).where(Message.remote_message_id == identifier)) is None
