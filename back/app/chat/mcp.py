"""Chat tools with a live user on the originating desktop."""

from typing import Annotated

from pydantic import Field

from app.conversation.contracts import ConversationTurn
from app.file_share import ResourceContext, resource_create
from app.services import McpToolContext, mcp_tool
from app.services.contracts import ToolCallRejectedError

from .desktop_screen import MAX_IMAGE_BYTES, ScreenUnavailable, eligible_tab, request_screen


def _turn(ctx: McpToolContext) -> ConversationTurn | None:
    value = ctx.resource("conversation_turn")
    if ctx.runtime == "internal" and ctx.conversation_only and ctx.task_id is None and isinstance(value, ConversationTurn):
        return value if ctx.agent_id == value.agent_id else None
    return None


async def _available(ctx: McpToolContext) -> bool:
    turn = _turn(ctx)
    return turn is not None and await eligible_tab(turn) is not None


@mcp_tool(
    "chat",
    name="chat_screenshot",
    description="Ask the current participant to share one screenshot from the Galaris desktop client that sent this Chat turn. "
                "Explain why the screenshot is needed. The human chooses a screen or window and approves the upload. "
                "Returns the saved file's canonical file:// URI, name and media type. Use the URI to attach the image.",
    conversation_policy="short",
    task_enabled=False,
    timeout_seconds=100,
    available_when=_available,
    approval="enabled",
    approval_reason="Screen capture requires a new, one-use local desktop consent for each call.",
)
async def chat_screenshot(
    ctx: McpToolContext,
    reason: Annotated[str, Field(min_length=1, max_length=400)],
) -> dict[str, str]:
    turn = _turn(ctx)
    if turn is None:
        raise ToolCallRejectedError("A live Chat turn from the original desktop client is required.")
    try:
        data = await request_screen(turn, reason)
    except ScreenUnavailable as error:
        raise ToolCallRejectedError(str(error)) from error
    if turn.assert_fresh_before_effect is None or not await turn.assert_fresh_before_effect():
        raise ToolCallRejectedError("The Chat turn is no longer current.")
    name = "screenshot.jpg"
    file = await resource_create(ResourceContext(agent_id=ctx.agent_id, runtime=ctx.runtime,
        language=turn.language, conversation_turn=turn), "file://", data, name=name, max_bytes=MAX_IMAGE_BYTES)
    return {"uri": file.uri, "name": name, "media_type": "image/jpeg"}
