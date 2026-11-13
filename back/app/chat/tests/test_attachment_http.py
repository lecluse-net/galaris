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
            "agent_id": agent.id,
            "room_id": room.id, "connection_id": room.connection_id, "room_external_id": room.external_id,
            "headers": {"Authorization": f"Bearer {token}"}, "uri": source.uri,
            "denied_uri": denied.uri, "root": tmp_path / "chat",
        }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        yield {**context, "client": client}


@pytest.mark.asyncio
@pytest.mark.parametrize("references", ["omitted", "empty", "mixed"])
@pytest.mark.parametrize("file_count", [1, 3])
async def test_multipart_upload_preserves_internal_references_and_uploaded_bytes(attachment_context, references, file_count):
    ctx = attachment_context
    identifier = str(uuid4())
    data = {"client_message_id": identifier, "text": "Synthetic attachments", "language": "en"}
    expected = [ctx["uri"]] if references == "mixed" else []
    if references != "omitted":
        data["resource_uris"] = json.dumps(expected)
    uploads = [(f"external-{index}.txt", f"Synthetic external attachment {index}".encode(), "text/plain")
               for index in range(file_count)]
    response = await ctx["client"].post(ctx["url"], headers=ctx["headers"], data=data,
        files=[("files", upload) for upload in uploads])
    assert response.status_code == 201, response.text
    message = response.json()
    assert message["resource_uris"] == expected
    assert message["text"] == data["text"]
    assert [file["name"] for file in message["files"]] == [upload[0] for upload in uploads]
    async with get_db_session() as db:
        stored = await db.get(Message, UUID(message["id"]))
        assert stored is not None and stored.resource_uris == expected
        hydrated = (await journal.hydrate_messages([stored]))[0]
        assert len(hydrated.files) == file_count
        from app.agent.contracts import TaskMessage
        from app.agent.conversation_context import message_prompt
        from app.file_share import resource_read

        current = TaskMessage.from_messenger(hydrated)
        prompt = message_prompt(current)
        by_name = {file.name: file for file in current.attachments}
        for name, content, _mime in uploads:
            attachment = by_name[name]
            assert attachment.uri in prompt
            assert await storage.read_bytes(attachment.id) == content
            read = await resource_read(ResourceContext(ctx["agent_id"], "internal"), attachment.uri)
            assert read.content == content.decode()
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


