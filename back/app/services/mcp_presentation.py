"""Bounded, opt-in presentation data from external MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastmcp.tools import Tool
from mcp.client import advertise
from mcp.types import Tool as RemoteTool
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

MCP_PRESENTATIONS_KEY = "galaris.mcp-presentations/v1"
MCP_APP_MIME = "text/html;profile=mcp-app"
MAX_PRESENTATIONS = 4
MAX_APP_HTML_BYTES = 256_000
MCP_APP_EXTENSION = advertise("io.modelcontextprotocol/ui", {"mimeTypes": [MCP_APP_MIME]})

Label = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Cell = Annotated[str, StringConstraints(max_length=1_000)] | bool | int | float | None


class McpTable(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    title: Label
    columns: list[Label] = Field(min_length=1, max_length=16)
    rows: list[Annotated[list[Cell], Field(max_length=16)]] = Field(max_length=100)

    @model_validator(mode="after")
    def _bounded_rows(self) -> McpTable:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Each table row must have one cell per column")
        if len(self.model_dump_json().encode()) > 64_000:
            raise ValueError("The table exceeds the presentation size limit")
        return self


class McpPresentation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source: str = Field(max_length=200)
    connection_id: int
    service_id: int
    tool_name: str = Field(max_length=255)
    resource_uri: str | None = Field(default=None, max_length=1_000)
    table: McpTable


McpPresentationSink = Callable[[McpPresentation], None]


def presented_table(structured_content: object) -> McpTable | None:
    if not isinstance(structured_content, dict):
        return None
    try:
        return McpTable.model_validate(cast(dict[str, object], structured_content).get("table"))
    except (ValidationError, ValueError):
        return None


def app_resource_uri(tool: Tool | RemoteTool) -> str | None:
    ui: object = (tool.meta or {}).get("ui")
    uri = cast(dict[str, object], ui).get("resourceUri") if isinstance(ui, dict) else None
    return uri if isinstance(uri, str) and 5 < len(uri) <= 1_000 and uri.startswith("ui://") else None


def app_tool_visible_to(tool: Tool | RemoteTool, target: str) -> bool:
    ui: object = (tool.meta or {}).get("ui")
    visibility: object = cast(dict[str, object], ui).get("visibility") if isinstance(ui, dict) else None
    return visibility is None or isinstance(visibility, list) and target in visibility


def app_read_tool(tool: Tool | RemoteTool) -> bool:
    return bool(tool.annotations and tool.annotations.read_only_hint is True and app_tool_visible_to(tool, "app"))


def read_presentations(value: object) -> list[McpPresentation]:
    if not isinstance(value, list):
        return []
    try:
        return [McpPresentation.model_validate(item) for item in cast(list[object], value)[:MAX_PRESENTATIONS]]
    except ValidationError:
        return []
