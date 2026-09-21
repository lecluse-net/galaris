from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent
from app.file_share.resource_contracts import ResourceContext
from app.file_share import resource_service
from app.memory import MessengerContactObservation, mcp, observe_messenger_contact, service
from app.memory.models import (
    MemoryContactItem,
    MemoryItem,
    MemoryRevision,
    MemorySource,
)
from app.messenger.models import Message, Room, MessengerUser
from app.task.models import Task, TaskStatus
from app.tools.mcp_loader import (
    McpToolContext,
    load_mcp_tools,
    mcp_tool_names_by_tool_code,
)


def test_memory_mcp_family_is_discovered_once() -> None:
    names = mcp_tool_names_by_tool_code()
    expected = {
        "memory_remember",
        "memory_forget",
        "memory_summarize",
        "document_share",
        "memory_sharing",
        "memory_share",
    }
    assert set(names["memory"]) == expected
    assert "document_show" in names["conversation"]
    assert {
        "memory_search",
        "memory_get",
        "memory_index",
        "document_read",
        "document_append",
    }.isdisjoint(names["memory"])
    all_names = [definition.name for definition in load_mcp_tools()]
    assert all(all_names.count(name) == 1 for name in expected)
    assert "full_search" not in inspect.signature(mcp.memory_search).parameters


def test_memory_remember_description_preserves_storage_contract() -> None:
    definition = next(
        item for item in load_mcp_tools() if item.name == "memory_remember"
    )

    assert "Store one durable governed memory" in definition.description
    assert "do not wait for an explicit request" not in definition.description


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["internal", "hermes"])
async def test_sharing_tools_expose_team_and_human_targets_without_breaking_agent_calls(runtime):
    from app.tools.mcp_loader import build_galaris_fastmcp

    server = build_galaris_fastmcp(1, runtime=runtime, enabled_tool_codes={"memory"})
    tools = {tool.name: tool for tool in await server.list_tools()}
    for name in ("document_share", "memory_share"):
        parameters = tools[name].parameters
        assert {"agent_id", "team_id", "user_id", "access", "expected_lock_version"} <= parameters["properties"].keys()
        assert "agent_id" not in parameters.get("required", [])
    assert {"memory_id", "kind", "search", "offset", "limit"} <= tools["memory_sharing"].parameters["properties"].keys()


@pytest.mark.asyncio
async def test_memory_remember_schema_accepts_json_encoded_keywords() -> None:
    from app.tools.mcp_loader import build_galaris_fastmcp

    server = build_galaris_fastmcp(
        1,
        runtime="internal",
        enabled_tool_codes={"memory"},
    )
    tools = {tool.name: tool for tool in await server.list_tools()}

    keyword_schema = tools["memory_remember"].parameters["properties"]["keywords"]
    assert "reason" not in tools["memory_remember"].parameters["properties"]
    accepted_types = {
        variant.get("type") for variant in keyword_schema["anyOf"]
    }
    assert {"array", "string", "null"} <= accepted_types