@pytest.mark.asyncio
async def test_process_completion_attaches_real_resources_to_the_chat_reply(attachment_context):
    from app.connection import Connection
    from app.conversation.models import ConversationRound, ConversationProcessLink
    from app.conversation.service import claim_next_process_notification, deliver_process_notification
    from app.process import ProcessDefinition, ProcessRun

    ctx = attachment_context
    async with get_db_session() as db:
        document = await resource_create(ResourceContext(ctx["agent_id"], "internal"),
            "document://", "<p>Synthetic process report</p>".encode(), name="Process report")
        connection = await db.get(Connection, ctx["connection_id"])
        definition = ProcessDefinition(agent_id=ctx["agent_id"], tool_id=connection.tool_id,
            engine_process_id=uuid4().hex, label="Synthetic report")
        round_ = ConversationRound(room_id=ctx["room_id"], status="SUCCEEDED", delivery_state="DELIVERED", language="en")
        db.add_all([definition, round_])
        await db.flush()
        run = ProcessRun(process_id=definition.id, launcher_agent_id=ctx["agent_id"],
            engine_code="galaris", correlation_id=uuid4().hex, callback_token=uuid4().hex,
            status="success", input={}, engine_metadata={"native": {"summary": "Report ready."}},
            launch_snapshot={"process_label": definition.label, "definition": {"graph": {"schema_version": "galaris.bpmn/v2"}}},
            output={"count": {"type": "int", "value": 0},
                "file": {"type": "File", "value": ctx["uri"]},
                "report": {"type": "Document", "value": document.uri},
                "private": {"type": "File", "value": ctx["denied_uri"]}})
        db.add(run)
        await db.flush()
        link = ConversationProcessLink(round_id=round_.id, process_run_id=run.id, action_key="completed")
        db.add(link)
        await db.commit()
        assert await claim_next_process_notification() == link.id
        await deliver_process_notification(link.id)
        await db.refresh(link)
        message_id = str(link.notification_message_id)
        assert link.notification_state == "DELIVERED"
        assert await claim_next_process_notification() is None

    base = f'/api/chat/rooms/{ctx["room_id"]}/messages'
    reopened = await ctx["client"].get(base, headers=ctx["headers"])
    assert reopened.status_code == 200, reopened.text
    message = next(item for item in reopened.json()["items"] if item["id"] == message_id)
    assert message["resource_uris"] == [ctx["uri"], document.uri]
    assert "Report ready." in message["text"] and "count : 0" in message["text"]
    assert "private : Attachment unavailable" in message["text"]
    previews = await ctx["client"].get(f"{base}/{message_id}/previews", headers=ctx["headers"])
    assert previews.status_code == 200, previews.text
    assert {item["uri"] for item in previews.json()} == {ctx["uri"], document.uri}
    download = await ctx["client"].get(f"{base}/{message_id}/previews/content",
        headers=ctx["headers"], params={"uri": ctx["uri"]})
    assert download.status_code == 200, download.text
    assert download.content == b"Synthetic internal attachment"
    denied = await ctx["client"].get(f"{base}/{message_id}/previews/content",
        headers=ctx["headers"], params={"uri": ctx["denied_uri"]})
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_draft_survives_requests_and_publishes_preuploaded_files_once(attachment_context):
    ctx = attachment_context
    client, headers = ctx['client'], ctx['headers']
    base = f"/api/chat/rooms/{ctx['room_id']}"
    key, message_key, mutation = str(uuid4()), str(uuid4()), str(uuid4())
    uploaded = await client.post(f'{base}/draft/files/{key}', headers=headers,
        files={'file': ('draft.txt', b'Synthetic unsent attachment', 'text/plain')})
    assert uploaded.status_code == 200, uploaded.text
    repeated = await client.post(f'{base}/draft/files/{key}', headers=headers,
        files={'file': ('draft.txt', b'Synthetic unsent attachment', 'text/plain')})
    assert repeated.json() == uploaded.json()
    content = {'client_message_id': message_key, 'text': 'Synthetic unsent text',
               'files': [uploaded.json()], 'resources': [], 'effort': 2}
    save = {'expected_revision': 0, 'mutation_key': mutation, 'content': content}
    saved = await client.put(f'{base}/draft', headers=headers, json=save)
    assert saved.status_code == 200, saved.text
    revision = saved.json()['revision']
    assert (await client.put(f'{base}/draft', headers=headers, json=save)).json() == saved.json()
    restored = await client.get(f'{base}/draft', headers=headers)
    assert restored.json()['content']['text'] == content['text']
    assert restored.json()['content']['files'] == [uploaded.json()]
    stale = await client.put(f'{base}/draft', headers=headers,
        json={**save, 'mutation_key': str(uuid4())})
    assert stale.status_code == 409
    body = {'client_message_id': message_key, 'text': content['text'], 'draft_revision': revision}
    sent = await client.post(f'{base}/messages', headers=headers, json=body)
    assert sent.status_code == 201, sent.text
    assert len(sent.json()['files']) == 1
    assert sent.json()['files'][0]['name'] == 'draft.txt'
    file_id = sent.json()['files'][0]['id']
    assert (await client.get(f'{base}/files/{file_id}', headers=headers)).content == b'Synthetic unsent attachment'
    assert (await client.get(f'{base}/draft', headers=headers)).json() == {'revision': revision + 1, 'content': None}
    retry = await client.post(f'{base}/messages', headers=headers, json=body)
    assert retry.status_code == 201, retry.text
    assert retry.json()['id'] == sent.json()['id']
    assert len(retry.json()['files']) == 1
    assert (await client.put(f'{base}/draft', headers=headers, json=save)).status_code == 409


@pytest.mark.asyncio
async def test_draft_access_is_private_and_send_failure_keeps_snapshot(attachment_context):
    from core.user import UserModel
    ctx = attachment_context
    client, headers = ctx['client'], ctx['headers']
    base = f"/api/chat/rooms/{ctx['room_id']}"
    content = {'client_message_id': str(uuid4()), 'text': 'Synthetic private draft', 'files': []}
    saved = await client.put(f'{base}/draft', headers=headers,
        json={'expected_revision': 0, 'mutation_key': str(uuid4()), 'content': content})
    assert saved.status_code == 200, saved.text
    # Invalid reply is rejected by the real publication path, without clearing autosave.
    failed = await client.post(f'{base}/messages', headers=headers, json={
        'client_message_id': content['client_message_id'], 'draft_revision': saved.json()['revision'],
        'text': content['text'], 'reply_to_message_id': str(uuid4()),
    })
    assert failed.status_code == 422
    assert (await client.get(f'{base}/draft', headers=headers)).json() == saved.json()
    async with get_db_session() as db:
        other = UserModel(email=f'draft-outsider-{uuid4().hex}@example.test', display_name='Synthetic outsider',
            hashed_password='unused', is_active=True)
        db.add(other)
        await db.flush()
        token = create_access_token({'sub': other.email, 'user_id': other.id})
    denied = {'Authorization': f'Bearer {token}'}
    for method in ('get', 'put'):
        kwargs = {'json': {'expected_revision': 0, 'mutation_key': str(uuid4()), 'content': content}} if method == 'put' else {}
        response = await getattr(client, method)(f'{base}/draft', headers=denied, **kwargs)
        assert response.status_code == 403
    response = await client.post(f'{base}/draft/files/{uuid4()}', headers=denied,
        files={'file': ('private.txt', b'Synthetic private bytes', 'text/plain')})
    assert response.status_code == 403
    assert (await client.get(f'{base}/draft', headers=headers)).json() == saved.json()


