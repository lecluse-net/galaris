from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.file_share import mcp as file_share_mcp
from app.file_share.resource_contracts import (
    ResourceContext,
    ResourceListing,
    ResourceMutation,
    ResourceTransfer,
)
from app.tools.mcp_loader import McpToolContext, load_mcp_tools, mcp_tool_names_by_tool_code


async def _language(_ctx: McpToolContext) -> str:
    return "en"


def test_file_search_description_stays_transport_focused() -> None:
    definition = next(item for item in load_mcp_tools() if item.name == "file_search")

    assert "Returns canonical resource URIs" in definition.description
    assert "injected memory brief" not in definition.description
    assert "galaris:// supports name and text search" in definition.description


@pytest.mark.asyncio
async def test_file_search_rejects_galaris_semantic_mode_with_actionable_guidance() -> None:
    with pytest.raises(RuntimeError, match="Retry with mode='text'"):
        await file_share_mcp.search_files(
            McpToolContext(agent_id=7, runtime="internal"),
            "galaris://task/",
            "deployment",
            mode="semantic",
        )


@pytest.mark.asyncio
async def test_file_list_forwards_and_returns_the_pagination_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_context = ResourceContext(agent_id=7, runtime="hermes")
    captured: dict[str, object] = {}

    async def context(_ctx: McpToolContext) -> ResourceContext:
        return resource_context

    async def list_resources(
        ctx: ResourceContext,
        uri: str,
        *,
        recursive: bool,
        max_entries: int,
        cursor: str | None,
    ) -> ResourceListing:
        captured.update(
            ctx=ctx,
            uri=uri,
            recursive=recursive,
            max_entries=max_entries,
            cursor=cursor,
        )
        return ResourceListing(
            uri=uri,
            entries=[],
            truncated=True,
            next_cursor="1000",
        )

    monkeypatch.setattr(file_share_mcp, "_resource_context", context)
    monkeypatch.setattr(file_share_mcp, "resource_list", list_resources)

    result = await file_share_mcp.list_files(
        McpToolContext(agent_id=7, runtime="hermes"),
        "galaris://task/",
        recursive=False,
        max_entries=500,
        cursor="500",
    )

    assert captured == {
        "ctx": resource_context,
        "uri": "galaris://task/",
        "recursive": False,
        "max_entries": 500,
        "cursor": "500",
    }
    assert '"truncated": true' in result
    assert '"next_cursor": "1000"' in result


@pytest.mark.asyncio
async def test_file_list_prefers_the_console_root_when_uri_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_context = ResourceContext(
        agent_id=7,
        runtime="internal",
        console_resource=object(),
    )
    captured: dict[str, object] = {}

    async def context(_ctx: McpToolContext) -> ResourceContext:
        return resource_context

    async def list_resources(
        ctx: ResourceContext,
        uri: str,
        *,
        recursive: bool,
        max_entries: int,
        cursor: str | None,
    ) -> ResourceListing:
        captured.update(ctx=ctx, uri=uri)
        return ResourceListing(uri=uri)

    monkeypatch.setattr(file_share_mcp, "_resource_context", context)
    monkeypatch.setattr(file_share_mcp, "resource_list", list_resources)

    result = await file_share_mcp.list_files(
        McpToolContext(agent_id=7, runtime="internal")
    )

    assert captured == {"ctx": resource_context, "uri": "console://"}
    assert '"uri": "console://"' in result


@pytest.mark.asyncio
async def test_file_list_requires_a_provider_without_a_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_context = ResourceContext(agent_id=7, runtime="internal")
    async def context(_ctx: McpToolContext) -> ResourceContext:
        return resource_context

    monkeypatch.setattr(file_share_mcp, "_resource_context", context)

    with pytest.raises(RuntimeError, match="No local filesystem"):
        await file_share_mcp.list_files(
            McpToolContext(agent_id=7, runtime="internal")
        )


@pytest.mark.asyncio
async def test_file_copy_is_the_only_cross_provider_transfer_primitive(
    monkeypatch: pytest.MonkeyPatch,
    db,
) -> None:
    captured: dict[str, Any] = {}

    async def copy(
        _ctx: object,
        source: object,
        destination: object,
        *,
        overwrite: bool,
    ) -> ResourceTransfer:
        captured.update(
            source=source,
            destination=destination,
            overwrite=overwrite,
        )
        return ResourceTransfer(
            source_uri="telegram://room-7/attachment-9",
            uri="nextcloud://downloads/report.pdf",
            size=15,
        )

    monkeypatch.setattr(file_share_mcp, "_context_language", _language)
    monkeypatch.setattr(file_share_mcp, "resource_copy", copy)

    result = await file_share_mcp.copy_file(
        McpToolContext(agent_id=7, runtime="hermes"),
        "telegram://room-7/attachment-9",
        "nextcloud://downloads/report.pdf",
        overwrite=True,
    )

    assert captured == {
        "source": "telegram://room-7/attachment-9",
        "destination": "nextcloud://downloads/report.pdf",
        "overwrite": True,
    }
    assert '"uri": "nextcloud://downloads/report.pdf"' in result


