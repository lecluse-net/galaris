from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.tools import McpToolContext
from app.topic import mcp
from app.topic.schemas import TopicItemMutationResult, TopicItemRead


def test_topic_mcp_functions_are_grouped_in_the_dedicated_tool() -> None:
    functions = (
        mcp.mcp_topic_list,
        mcp.mcp_topic_get,
        mcp.mcp_topic_items_list,
        mcp.mcp_topic_create,
        mcp.mcp_topic_update,
        mcp.mcp_topic_item_move,
        mcp.mcp_topic_merge,
        mcp.mcp_topic_split,
    )

    assert {
        getattr(function, "__galaris_mcp_tool__").tool_code
        for function in functions
    } == {"topic"}
    assert getattr(mcp.mcp_topic_list, "__galaris_mcp_tool__").effect_policy == "read"
    assert getattr(mcp.mcp_topic_items_list, "__galaris_mcp_tool__").concurrency_policy == "safe"


@pytest.mark.asyncio
async def test_topic_mcp_rechecks_its_live_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp,
        "has_active_tool_connection",
        AsyncMock(return_value=False),
    )

    with pytest.raises(PermissionError, match="active topic connection"):
        await mcp.mcp_topic_get(
            McpToolContext(agent_id=7, runtime="internal"),
            str(uuid4()),
        )


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
        mcp,
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