@pytest.mark.asyncio
async def test_memory_remember_normalizes_json_encoded_keywords(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents

    result = json.loads(
        await mcp.memory_remember(
            McpToolContext(agent_id=owner.id, runtime="internal"),
            content="Deux capteurs équipent le robot Lyra : température et pression.",
            title="Capteurs du robot Lyra",
            keywords='["Lyra", "température", "pression"]',
        )
    )

    memory = await db.get(MemoryItem, UUID(str(result["memory_id"])))
    assert memory is not None
    assert memory.keywords == ["Lyra", "température", "pression"]


@pytest.mark.asyncio
async def test_memory_remember_seals_identical_facts_to_the_exact_contact(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    alice_contact = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@alice-mcp:example.test",
            display_name="Alice",
        )
    )
    bob_contact = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@bob-mcp:example.test",
            display_name="Bob",
        )
    )
    alice_task = Task(
        label="Conversation with Alice",
        status=TaskStatus.EXEC,
        agent_id=owner.id,
        contact_memory_item_id=alice_contact,
    )
    bob_task = Task(
        label="Conversation with Bob",
        status=TaskStatus.EXEC,
        agent_id=owner.id,
        contact_memory_item_id=bob_contact,
    )
    db.add_all([alice_task, bob_task])
    await db.flush()

    async def remember(task: Task) -> dict[str, object]:
        return json.loads(
            await mcp.memory_remember(
                McpToolContext(
                    agent_id=owner.id,
                    runtime="internal",
                    task_id=task.id,
                ),
                content="La personne est à la plage.",
                title="Localisation déclarée",
            )
        )

    alice_memory = await remember(alice_task)
    bob_memory = await remember(bob_task)

    assert alice_memory["memory_id"] != bob_memory["memory_id"]
    memberships = list((await db.scalars(select(MemoryContactItem))).all())
    assert {
        (membership.item_id, membership.contact_item_id)
        for membership in memberships
    } >= {
        (UUID(str(alice_memory["memory_id"])), alice_contact),
        (UUID(str(bob_memory["memory_id"])), bob_contact),
    }

    alice_search = json.loads(
        await mcp.memory_search(
            McpToolContext(
                agent_id=owner.id,
                runtime="internal",
                task_id=alice_task.id,
            ),
            "plage",
        )
    )
    assert [memory["memory_id"] for memory in alice_search["memories"]] == [
        alice_memory["memory_id"]
    ]


@pytest.mark.asyncio
async def test_memory_mcp_index_search_get_and_store(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    start = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)
    previous_task = Task(
        label="Previous conversation subject",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        created_at=start,
        message_platform="nextcloud_talk",
        message_group_id="room-1",
        data={"message_id": "message-previous"},
    )
    task = Task(
        label="Current conversation subject",
        status=TaskStatus.EXEC,
        agent_id=owner.id,
        created_at=start + timedelta(minutes=1),
        message_platform="nextcloud_talk",
        message_group_id="room-1",
        data={"message_id": "message-current"},
    )
    db.add_all([previous_task, task])
    await db.flush()
    previous_ctx = McpToolContext(
        agent_id=owner.id,
        runtime="internal",
        task_id=previous_task.id,
    )
    previous_memory = json.loads(
        await mcp.memory_remember(
            previous_ctx,
            content="The previous turn established the deployment baseline.",
            title="Previous deployment baseline",
        )
    )
    assert previous_memory["task_associated"] is True
    assert previous_memory["links_created"] == 0
    assert previous_memory["topic_projection_pending"] is True
    ctx = McpToolContext(
        agent_id=owner.id,
        runtime="internal",
        task_id=task.id,
    )

    indexed = json.loads(
        await mcp.memory_index(
            ctx,
            text="Use Atlas for every declarative database schema change.",
            title="Database schema convention",
            source_type="test",
            source_id="test:mcp:1",
            tags=["atlas", "database"],
        )
    )
    memory_id = str(indexed["memory_id"])
    assert indexed["created"] is True
    assert indexed["task_associated"] is True
    assert indexed["links_created"] == 0
    assert indexed["topic_projection_pending"] is True

    searched = json.loads(await mcp.memory_search(ctx, "Atlas database"))
    assert searched["memories"][0]["memory_id"] == memory_id
    assert "score" not in searched["memories"][0]
    assert searched["memories"][0]["sources"] == [
        "test:mcp:1",
        f"task:{task.id}",
    ]
    assert searched["search"] == {
        "requested": "hybrid",
        "used": "lexical",
        "degraded": True,
        "reason": "embedding_not_configured",
    }

    loaded = json.loads(await mcp.memory_get(ctx, memory_id))
    assert loaded["payload"]["text"].startswith("<p>Use Atlas")
    assert loaded["access_count"] == 2
    assert loaded["last_accessed_at"] is not None
    assert loaded["updated_at"] is None

    remembered = json.loads(
        await mcp.memory_remember(
            ctx,
            content="The user prefers French answers.",
            title="Language preference",
            memory_type="core",
        )
    )
    assert remembered["created"] is True
    assert remembered["status"] == "stored"
    assert remembered["memory_id"]
    assert remembered["task_associated"] is True
    assert remembered["links_created"] == 0
    assert remembered["topic_projection_pending"] is True

    class MessengerWithHistory:
        async def history(
            self, room_id: str, limit: int = 20
        ) -> list[Message]:
            assert room_id == "room-1"
            assert limit == 20
            message = Message(
                id=uuid4(),
                connection_id=1,
                tool_id=1,
                platform="test",
                remote_message_id="message-1",
                direction="inbound",
                text="La procédure Atlas a été confirmée.",
            )
            message.sender = MessengerUser(
                id=uuid4(),
                tool_id=1,
                external_id="nicolas",
                display_name="Nicolas",
            )
            message.room = Room(
                id=uuid4(),
                connection_id=1,
                external_id=room_id,
                label=room_id,
                kind="group",
                conversation_type="text",
            )
            return [message]

    async def fake_messenger_for_agent(agent_id: int) -> MessengerWithHistory:
        assert agent_id == owner.id
        return MessengerWithHistory()

    monkeypatch.setattr(
        "app.messenger.messenger_for_agent", fake_messenger_for_agent
    )
    from unittest.mock import AsyncMock
    from app.memory import conversation_summary
    monkeypatch.setattr(conversation_summary, "summarize_transcript", AsyncMock(
        return_value="<p>Alice agreed to keep the decision.</p>"
    ))
    summarized = json.loads(
        await mcp.memory_summarize(ctx, room_id="room-1", limit=20)
    )
    assert summarized["created"] is True
    assert summarized["status"] == "stored"
    assert summarized["memory_id"]
    assert summarized["task_associated"] is True
    assert summarized["links_created"] == 0
    assert summarized["topic_projection_pending"] is True

    task_sources = list(
        (
            await db.scalars(
                select(MemorySource).where(
                    MemorySource.source_kind == "task",
                    MemorySource.source_ref == f"task:{task.id}",
                )
            )
        ).all()
    )
    assert {str(source.item_id) for source in task_sources} == {
        memory_id,
        str(remembered["memory_id"]),
        str(summarized["memory_id"]),
    }