@pytest.mark.asyncio
async def test_file_write_decodes_complete_base64_binary_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_context = ResourceContext(agent_id=7, runtime="internal")
    captured: dict[str, object] = {}

    async def context(_ctx: McpToolContext) -> ResourceContext:
        return resource_context

    async def write(
        ctx: ResourceContext,
        uri: object,
        content: bytes,
        *,
        expected_revision: int | None,
    ) -> ResourceMutation:
        captured.update(
            ctx=ctx,
            uri=uri,
            content=content,
            expected_revision=expected_revision,
        )
        return ResourceMutation(
            uri="console://image.bin",
            operation="write",
            state="written",
            size=len(content),
        )

    monkeypatch.setattr(file_share_mcp, "_resource_context", context)
    monkeypatch.setattr(file_share_mcp, "resource_write", write)

    result = await file_share_mcp.write_file(
        McpToolContext(agent_id=7, runtime="internal"),
        "console://image.bin",
        "AP8Q",
        encoding="base64",
        expected_revision=4,
    )

    assert captured == {
        "ctx": resource_context,
        "uri": "console://image.bin",
        "content": b"\x00\xff\x10",
        "expected_revision": 4,
    }
    assert '"size": 3' in result

    with pytest.raises(ValueError, match="valid base64"):
        await file_share_mcp.write_file(
            McpToolContext(agent_id=7, runtime="internal"),
            "console://image.bin",
            "not base64!",
            encoding="base64",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("document_type,content", [(None, "<p>First draft</p>"), ("dataset", '{"amount":1200}')])
async def test_file_create_returns_the_assigned_complete_uri(
    monkeypatch: pytest.MonkeyPatch,
    document_type,
    content,
) -> None:
    resource_context = ResourceContext(agent_id=7, runtime="internal")
    captured: dict[str, object] = {}

    async def context(_ctx: McpToolContext) -> ResourceContext:
        return resource_context

    async def create(
        ctx: ResourceContext,
        path: object,
        content: bytes,
        *,
        name: str,
        document_type: str | None,
    ) -> ResourceMutation:
        captured.update(ctx=ctx, path=path, content=content, name=name, document_type=document_type)
        return ResourceMutation(
            uri="document://34ccf9d6-6ea2-49b8-a8c4-4ca9f85e0458",
            operation="create",
            state="created",
            size=len(content),
            revision=1,
        )

    monkeypatch.setattr(file_share_mcp, "_resource_context", context)
    monkeypatch.setattr(file_share_mcp, "resource_create", create)

    result = await file_share_mcp.create_file(
        McpToolContext(agent_id=7, runtime="internal"),
        "document://",
        content,
        name="Release plan",
        document_type=document_type,
    )

    assert captured == {
        "ctx": resource_context,
        "path": "document://",
        "content": content.encode(),
        "name": "Release plan",
        "document_type": document_type,
    }
    assert '"uri": "document://34ccf9d6-6ea2-49b8-a8c4-4ca9f85e0458"' in result


def test_legacy_file_wrappers_are_not_exposed() -> None:
    names_by_code = mcp_tool_names_by_tool_code()
    names = set(names_by_code["file_sharing"])

    assert {"file_upload", "file_download", "file_transfer", "file_targets"}.isdisjoint(
        names
    )
    assert {
        "file_schemes",
        "file_list",
        "file_info",
        "file_search",
        "file_read",
        "file_create",
        "file_write",
        "file_append",
        "file_edit",
        "file_copy",
        "file_move",
        "file_delete",
    } <= names
    assert {"file_read_text", "file_write_text", "file_append_text"}.isdisjoint(
        names
    )
    assert names.isdisjoint(names_by_code["galaris"])


@pytest.mark.asyncio
async def test_resource_context_projects_live_skill_management_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.skill as skill

    access = AsyncMock(return_value=True)
    monkeypatch.setattr(skill, "can_manage_skill_resources", access)
    monkeypatch.setattr(file_share_mcp, "_context_language", AsyncMock(return_value="fr"))

    result = await file_share_mcp._resource_context(  # pyright: ignore[reportPrivateUsage]
        McpToolContext(agent_id=19, runtime="internal")
    )

    assert result.skill_management is True
    access.assert_awaited_once_with(19)
