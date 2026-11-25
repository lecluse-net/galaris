import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services import McpToolContext
from app.topic import mcp, resource_facade
from app.topic.schemas import TopicItemMutationResult, TopicItemRead


def test_topic_mcp_functions_are_grouped_in_the_dedicated_tool() -> None:
    functions = (
        mcp.mcp_topic_list,
        mcp.mcp_topic_items_list,
        mcp.mcp_topic_create,
        mcp.mcp_topic_update,
        mcp.mcp_topic_item_move,
        mcp.mcp_topic_merge,
        mcp.mcp_topic_split,
    )

    assert {
        getattr(function, "__galaris_mcp_tool__").service_code
        for function in functions
    } == {"topic"}
    assert getattr(mcp.mcp_topic_list, "__galaris_mcp_tool__").effect_policy == "read"
    assert getattr(mcp.mcp_topic_items_list, "__galaris_mcp_tool__").concurrency_policy == "safe"


@pytest.mark.asyncio
async def test_topic_mcp_rechecks_its_live_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resource_facade,
        "has_active_tool_connection",
        AsyncMock(return_value=False),
    )

    with pytest.raises(PermissionError, match="active topic connection"):
        await mcp.mcp_topic_list(McpToolContext(agent_id=7, runtime="internal"))
    with pytest.raises(PermissionError, match="active topic connection"):
        await resource_facade.read_topic_resource(uuid4(), 7)


@pytest.mark.asyncio
async def test_topic_list_returns_a_file_uri_with_the_same_live_access(db) -> None:
    from app.agent import Agent, Title
    from app.connection import Connection
    from app.file_share import ResourceContext, resource_list, resource_read
    from app.services import ServiceModel
    from app.topic import service
    from app.topic.schemas import TopicCreate
    from sqlalchemy import select

    title = Title(label="Synthetic Topic reader", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(title_id=title.id, code="synthetic-topic-reader", first_name="Synthetic", last_name="Reader")
    db.add(agent)
    await db.flush()
    topic = await service.create(TopicCreate(title="Synthetic Topic metadata", keywords=["synthetic"]))
    service_id = await db.scalar(select(ServiceModel.id).where(ServiceModel.code == "topic"))
    connection = Connection(service_id=service_id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    ctx = ResourceContext(agent_id=agent.id, runtime="internal")
    catalog = await mcp.mcp_topic_list(McpToolContext(agent_id=agent.id, runtime="internal"))
    uri = next(item["resource_uri"] for item in catalog["items"] if item["id"] == str(topic.id))
    assert uri in {item.uri for item in (await resource_list(ctx, "galaris://topic/")).entries}
    payload = json.loads((await resource_read(ctx, uri)).content)
    assert (payload["title"], payload["revision"]) == (topic.title, topic.revision)
    connection.active = False
    await db.flush()
    assert (await resource_list(ctx, "galaris://topic/")).entries == []
    with pytest.raises(PermissionError, match="active topic connection"):
        await resource_read(ctx, uri)


@pytest.mark.asyncio
async def test_topic_item_move_uses_exact_typed_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = uuid4()
    target_id = uuid4()
    message_id = uuid4()
    reassign = AsyncMock(
        return_value=TopicItemMutationResult(
            item=TopicItemRead(
                item_type="message",
                item_id=message_id,
                topic_id=target_id,
                title="Reclassified message",
            ),
            source_topic_id=source_id,
            target_topic_id=target_id,
        )
    )
    monkeypatch.setattr(
        resource_facade,
        "has_active_tool_connection",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(mcp.service, "reassign_item", reassign)

    payload = await mcp.mcp_topic_item_move(
        McpToolContext(agent_id=7, runtime="internal"),
        source_topic_id=str(source_id),
        target_topic_id=str(target_id),
        item_type="message",
        item_id=str(message_id),
    )

    assert payload["target_topic_id"] == str(target_id)
    selector = reassign.await_args.args[2]
    assert selector.item_type == "message"
    assert selector.item_id == message_id
