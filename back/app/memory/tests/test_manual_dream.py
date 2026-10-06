"""Foreground Dream actions preserve ACLs and concurrent user edits."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent import AgentManagementScope
from app.dream import manual
from app.dream.models import DreamReceipt
from app.memory import MemoryConflictError, MemoryNotFoundError, MemoryPermissionError
from app.memory import service
from app.memory.facade import fill_attachment_description
from app.memory.models import MemoryRevision
from core.params import runtime_settings

from .test_dream_attachments import add_attachment


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["document", "human_document", "attachment"])
async def test_manual_thumbnail_replaces_existing_cache_and_preserves_it_on_failure(
    kind, db, agents, memory_storage, tmp_path, monkeypatch
):
    from PIL import Image
    from core.preview import thumbnails
    from app.memory import document_thumbnail_service as capture
    from app.memory.schemas import DocumentThumbnailRender, MemoryItemCreate, MemoryPayload

    owner = agents[0]
    owner_id, peer_id = owner.id, agents[1].id
    scope = AgentManagementScope(123, frozenset({owner_id}))
    monkeypatch.setattr(type(thumbnails.settings), "GALARIS_THUMBNAIL_ROOT", str(tmp_path / "cache"))
    monkeypatch.setattr(runtime_settings, "DREAM_ENABLED", False)
    blue = thumbnails.encode(Image.new("RGB", (80, 60), "blue"))
    red = thumbnails.encode(Image.new("RGB", (80, 60), "red"))
    snapshot = None
    if kind != "attachment":
        human_id = None
        if kind == "human_document":
            from core.user import HumanActor, UserModel
            human = UserModel(email=f"thumbnail-{uuid4()}@example.test", hashed_password="unused", is_active=True)
            db.add(human)
            await db.flush()
            human_id = human.id
            scope = AgentManagementScope(human_id, frozenset({owner_id}))
        item, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, node_kind="document", title="Synthetic illustrated document",
            memory_type="working", media_type="text/html", payload=MemoryPayload(text="<h1>Synthetic report</h1>"),
        ), owner_user_id=human_id)
        actor = owner_id
        if human_id is not None:
            from app.memory.schemas import MemoryGrantUpdate
            actor = HumanActor(human_id)
            await service.set_item_grant(item.id, owner_id, MemoryGrantUpdate(can_write=False), actor_agent_id=actor)
        await db.commit()
        identity = item.id
        snapshot = DocumentThumbnailRender(html="<h1>Synthetic report</h1>", revision=item.revision, lock_version=item.lock_version)
        renderer = AsyncMock(return_value=b"synthetic pdf")
        monkeypatch.setattr(capture, "render_html_pdf", renderer)
        monkeypatch.setattr(capture, "_printed_document_thumbnail", lambda _: renderer.image)
        renderer.image = blue
        async def read():
            return await capture.read_document_thumbnail(identity, snapshot, actor_agent_id=actor)
    else:
        source = await add_attachment(db, owner, "image")
        identity = source.item_id
        renderer = AsyncMock(return_value=blue)
        monkeypatch.setattr(capture, "render_file_thumbnail", renderer)
        async def read():
            return await capture.generate_document_attachment_thumbnail(source.document_id, source.attachment_id, actor_agent_id=owner_id)

    assert "thumbnail" in (await manual.available_actions(identity, owner_id, scope)).actions
    assert await read() == blue
    assert await read() == blue
    assert renderer.await_count == 1
    renderer.image = red
    if kind == "attachment":
        renderer.return_value = red
    result = await manual.run_action(identity, owner_id, "thumbnail", scope, snapshot=snapshot)
    assert result.result_count == 1
    assert renderer.await_count == 2
    assert await read() == red

    renderer.side_effect = RuntimeError("Synthetic renderer failure")
    with pytest.raises(RuntimeError):
        await manual.run_action(identity, owner_id, "thumbnail", scope, snapshot=snapshot)
    assert await read() == red
    receipts = list(await db.scalars(select(DreamReceipt).where(DreamReceipt.subject_id.startswith(f"{identity}:"))))
    assert sorted(receipt.status for receipt in receipts) == ["error", "success"]
    if snapshot is not None:
        snapshot.revision += 1
        with pytest.raises(MemoryConflictError):
            await manual.run_action(identity, owner_id, "thumbnail", scope, snapshot=snapshot)
    with pytest.raises((MemoryPermissionError, MemoryNotFoundError)):
        await manual.run_action(identity, peer_id, "thumbnail", scope, snapshot=snapshot)


@pytest.mark.asyncio
async def test_manual_checks_detect_suggestions_even_when_policies_are_off(
    db, agents, memory_storage, monkeypatch
):
    from app.memory.schemas import MemoryItemCreate, MemoryPayload
    from app.memory.models import MemoryFinding

    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=agents[0].id,
            title="Synthetic old fact",
            payload=MemoryPayload(text="<p>Synthetic old knowledge.</p>"),
        )
    )
    item.updated_at = datetime.now(timezone.utc) - timedelta(days=1000)
    await db.commit()
    for setting in ("MEMORY_AGING_MODE", "MEMORY_DUPLICATE_MODE", "MEMORY_CONTRADICTION_MODE"):
        monkeypatch.setattr(runtime_settings, setting, "off")
    result = await manual.run_action(
        item.id, agents[0].id, "findings", AgentManagementScope(123, None)
    )
    assert result.result_count >= 1
    finding = await db.scalar(select(MemoryFinding).where(MemoryFinding.primary_item_id == item.id))
    assert finding.kind == "aging" and finding.status == "pending"
    assert item.old_at is None
    assert runtime_settings.MEMORY_AGING_MODE == "off"


@pytest.mark.asyncio
async def test_manual_description_runs_when_dream_disabled_and_can_regenerate(
    db, agents, memory_storage, monkeypatch
):
    owner = agents[0]
    source = await add_attachment(db, owner, "image")
    scope = AgentManagementScope(user_id=123, agent_ids=frozenset({owner.id}))
    monkeypatch.setattr(runtime_settings, "DREAM_ENABLED", False)
    monkeypatch.setattr(runtime_settings, "DREAM_ATTACHMENT_IMAGE_ENABLED", False)
    analysis = AsyncMock(
        side_effect=["First synthetic description", "Second synthetic description"]
    )
    monkeypatch.setattr(manual, "analyze_attachment", analysis)
    assert (await manual.available_actions(source.item_id, owner.id, scope)).actions == [
        "describe",
        "thumbnail",
    ]
    first = await manual.run_action(source.item_id, owner.id, "describe", scope)
    second = await manual.run_action(source.item_id, owner.id, "describe", scope)
    assert first.result_count == second.result_count == 1
    assert first.receipt_id != second.receipt_id
    item, content, *_ = await service.get_item(source.item_id, agent_id=owner.id)
    assert item.revision == source.revision + 2
    assert "Second synthetic description" in content.decode()
    assert await db.scalar(
        select(MemoryRevision.id).where(
            MemoryRevision.item_id == item.id, MemoryRevision.revision == source.revision + 1
        )
    )
    receipts = list(
        await db.scalars(
            select(DreamReceipt).where(DreamReceipt.id.in_([first.receipt_id, second.receipt_id]))
        )
    )
    assert all(receipt.status == "success" for receipt in receipts)


@pytest.mark.asyncio
async def test_manual_description_rechecks_source_and_rejects_duplicate_calls(
    db, agents, memory_storage, monkeypatch
):
    owner = agents[0]
    source = await add_attachment(db, owner, "image")
    scope = AgentManagementScope(user_id=123, agent_ids=frozenset({owner.id}))

    async def analyze(*_args):
        with pytest.raises(MemoryConflictError):
            await manual.run_action(source.item_id, owner.id, "describe", scope)
        assert await fill_attachment_description(source, "Concurrent synthetic acquisition")
        return "Late synthetic description"

    monkeypatch.setattr(manual, "analyze_attachment", analyze)
    result = await manual.run_action(source.item_id, owner.id, "describe", scope)
    assert result.result_count == 0
    _, content, *_ = await service.get_item(source.item_id, agent_id=owner.id)
    assert "Concurrent synthetic acquisition" in content.decode()
    assert "Late synthetic description" not in content.decode()


@pytest.mark.asyncio
async def test_manual_description_denies_scope_and_read_only_sharing(
    db, agents, memory_storage, monkeypatch
):
    owner, peer = agents
    source = await add_attachment(db, owner, "image")
    analysis = AsyncMock()
    monkeypatch.setattr(manual, "analyze_attachment", analysis)
    with pytest.raises(MemoryNotFoundError):
        await manual.run_action(
            source.item_id, owner.id, "describe", AgentManagementScope(123, frozenset({peer.id}))
        )
    from app.memory.models import MemoryItemGrant

    db.add(MemoryItemGrant(item_id=source.document_id, agent_id=peer.id, can_write=False))
    await db.commit()
    with pytest.raises(MemoryPermissionError):
        await manual.run_action(
            source.item_id, peer.id, "describe", AgentManagementScope(123, None)
        )
    analysis.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_manual_failure_keeps_content_and_allows_retry(
    db, agents, memory_storage, monkeypatch, failure
):
    source = await add_attachment(db, agents[0], "image")
    scope = AgentManagementScope(123, None)
    monkeypatch.setattr(manual, "analyze_attachment", AsyncMock(side_effect=failure()))
    with pytest.raises(failure):
        await manual.run_action(source.item_id, agents[0].id, "describe", scope)
    _, content, *_ = await service.get_item(source.item_id, agent_id=agents[0].id)
    assert not content
    receipt = await db.scalar(
        select(DreamReceipt).where(DreamReceipt.subject_id.startswith(f"{source.item_id}:"))
    )
    assert receipt.status == "error" and receipt.lease_expires_at is None
    monkeypatch.setattr(
        manual, "analyze_attachment", AsyncMock(return_value="Recovered synthetic description")
    )
    assert (
        await manual.run_action(source.item_id, agents[0].id, "describe", scope)
    ).result_count == 1


@pytest.mark.asyncio
async def test_manual_dream_http_requires_edit_privilege_and_hides_unknown_agents(
    client, memory_storage
):
    item_id = uuid4()
    path = f"/api/dream/memory/{item_id}/actions"
    assert (await client.get(path, params={"agent_id": 1})).status_code == 401
    credentials = {"email": "dream-admin@example.com", "password": "Synthetic-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    admin = {
        "Authorization": "Bearer " + login.json()["access_token"],
        "X-Editorial-Profile-Version": "1",
    }
    agents = (await client.get("/api/agents/selection", headers=admin)).json()
    agent_id = agents[0]["id"]
    created = await client.post(
        "/api/memory/items",
        headers=admin,
        json={
            "owner_agent_id": agent_id,
            "title": "Synthetic Dream memory",
            "payload": {"text": "<p>Synthetic fact.</p>"},
        },
    )
    assert created.status_code == 201, created.text
    path = f"/api/dream/memory/{created.json()['id']}/actions"
    assert (await client.get(path, headers=admin, params={"agent_id": agent_id})).json() == {
        "actions": ["findings"]
    }
    result = await client.post(path + "/findings", headers=admin, params={"agent_id": agent_id})
    assert result.status_code == 200, result.text
    assert (
        await client.post(path + "/describe", headers=admin, params={"agent_id": agent_id})
    ).status_code == 422
    assert (
        await client.get(path, headers=admin, params={"agent_id": 2147483647})
    ).status_code == 404
    credentials = {"email": "dream-reader@example.com", "password": "Synthetic-password-123"}
    await client.post("/api/auth/users", headers=admin, json=credentials)
    client.cookies.clear()
    login = await client.post("/api/auth/login-json", json=credentials)
    reader = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert (
        await client.get(path, headers=reader, params={"agent_id": agent_id})
    ).status_code == 403
    assert (
        await client.post(path + "/findings", headers=reader, params={"agent_id": agent_id})
    ).status_code == 403
