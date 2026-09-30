"""Synthetic MCP boundary for the isolated assembled ToolAdmin browser journey."""

import json

from fastapi import APIRouter, Body
from fastmcp import Client, FastMCP

from app.tools import build_agent_galaris_fastmcp
from core.database import get_db_session

router = APIRouter(prefix="/api/__test/tool-admin")
remote = FastMCP("Synthetic ToolAdmin integration")
business_calls: list[str] = []


@remote.tool()
async def lookup(value: str = "") -> str:
    """Read a synthetic value without external providers."""
    business_calls.append(value)
    return value


remote_app = remote.http_app(path="/")


@router.post("/{agent_id}/{function_name}")
async def invoke(agent_id: int, function_name: str, arguments: dict = Body(default_factory=dict)):
    if not function_name.startswith("tool_admin_"):
        return {"success": False}
    async with get_db_session():
        server = await build_agent_galaris_fastmcp(agent_id, runtime="internal")
        async with Client(server) as client:
            result = await client.call_tool(function_name, arguments, raise_on_error=False)
    if result.is_error:
        return {"success": False, "rejected": True}
    return json.loads(result.content[0].text)


@router.get("/business-calls")
async def calls():
    return {"calls": business_calls}
