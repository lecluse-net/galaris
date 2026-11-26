"""Discover deferred tools from the same governed catalog used by Pydantic AI."""

import json
from collections.abc import Awaitable, Callable, Collection
from uuid import UUID

from mcp.types import CallToolResult, TextContent, Tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.contracts import normalize_tool_name
from app.services import catalog_entry_from_definition, catalog_from_entries, mcp_loader, search_catalog_in_isolated_session
from core.database import get_db_session

from .mcp_toolset import MountedMcpTools


SEARCH_TOOLS = "search_deferred_tools"
CALL_TOOL = "call_discovered_tool"
DISCOVERY_TOOLS = frozenset({SEARCH_TOOLS, CALL_TOOL})


class _SearchInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    query: str = Field(min_length=1, max_length=4_000, description="What the tool must do, or its exact name.")


class DiscoveredToolInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str = Field(description="Exact tool name returned by search_deferred_tools.")
    arguments: dict[str, object] = Field(description="Arguments conforming to that tool's returned input schema.")


class ClaudeToolDiscovery:
    def __init__(self, mounted: MountedMcpTools, *, agent_id: int, task_id: UUID,
                 candidate_names: Collection[str]) -> None:
        self._mounted = mounted
        self._agent_id = agent_id
        self._task_id = task_id
        self.candidate_names = frozenset(candidate_names)
        self._revealed: set[str] = set()
        self.definitions = {
            SEARCH_TOOLS: Tool.model_validate({
                "name": SEARCH_TOOLS,
                "description": "Find authorized tools for this task when the currently listed tools do not cover the work. "
                               "Call this first, then use call_discovered_tool with an exact result name and its schema.",
                "inputSchema": _SearchInput.model_json_schema(),
            }),
            CALL_TOOL: Tool.model_validate({
                "name": CALL_TOOL,
                "description": "Run one tool discovered in a preceding search_deferred_tools result in this task attempt.",
                "inputSchema": DiscoveredToolInput.model_json_schema(),
            }),
        }

    def revealed_call(self, arguments: dict[str, object]) -> DiscoveredToolInput | None:
        try:
            call = DiscoveredToolInput.model_validate(arguments)
        except ValidationError:
            return None
        return call if call.name in self._revealed else None

    async def search(self, arguments: dict[str, object], authorize: Callable[[], Awaitable[None]]) -> CallToolResult:
        try:
            request = _SearchInput.model_validate(arguments)
        except ValidationError:
            return _result("Describe the tool you need in the query field.", error=True)
        live = await self._live_tools(self.candidate_names)
        # Refuse ambiguous normalized names instead of mapping a hit to the wrong wire tool.
        names = {normalize_tool_name(name).strip(): name for name in live}
        if len(names) != len(live):
            return _result("Galaris could not disambiguate the current tool catalog.", error=True)
        catalog = catalog_from_entries(agent_id=self._agent_id, runtime="internal", entries=(
            catalog_entry_from_definition(runtime="internal", name=name, description=tool.description,
                                          parameters_json_schema=tool.input_schema)
            for name, tool in live.items()
        ))
        result = await search_catalog_in_isolated_session(catalog, query=request.query, limit=10, surface="executor")
        matches = await self._live_tools({names[hit.entry.name] for hit in result.hits})
        await authorize()
        disclosed = [(name, hit.entry) for hit in result.hits if (name := names[hit.entry.name]) in matches]
        found = [
            {"name": name, "description": entry.description, "input_schema": matches[name].input_schema}
            for name, entry in disclosed
        ]
        self._revealed.update(name for name, _ in disclosed)
        return _result(json.dumps({"tools": found}, ensure_ascii=False))

    async def is_live(self, name: str) -> bool:
        return name in await self._live_tools({name})

    async def _live_tools(self, names: Collection[str]) -> dict[str, Tool]:
        native = self._mounted.native_names.intersection(names)
        definitions: dict[str, Tool] = {}
        if native:
            async with get_db_session():
                visible = await mcp_loader.list_enabled_native_mcp_definitions(
                    self._agent_id, runtime="internal", task_id=self._task_id, allowed_tool_names=native,
                )
            definitions.update((item.name, self._mounted.definitions[item.name]) for item in visible)
        external = set(names) - native
        if external:
            for tool in await self._mounted.client.list_tools():
                if tool.name in external and (admitted := self._mounted.definitions.get(tool.name)) is not None:
                    if tool.input_schema == admitted.input_schema and tool.description == admitted.description:
                        definitions[tool.name] = admitted
        return definitions


def _result(text: str, *, error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=error)