@pytest.mark.asyncio
async def test_working_documents_are_bounded_mutable_and_shared_between_agents(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    owner_task = Task(
        label="Collaborative research",
        status=TaskStatus.EXEC,
        agent_id=owner.id,
    )
    peer_task = Task(
        label="Collaborative review",
        status=TaskStatus.EXEC,
        agent_id=peer.id,
    )
    db.add_all([owner_task, peer_task])
    await db.flush()
    owner_ctx = McpToolContext(
        agent_id=owner.id,
        runtime="internal",
        task_id=owner_task.id,
    )
    peer_ctx = McpToolContext(
        agent_id=peer.id,
        runtime="internal",
        task_id=peer_task.id,
    )

    created = await resource_service.resource_create(
        ResourceContext(
            agent_id=owner.id,
            runtime="internal",
            task_id=owner_task.id,
        ),
        "document://",
        b"<h1>Findings</h1><p>The draft uses option A.</p><h2>Evidence</h2><p>Initial.</p>",
        name="Release investigation",
    )
    document_id = created.uri.removeprefix("document://")
    assert created.state == "created"

    owner_search = json.loads(
        await mcp.memory_search(owner_ctx, "release investigation")
    )
    assert owner_search["memories"][0]["memory_id"] == document_id
    assert owner_search["memories"][0]["node_kind"] == "document"
    whole_read_refused = json.loads(await mcp.memory_get(owner_ctx, document_id))
    assert "file_read" in whole_read_refused["error"]

    repeated_suffix = await resource_service.resource_append(
        ResourceContext(
            agent_id=owner.id,
            runtime="internal",
            task_id=owner_task.id,
        ),
        f"document://{document_id}",
        "<p>Initial.</p>",
        expected_revision=created.revision,
    )
    assert repeated_suffix.state == "appended"

    invisible = json.loads(
        await mcp.memory_search(peer_ctx, "release investigation")
    )
    assert invisible["memories"] == []

    shared_read = json.loads(
        await mcp.document_share(
            owner_ctx,
            document_id=document_id,
            agent_id=peer.id,
            access="read",
        )
    )
    assert shared_read["shared_with"] == [
        {"agent_id": peer.id, "access": "read"}
    ]
    peer_passage = json.loads(
        await mcp.document_read(
            peer_ctx,
            document_id=document_id,
            query="Evidence",
            max_chars=30,
        )
    )
    assert peer_passage["content"].startswith("<h2>Evidence</h2>")
    assert peer_passage["can_write"] is False
    with pytest.raises(service.MemoryPermissionError, match="access denied"):
        await resource_service.resource_edit(
            ResourceContext(
                agent_id=peer.id,
                runtime="internal",
                task_id=peer_task.id,
            ),
            f"document://{document_id}",
            start_line=2,
            end_line=2,
            content="<p>Reviewed.</p>",
            expected_revision=repeated_suffix.revision,
        )

    shared_edit = json.loads(
        await mcp.document_share(
            owner_ctx,
            document_id=document_id,
            agent_id=peer.id,
            access="edit",
        )
    )
    assert shared_edit["shared_with"] == [
        {"agent_id": peer.id, "access": "edit"}
    ]
    edited = await resource_service.resource_edit(
        ResourceContext(
            agent_id=peer.id,
            runtime="internal",
            task_id=peer_task.id,
        ),
        f"document://{document_id}",
        start_line=2,
        end_line=2,
        content="<p>The reviewed draft uses option B.</p>",
        expected_revision=repeated_suffix.revision,
    )
    assert edited.state == "edited"
    appended = await resource_service.resource_append(
        ResourceContext(
            agent_id=peer.id,
            runtime="internal",
            task_id=peer_task.id,
        ),
        f"document://{document_id}",
        "<h2>Review</h2><p>Validated by the peer.</p>",
        expected_revision=edited.revision,
    )
    assert appended.state == "appended"
    duplicate_retry = await resource_service.resource_append(
        ResourceContext(
            agent_id=peer.id,
            runtime="internal",
            task_id=peer_task.id,
        ),
        f"document://{document_id}",
        "<h2>Review</h2><p>Validated by the peer.</p>",
        expected_revision=edited.revision,
    )
    assert duplicate_retry.state == "unchanged"
    assert duplicate_retry.revision == appended.revision

    current = await resource_service.resource_read(
        ResourceContext(
            agent_id=owner.id,
            runtime="internal",
            task_id=owner_task.id,
        ),
        f"document://{document_id}",
    )
    assert "option B" in current.content
    assert "Validated by the peer" in current.content
    peer_forget = json.loads(await mcp.memory_forget(peer_ctx, document_id))
    assert "Only the document owner" in peer_forget["error"]

    revisions = list(
        (
            await db.scalars(
                select(MemoryRevision)
                .where(MemoryRevision.item_id == UUID(document_id))
                .order_by(MemoryRevision.revision)
            )
        ).all()
    )
    assert revisions[0].task_id == owner_task.id
    assert peer_task.id in {revision.task_id for revision in revisions}
    assert peer.id in {
        revision.author_agent_id
        for revision in revisions
        if revision.author_agent_id is not None
    }

    removed = json.loads(
        await mcp.document_share(
            owner_ctx,
            document_id=document_id,
            agent_id=peer.id,
            access="none",
        )
    )
    assert removed["shared_with"] == []
    with pytest.raises(service.MemoryPermissionError, match="access denied"):
        await mcp.document_read(peer_ctx, document_id=document_id)
