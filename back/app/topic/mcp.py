"""Administrative MCP Tool for instance-wide thematic Topics."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from app.connection.facade import has_active_tool_connection
from app.tools import McpToolContext, mcp_tool

from . import service
from .schemas import (
    TopicCreate,
    TopicItemKind,
    TopicItemSelector,
    TopicSelectionSplitRequest,
    TopicUpdate,
)


_TOOL_CODE = "topic"
_ITEM_TYPES = frozenset(
    {
        "task",
        "message",
        "conversation_round",
        "voice_turn",
        "memory",
        "document",
    }
)


def _uuid(value: str, *, field: str) -> UUID:
    try:
        return UUID(value.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"Invalid {field} UUID: {value}") from exc


async def _require_access(ctx: McpToolContext) -> None:
    if not await has_active_tool_connection(ctx.agent_id, _TOOL_CODE):
        raise PermissionError(
            "An active topic connection is required for Topic administration."
        )


def _item_type(value: str | None) -> TopicItemKind | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in _ITEM_TYPES:
        raise ValueError(
            "item_type must be task, message, conversation_round, voice_turn, memory, or document"
        )
    return cast(TopicItemKind, normalized)


@mcp_tool(
    _TOOL_CODE,
    name="topic_list",
    description=(
        "List the instance's Topics with stable UUIDs, revisions, descriptions, keywords, "
        "usage, and related entities. Use the returned revision before topic_update."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def mcp_topic_list(
    ctx: McpToolContext,
    search: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    await _require_access(ctx)
    if offset < 0:
        raise ValueError("offset must be greater than or equal to zero")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    page = await service.list_page(
        skip=offset,
        limit=limit,
        search=search,
    )
    return page.model_dump(mode="json")


@mcp_tool(
    _TOOL_CODE,
    name="topic_get",
    description=(
        "Get one Topic by exact UUID, including its current revision. Use topic_items_list "
        "to inspect the objects assigned to it."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def mcp_topic_get(ctx: McpToolContext, topic_id: str) -> dict[str, object]:
    await _require_access(ctx)
    identifier = _uuid(topic_id, field="topic_id")
    topic = await service.get(identifier)
    if topic is None:
        raise ValueError(f"Topic not found: {identifier}")
    return topic.model_dump(mode="json")


@mcp_tool(
    _TOOL_CODE,
    name="topic_items_list",
    description=(
        "List objects assigned or linked to one Topic. Optionally filter item_type to task, "
        "message, conversation_round, voice_turn, memory, or document. Returned item IDs can "
        "be passed unchanged to topic_item_move or topic_split."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def mcp_topic_items_list(
    ctx: McpToolContext,
    topic_id: str,
    item_type: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    await _require_access(ctx)
    page = await service.list_items(
        _uuid(topic_id, field="topic_id"),
        item_type=_item_type(item_type),
        offset=offset,
        limit=limit,
    )
    return page.model_dump(mode="json")


@mcp_tool(
    _TOOL_CODE,
    name="topic_create",
    description=(
        "Create a global Topic with a concise title and optional description and keywords. "
        "Prefer topic_list first to avoid fragmenting an existing subject."
    ),
)
async def mcp_topic_create(
    ctx: McpToolContext,
    title: str,
    description: str = "",
    keywords: list[str] | None = None,
) -> dict[str, object]:
    await _require_access(ctx)
    topic = await service.create(
        TopicCreate(
            title=title,
            description=description,
            keywords=keywords or [],
        )
    )
    return topic.model_dump(mode="json")


@mcp_tool(
    _TOOL_CODE,
    name="topic_update",
    description=(
        "Replace a Topic's title, description, and keywords using the exact current revision "
        "returned by topic_get or topic_list. A stale revision is rejected."
    ),
)
async def mcp_topic_update(
    ctx: McpToolContext,
    topic_id: str,
    expected_revision: int,
    title: str,
    description: str = "",
    keywords: list[str] | None = None,
) -> dict[str, object]:
    await _require_access(ctx)
    topic = await service.update_topic(
        _uuid(topic_id, field="topic_id"),
        TopicUpdate(
            revision=expected_revision,
            title=title,
            description=description,
            keywords=keywords or [],
        ),
    )
    return topic.model_dump(mode="json")


@mcp_tool(
    _TOOL_CODE,
    name="topic_item_move",
    description=(
        "Move one exact task, message, conversation round, voice turn, memory, or document "
        "from its current Topic to another Topic. Resolve both Topic UUIDs and the item with "
        "topic_list and topic_items_list first."
    ),
)
async def mcp_topic_item_move(
    ctx: McpToolContext,
    source_topic_id: str,
    target_topic_id: str,
    item_type: str,
    item_id: str,
) -> dict[str, object]:
    await _require_access(ctx)
    kind = _item_type(item_type)
    assert kind is not None
    result = await service.reassign_item(
        _uuid(source_topic_id, field="source_topic_id"),
        _uuid(target_topic_id, field="target_topic_id"),
        TopicItemSelector(
            item_type=kind,
            item_id=_uuid(item_id, field="item_id"),
        ),
    )
    return result.model_dump(mode="json")


@mcp_tool(
    _TOOL_CODE,
    name="topic_merge",
    description=(
        "Merge a source Topic into a target Topic. All assignments and memory links move to "
        "the target, then the source Topic is soft-deleted. This operation is irreversible."
    ),
)
async def mcp_topic_merge(
    ctx: McpToolContext,
    source_topic_id: str,
    target_topic_id: str,
) -> dict[str, object]:
    await _require_access(ctx)
    result = await service.merge(
        _uuid(source_topic_id, field="source_topic_id"),
        _uuid(target_topic_id, field="target_topic_id"),
    )
    return result.model_dump(mode="json")


@mcp_tool(
    _TOOL_CODE,
    name="topic_split",
    description=(
        "Split selected heterogeneous items out of a source Topic into a newly created Topic. "
        "Pass the exact item_type and item_id pairs returned by topic_items_list."
    ),
)
async def mcp_topic_split(
    ctx: McpToolContext,
    source_topic_id: str,
    title: str,
    items: list[TopicItemSelector],
    description: str = "",
    keywords: list[str] | None = None,
) -> dict[str, object]:
    await _require_access(ctx)
    result = await service.split_selection(
        _uuid(source_topic_id, field="source_topic_id"),
        TopicSelectionSplitRequest(
            title=title,
            description=description,
            keywords=keywords or [],
            items=items,
        ),
    )
    return result.model_dump(mode="json")


__all__ = [
    "mcp_topic_create",
    "mcp_topic_get",
    "mcp_topic_item_move",
    "mcp_topic_items_list",
    "mcp_topic_list",
    "mcp_topic_merge",
    "mcp_topic_split",
    "mcp_topic_update",
]
