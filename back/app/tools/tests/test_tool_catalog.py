from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.tools import mcp_loader
from app.tools.catalog import (
    build_effective_tool_catalog,
    catalog_entry_from_definition,
    catalog_from_entries,
)


@pytest.mark.asyncio
async def test_effective_catalog_is_rights_filtered_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = [
        SimpleNamespace(
            name="mcp__galaris__messenger_room_history",
            description="Read room history",
            parameters={
                "type": "object",
                "properties": {
                    "room_id": {
                        "type": "string",
                        "description": "Exact room identifier",
                        "default": "secret-room",
                    }
                },
                "required": ["room_id"],
                "x-secret": "must disappear",
            },
        ),
        SimpleNamespace(
            name="mcp__galaris__admin_delete",
            description="Administrative deletion",
            parameters={"type": "object", "properties": {}},
        ),
    ]
    mcp = SimpleNamespace(list_tools=AsyncMock(return_value=tools))
    monkeypatch.setattr(
        mcp_loader,
        "build_agent_mcp",
        AsyncMock(return_value=mcp),
    )

    catalog = await build_effective_tool_catalog(
        7,
        runtime="internal",
        allowed_tool_names={"messenger_room_history"},
    )

    assert catalog.names == frozenset({"messenger_room_history"})
    assert catalog.entries[0].parameters_json_schema == {
        "type": "object",
        "properties": {
            "room_id": {
                "type": "string",
                "description": "Exact room identifier",
            }
        },
        "required": ["room_id"],
    }
    assert "secret-room" not in catalog.entries[0].embedding_text


def test_catalog_version_changes_with_public_definition() -> None:
    first = catalog_entry_from_definition(
        runtime="internal",
        name="search_web",
        description="Search the web",
        parameters_json_schema={"type": "object", "properties": {}},
    )
    changed = catalog_entry_from_definition(
        runtime="internal",
        name="search_web",
        description="Search public web pages",
        parameters_json_schema={"type": "object", "properties": {}},
    )

    first_catalog = catalog_from_entries(
        agent_id=1,
        runtime="internal",
        entries=[first],
    )
    changed_catalog = catalog_from_entries(
        agent_id=1,
        runtime="internal",
        entries=[changed],
    )

    assert first_catalog.version != changed_catalog.version


def test_catalog_rejects_ambiguous_normalized_names() -> None:
    first = catalog_entry_from_definition(
        runtime="internal",
        name="search_web",
        description="Search the public web",
        parameters_json_schema={},
    )
    conflicting = catalog_entry_from_definition(
        runtime="internal",
        name="mcp__galaris__search_web",
        description="Search a private index",
        parameters_json_schema={},
    )

    with pytest.raises(ValueError, match="Ambiguous MCP tool name"):
        catalog_from_entries(
            agent_id=1,
            runtime="internal",
            entries=[first, conflicting],
        )
