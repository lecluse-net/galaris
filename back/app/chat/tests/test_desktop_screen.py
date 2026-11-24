"""A Chat turn can consume only an explicitly completed capture from its source tab."""

import asyncio
from dataclasses import replace
from io import BytesIO
from secrets import token_urlsafe
from uuid import UUID, uuid4

from fastmcp import Client
from PIL import Image
import pytest
from sqlalchemy import select

from app.chat.desktop_screen import SCREEN_HEADER
from app.chat.models import ChatDesktopScreenRequest
from app.conversation.service import build_turn, claim_next_round
from app.file_share import ResourceContext, resource_list
from app.messenger.contracts import CHAT_SCREEN_SOURCE_KEY
from app.messenger.models import Message
from app.services.mcp_loader import build_agent_galaris_fastmcp, list_enabled_native_mcp_definitions
from core.database import get_db_session
from core.user.auth_service import create_access_token
from core.user.models import UserRefreshSession
from core.user.refresh_session_service import create_refresh_session

from .test_attachment_http import attachment_context as attachment_context


ROOT = "/api/chat/desktop-screen"


async def web_headers(ctx: dict, key: str) -> dict[str, str]:
    async with get_db_session() as db:
        await create_refresh_session(ctx["user_id"])
        family = await db.scalar(select(UserRefreshSession.family_id).where(
            UserRefreshSession.user_id == ctx["user_id"],
        ).order_by(UserRefreshSession.id.desc()).limit(1))
    token = create_access_token({"sub": ctx["user_email"], "user_id": ctx["user_id"],
                                 "role_id": ctx["role_id"], "session_family": family})
    return {"Authorization": f"Bearer {token}", SCREEN_HEADER: key}


@pytest.mark.asyncio
async def test_header_without_a_live_client_does_not_grant_capture(attachment_context):
    ctx = attachment_context
    headers = await web_headers(ctx, token_urlsafe(32))
    response = await ctx["client"].post(ctx["url"].replace("/attachments", "/messages"), headers=headers,
        json={"text": "Synthetic browser-only message", "client_message_id": str(uuid4())})
    assert response.status_code == 201, response.text
    async with get_db_session() as db:
        message = await db.get(Message, UUID(response.json()["id"]))
        assert message is not None and CHAT_SCREEN_SOURCE_KEY not in message.metadata_


@pytest.mark.asyncio
async def test_capture_from_the_originating_tab_becomes_an_attachable_private_file(attachment_context):
    ctx = attachment_context
    client = ctx["client"]
    key = token_urlsafe(32)
    desktop = await web_headers(ctx, key)
    another_login = await web_headers(ctx, key)
    another_tab = {**desktop, SCREEN_HEADER: token_urlsafe(32)}
    assert (await client.post(ROOT + "/poll?initialize=true", headers={**ctx["headers"], SCREEN_HEADER: key})).status_code == 403
    for headers in (desktop, another_login, another_tab):
        assert (await client.post(ROOT + "/poll?initialize=true", headers=headers)).status_code == 200
    sent = await client.post(ctx["url"].replace("/attachments", "/messages"), headers=desktop,
        json={"text": "Inspect this synthetic screen", "client_message_id": str(uuid4())})
    assert sent.status_code == 201, sent.text
    async with get_db_session():
        claimed = await claim_next_round("synthetic-screen-worker")
        assert claimed is not None and claimed.lease_token is not None
        turn = await build_turn(claimed.id, lease_token=claimed.lease_token)
        assert turn.desktop_screen_session is not None
    photo = BytesIO()
    Image.new("RGB", (32, 24), "#008080").save(photo, format="JPEG")
    resources = {"conversation_turn": turn}
    async with get_db_session():
        owner = ResourceContext(ctx["agent_id"], "internal")
        initial = {entry.uri for entry in (await resource_list(owner, "file://")).entries}
        assert not await list_enabled_native_mcp_definitions(ctx["agent_id"], runtime="internal",
            resources=resources, allowed_tool_names={"chat_screenshot"}, task_id=uuid4())
        assert not await list_enabled_native_mcp_definitions(ctx["agent_id"], runtime="internal",
            resources={"conversation_turn": replace(turn, desktop_screen_session=None)},
            allowed_tool_names={"chat_screenshot"}, conversation_only=True)
        server = await build_agent_galaris_fastmcp(ctx["agent_id"], runtime="internal",
            resources=resources, allowed_tool_names={"chat_screenshot"}, conversation_only=True)
    async with Client(server) as tools:
        assert [tool.name for tool in await tools.list_tools()] == ["chat_screenshot"]
        async with asyncio.timeout(12), asyncio.TaskGroup() as group:
            pending = group.create_task(tools.call_tool("chat_screenshot", {"reason": "Check the synthetic color"}))
            delivery = (await client.post(ROOT + "/poll", headers=desktop)).json()
            assert delivery["reason"] == "Check the synthetic color"
            endpoint = f'{ROOT}/{delivery["id"]}/complete'
            for foreign in (another_login, another_tab):
                assert (await client.post(endpoint, headers={**foreign, "Content-Type": "image/jpeg"},
                    content=photo.getvalue())).status_code == 404
            assert (await client.post(endpoint, headers={**desktop, "Content-Type": "image/jpeg"},
                content=b"invalid JPEG")).status_code == 415
            assert (await client.post(endpoint, headers={**desktop, "Content-Type": "image/jpeg"},
                content=photo.getvalue())).status_code == 204
        outcome = pending.result()
        async with asyncio.timeout(12), asyncio.TaskGroup() as group:
            declined = group.create_task(tools.call_tool("chat_screenshot", {"reason": "Synthetic decline"},
                raise_on_error=False))
            delivery = (await client.post(ROOT + "/poll", headers=desktop)).json()
            assert (await client.post(f'{ROOT}/{delivery["id"]}/complete', headers=desktop)).status_code == 204
        assert declined.result().is_error
    assert outcome.structured_content is not None
    receipt = outcome.structured_content
    assert receipt["media_type"] == "image/jpeg" and receipt["name"].endswith(".jpg")
    uri = receipt["uri"]
    assert uri.startswith("file://")
    file_id = UUID(uri.removeprefix("file://"))
    url = f"/api/file-share/files/{file_id}/content"
    fetched = await client.get(url, headers=desktop, params={"agent_id": ctx["agent_id"]})
    assert fetched.status_code == 200 and fetched.content == photo.getvalue()
    assert fetched.headers["content-type"] == "image/jpeg"
    assert (await client.get(url, headers=desktop, params={"agent_id": ctx["other_agent_id"]})).status_code == 404
    assert (await client.post(endpoint, headers=desktop)).status_code == 404
    assert (await client.delete(ROOT, headers=desktop)).status_code == 204
    async with get_db_session() as db:
        assert await db.scalar(select(ChatDesktopScreenRequest.id)) is None
        assert {entry.uri for entry in (await resource_list(owner, "file://")).entries} == initial | {uri}
        assert not await list_enabled_native_mcp_definitions(ctx["agent_id"], runtime="internal",
            resources=resources, allowed_tool_names={"chat_screenshot"}, conversation_only=True)
    attachment = await client.post(ctx["url"].replace("/attachments", "/messages"), headers=ctx["headers"],
        json={"text": "Synthetic screenshot as an attachment", "resource_uris": [uri], "client_message_id": str(uuid4())})
    assert attachment.status_code == 201, attachment.text
    assert attachment.json()["resource_uris"] == [uri]
