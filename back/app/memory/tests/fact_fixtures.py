"""Build explicit scalar facts for existing MCP workflow fixtures."""

from core.util import visible_text, RichTextError
from app.memory import mcp


async def remember_fact(ctx, *, content, **kwargs):
    try:
        value = visible_text(content)
    except RichTextError:
        value = content
    return await mcp.memory_remember(ctx, fact={"predicate": "fixture_value", "value": value}, **kwargs)