@pytest.mark.asyncio
async def test_sent_revision_does_not_erase_newer_draft_and_removed_files_are_retired(attachment_context):
    from app.chat.draft_service import clear_sent_draft, read_draft
    from core.storage import StoredFile
    from app.chat.models import ChatDraftFile
    ctx = attachment_context
    client, headers = ctx['client'], ctx['headers']
    base = f"/api/chat/rooms/{ctx['room_id']}"
    key = str(uuid4())
    uploaded = await client.post(f'{base}/draft/files/{key}', headers=headers,
        files={'file': ('removed.txt', b'Synthetic removed bytes', 'text/plain')})
    assert uploaded.status_code == 200, uploaded.text
    content = {'client_message_id': str(uuid4()), 'text': 'First draft', 'files': [uploaded.json()]}
    first = await client.put(f'{base}/draft', headers=headers,
        json={'expected_revision': 0, 'mutation_key': str(uuid4()), 'content': content})
    assert first.status_code == 200, first.text
    async with get_db_session() as db:
        from app.chat.models import ChatDraft
        row = await db.scalar(select(ChatDraft).where(ChatDraft.room_id == ctx['room_id']))
        # Keep the first revision in this session's identity map while another
        # request commits a newer snapshot. A lock alone must not reuse stale ORM state.
        second = await client.put(f'{base}/draft', headers=headers, json={
            'expected_revision': first.json()['revision'], 'mutation_key': str(uuid4()),
            'content': {**content, 'text': 'More recent draft', 'files': []},
        })
        assert second.status_code == 200, second.text
        await clear_sent_draft(row.user_id, ctx['room_id'], first.json()['revision'])
        assert (await read_draft(row.user_id, ctx['room_id'])).content.text == 'More recent draft'
        assert await db.get(ChatDraftFile, UUID(key)) is None
        # The common storage lifecycle retired the unreferenced immutable file.
        files = list(await db.scalars(select(StoredFile).where(StoredFile.name == 'removed.txt')
            .execution_options(include_historized=True)))
        assert len(files) == 1 and files[0].deleted_at is not None


@pytest.mark.asyncio
async def test_drafts_are_unique_and_isolated_by_user_and_room(attachment_context):
    import asyncio
    from app.chat.draft_service import DraftContent, DraftWrite, read_draft, write_draft
    from app.chat.models import ChatDraft
    ctx = attachment_context
    base = f"/api/chat/rooms/{ctx['room_id']}"
    content = {'client_message_id': str(uuid4()), 'text': 'Concurrent draft'}
    responses = await asyncio.gather(*(ctx['client'].put(f'{base}/draft', headers=ctx['headers'],
        json={'expected_revision': 0, 'mutation_key': str(uuid4()), 'content': content}) for _ in range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    async with get_db_session() as db:
        first = await db.scalar(select(ChatDraft).where(ChatDraft.room_id == ctx['room_id']))
        _, second_user, _ = await _scope(db)
        await write_draft(second_user.id, ctx['room_id'], DraftWrite(expected_revision=0, mutation_key=uuid4(),
            content=DraftContent(client_message_id=uuid4(), text='Other user draft')))
        assert (await read_draft(first.user_id, ctx['room_id'])).content.text == 'Concurrent draft'
        assert (await read_draft(second_user.id, ctx['room_id'])).content.text == 'Other user draft'
        assert (await read_draft(second_user.id, uuid4())).content is None
        assert len(list(await db.scalars(select(ChatDraft).where(ChatDraft.room_id == ctx['room_id'])))) == 2
