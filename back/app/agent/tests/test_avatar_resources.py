"""Agent portraits are live, authorized binary resources, without duplicate storage."""

import base64
import io
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from PIL import Image

from app.agent import agent_service, tools
from app.agent.avatars import normalize_avatar
from app.agent.models import Agent, Title
from app.file_share import ResourceContext, materialize_resource, resource_info, resource_read
from app.file_share.resource_service import resource_copy, resource_list, resource_search
from core.user import UserModel


def portrait(color):
    output = io.BytesIO()
    Image.new("RGB", (24, 32), color).save(output, "PNG")
    return normalize_avatar(output.getvalue())


@pytest_asyncio.fixture
async def directory(db):
    owner = UserModel(email=f"portraits-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
    title = Title(label="Synthetic portrait", gender="F")
    db.add_all([owner, title])
    await db.flush()
    agents = [Agent(user_id=owner.id, title_id=title.id, code=f"portrait-{uuid4().hex}",
                    first_name=f"Synthetic {index}", last_name="Portrait", agent_driver="internal",
                    personality="<p>Synthetic personality</p>", job_description="<p>Synthetic mission</p>")
              for index in range(3)]
    agents[1].avatar = portrait("blue")
    db.add_all(agents)
    await db.flush()
    return agents


@pytest.mark.asyncio
async def test_peer_portrait_discovery_and_binary_transports(db, directory, tmp_path):
    caller, peer, no_photo = directory
    expected = peer.avatar
    ctx = ResourceContext(agent_id=caller.id, runtime="internal")
    profile_uri = f"galaris://agent/{peer.id}"
    uri = profile_uri + "/avatar"
    profile = json.loads((await resource_read(ctx, profile_uri)).content)
    assert profile["avatar_uri"] == uri
    assert profile["personality"] == peer.personality
    assert uri in await tools.get_agent_details(peer.id, language="en")
    page = json.loads(await tools.list_agents())
    assert next(item for item in page["items"] if item["id"] == peer.id)["avatar_uri"] == uri
    assert next(item for item in page["items"] if item["id"] == no_photo.id)["avatar_uri"] is None
    listing = await resource_list(ctx, "galaris://agent/")
    assert profile_uri in [item.uri for item in listing.entries]
    assert profile_uri in [hit.resource.uri for hit in (await resource_search(ctx, "galaris://agent/", "Synthetic 1")).hits]

    info = await resource_info(ctx, uri)
    assert info.media_type == "image/jpeg" and info.size == len(expected)
    assert info.name.endswith(".jpg") and info.capabilities == ["copy", "info", "read"]
    read = await resource_read(ctx, uri)
    assert read.encoding == "base64" and read.media_type == "image/jpeg"
    assert base64.b64decode(read.content) == expected
    target = tmp_path / "portrait"
    result = await materialize_resource(ctx, uri, target, max_bytes=100_000)
    assert result.uri == uri and result.media_type == "image/jpeg"
    assert target.read_bytes() == expected
    copied = await resource_copy(ctx, uri, "file://")
    assert copied.size == len(expected)
    assert base64.b64decode((await resource_read(ctx, copied.uri)).content) == expected
    # Generic writes must never replace another profile's photo.
    with pytest.raises(PermissionError):
        await resource_copy(ctx, uri, f"galaris://agent/{caller.id}/avatar")


@pytest.mark.asyncio
async def test_image_tool_consumes_peer_photo_and_persists_description(db, directory, monkeypatch):
    from app.image import mcp as image_mcp
    from app.memory.models import MemoryItem
    from app.tools.mcp_loader import McpToolContext
    from sqlalchemy import select

    caller, peer, _ = directory
    expected = peer.avatar
    uri = f"galaris://agent/{peer.id}/avatar"
    observed = []

    async def describe(content, media_type, **kwargs):
        observed.append((content, media_type, kwargs["agent_id"]))
        return "Synthetic blue portrait."

    # Only replace the paid external model boundary; keep resource resolution,
    # materialization and private description persistence real.
    monkeypatch.setattr(image_mcp.image_service, "describe_image", describe)
    assert await image_mcp.describe_image(McpToolContext(caller.id, "internal"), uri) == "Synthetic blue portrait."
    assert observed == [(expected, "image/jpeg", caller.id)]
    descriptions = list(await db.scalars(select(MemoryItem).where(
        MemoryItem.owner_agent_id == caller.id, MemoryItem.managed_source_kind == "image_description")))
    assert len(descriptions) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("format,media_type", [("PNG", "image/png"), ("GIF", "image/gif"), ("WEBP", "image/webp")])
async def test_legacy_portraits_keep_their_actual_image_type(db, directory, tmp_path, format, media_type):
    caller, peer, _ = directory
    output = io.BytesIO()
    Image.new("RGB", (24, 32), "blue").save(output, format)
    expected = output.getvalue()
    peer.avatar = expected
    await db.flush()
    ctx = ResourceContext(agent_id=caller.id, runtime="internal")
    uri = f"galaris://agent/{peer.id}/avatar"
    assert (await resource_info(ctx, uri)).media_type == media_type
    read = await resource_read(ctx, uri)
    assert read.media_type == media_type and base64.b64decode(read.content) == expected
    result = await materialize_resource(ctx, uri, tmp_path / "legacy", max_bytes=100_000)
    assert result.media_type == media_type and (tmp_path / "legacy").read_bytes() == expected


@pytest.mark.asyncio
async def test_large_legacy_portrait_uses_bounded_materialization(db, directory, tmp_path):
    caller, peer, _ = directory
    output = io.BytesIO()
    Image.new("RGB", (700, 700), "blue").save(output, "PNG", compress_level=0)
    expected = output.getvalue()
    assert len(expected) > 1_048_576
    peer.avatar = expected
    await db.flush()
    ctx = ResourceContext(agent_id=caller.id, runtime="internal")
    uri = f"galaris://agent/{peer.id}/avatar"
    with pytest.raises(ValueError, match="specialized"):
        await resource_read(ctx, uri)
    result = await materialize_resource(ctx, uri, tmp_path / "large", max_bytes=len(expected))
    assert result.size == len(expected) and (tmp_path / "large").read_bytes() == expected


@pytest.mark.asyncio
async def test_portraits_follow_current_profile_access_and_deletion(db, directory, tmp_path):
    caller, peer, no_photo = directory
    ctx = ResourceContext(agent_id=caller.id, runtime="internal")
    uri = f"galaris://agent/{peer.id}/avatar"
    original = (await resource_read(ctx, uri)).content
    await agent_service.update_avatar(peer.id, portrait("red"))
    assert (await resource_read(ctx, uri)).content != original
    with pytest.raises(ValueError, match="limit"):
        await materialize_resource(ctx, uri, tmp_path / "too-small", max_bytes=1)
    assert not (tmp_path / "too-small").exists()
    for unavailable in [f"galaris://agent/{no_photo.id}/avatar", "galaris://agent/2147483647/avatar"]:
        with pytest.raises(FileNotFoundError):
            await resource_info(ctx, unavailable)
    for actor in [2147483647, no_photo.id]:
        if actor == no_photo.id:
            no_photo.deleted_at = datetime.now(timezone.utc)
            await db.flush()
        denied = ResourceContext(agent_id=actor, runtime="internal")
        for hidden_uri in [f"galaris://agent/{peer.id}", uri]:
            with pytest.raises(FileNotFoundError):
                await resource_read(denied, hidden_uri)
        with pytest.raises(FileNotFoundError):
            await materialize_resource(denied, uri, tmp_path / "denied", max_bytes=100_000)
        assert not (tmp_path / "denied").exists()
    await agent_service.delete_avatar(peer.id)
    assert json.loads((await resource_read(ctx, f"galaris://agent/{peer.id}")).content)["avatar_uri"] is None
    with pytest.raises(FileNotFoundError):
        await resource_read(ctx, uri)
    await agent_service.update_avatar(peer.id, portrait("blue"))
    peer.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    for hidden_uri in [f"galaris://agent/{peer.id}", uri]:
        with pytest.raises(FileNotFoundError):
            await resource_info(ctx, hidden_uri)
