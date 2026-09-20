"""Public, rights-filtered projection of the effective MCP catalog."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from app.agent.contracts import RuntimeName, normalize_tool_name
from core.util import as_dict, as_list


_MAX_DESCRIPTION_CHARS = 4_000
_MAX_FIELD_DESCRIPTION_CHARS = 500
_MAX_SCHEMA_PROPERTIES = 100


def _normalized_text(value: object, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _bounded_parameters_schema(value: object) -> dict[str, Any]:
    """Keep routing metadata while dropping large or non-public schema extensions."""

    raw = as_dict(value)
    properties = as_dict(raw.get("properties"))
    bounded_properties: dict[str, dict[str, Any]] = {}
    for raw_name in sorted(properties)[:_MAX_SCHEMA_PROPERTIES]:
        name = str(raw_name)
        definition = as_dict(properties[raw_name])
        item: dict[str, Any] = {}
        field_type = definition.get("type")
        if isinstance(field_type, (str, list)):
            item["type"] = field_type
        description = _normalized_text(
            definition.get("description"),
            limit=_MAX_FIELD_DESCRIPTION_CHARS,
        )
        if description:
            item["description"] = description
        enum = as_list(definition.get("enum"))
        if enum:
            item["enum"] = [str(entry)[:100] for entry in enum[:20]]
        bounded_properties[name[:200]] = item

    required = [
        str(name)[:200]
        for name in as_list(raw.get("required"))
        if str(name) in properties
    ][:_MAX_SCHEMA_PROPERTIES]
    result: dict[str, Any] = {
        "type": "object",
        "properties": bounded_properties,
    }
    if required:
        result["required"] = required
    return result


def _input_summary(schema: dict[str, Any]) -> str:
    properties = as_dict(schema.get("properties"))
    required = {str(name) for name in as_list(schema.get("required"))}
    fields: list[str] = []
    for raw_name, raw_definition in properties.items():
        name = str(raw_name)
        definition = as_dict(raw_definition)
        raw_type = definition.get("type")
        field_type = (
            "|".join(str(item) for item in as_list(raw_type))
            if isinstance(raw_type, list)
            else str(raw_type or "any")
        )
        description = _normalized_text(
            definition.get("description"),
            limit=160,
        )
        marker = " required" if name in required else ""
        rendered = f"{name} ({field_type}{marker})"
        if description:
            rendered += f": {description}"
        fields.append(rendered)
    return "; ".join(fields)


@dataclass(frozen=True)
class AgentToolCatalogEntry:
    """One tool definition already filtered by the effective agent MCP projection."""

    runtime: RuntimeName
    name: str
    description: str
    parameters_json_schema: dict[str, Any]
    input_summary: str
    definition_fingerprint: str

    @property
    def embedding_text(self) -> str:
        sections = [self.name]
        if self.description:
            sections.append(self.description)
        if self.input_summary:
            sections.append(f"Inputs: {self.input_summary}")
        return "\n".join(sections)


@dataclass(frozen=True)
class AgentToolCatalog:
    """Immutable effective catalog and its stable, non-secret version."""

    agent_id: int
    runtime: RuntimeName
    entries: tuple[AgentToolCatalogEntry, ...]
    version: str

    @property
    def names(self) -> frozenset[str]:
        return frozenset(entry.name for entry in self.entries)


def catalog_entry_from_definition(
    *,
    runtime: RuntimeName,
    name: object,
    description: object,
    parameters_json_schema: object,
) -> AgentToolCatalogEntry:
    """Normalize one FastMCP or Pydantic AI definition into public metadata."""

    normalized_name = normalize_tool_name(name).strip()
    normalized_description = _normalized_text(
        description,
        limit=_MAX_DESCRIPTION_CHARS,
    )
    schema = _bounded_parameters_schema(parameters_json_schema)
    payload = json.dumps(
        {
            "contract": 1,
            "runtime": runtime,
            "name": normalized_name,
            "description": normalized_description,
            "parameters": schema,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return AgentToolCatalogEntry(
        runtime=runtime,
        name=normalized_name,
        description=normalized_description,
        parameters_json_schema=schema,
        input_summary=_input_summary(schema),
        definition_fingerprint=fingerprint,
    )


def catalog_from_entries(
    *,
    agent_id: int,
    runtime: RuntimeName,
    entries: Iterable[AgentToolCatalogEntry],
) -> AgentToolCatalog:
    unique: dict[str, AgentToolCatalogEntry] = {}
    for entry in entries:
        if not entry.name:
            continue
        previous = unique.get(entry.name)
        if (
            previous is not None
            and previous.definition_fingerprint != entry.definition_fingerprint
        ):
            raise ValueError(
                f"Ambiguous MCP tool name in effective catalog: {entry.name}"
            )
        unique[entry.name] = entry
    ordered = tuple(
        sorted(
            unique.values(),
            key=lambda entry: (entry.name, entry.definition_fingerprint),
        )
    )
    version_payload = "\n".join(entry.definition_fingerprint for entry in ordered)
    version = hashlib.sha256(version_payload.encode("ascii")).hexdigest()
    return AgentToolCatalog(
        agent_id=agent_id,
        runtime=runtime,
        entries=ordered,
        version=version,
    )


async def build_effective_tool_catalog(
    agent_id: int,
    *,
    runtime: RuntimeName,
    task_id: UUID | None = None,
    allowed_tool_names: Collection[str] | None = None,
    resources: dict[str, Any] | None = None,
    discovery_failures: set[str] | None = None,
) -> AgentToolCatalog:
    """Build the live catalog after connection, runtime and function filtering."""

    from app.tools.mcp_loader import build_agent_mcp

    mcp = await build_agent_mcp(
        agent_id,
        runtime=runtime,
        task_id=task_id,
        resources=resources,
        discovery_failures=discovery_failures,
    )
    tools = await mcp.list_tools()
    allowed = (
        frozenset(normalize_tool_name(name) for name in allowed_tool_names)
        if allowed_tool_names is not None
        else None
    )
    entries: list[AgentToolCatalogEntry] = []
    for tool in tools:
        entry = catalog_entry_from_definition(
            runtime=runtime,
            name=tool.name,
            description=tool.description,
            parameters_json_schema=cast(object, getattr(tool, "parameters", {})),
        )
        if allowed is None or entry.name in allowed:
            entries.append(entry)
    return catalog_from_entries(
        agent_id=agent_id,
        runtime=runtime,
        entries=entries,
    )


__all__ = [
    "AgentToolCatalog",
    "AgentToolCatalogEntry",
    "build_effective_tool_catalog",
    "catalog_entry_from_definition",
    "catalog_from_entries",
]
