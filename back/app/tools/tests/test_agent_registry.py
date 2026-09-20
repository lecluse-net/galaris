from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastmcp import FastMCP


def _server(*names):
    server = FastMCP("catalog-contract")
    for name in names:
        server.tool(name=name)(lambda: "ok")
    return server


def test_agent_context_routes_youtube_urls_through_audio_transcribe() -> None:
    from app.tools import agent_registry

    instructions = agent_registry._TOOL_CONTEXT_TEMPLATE  # pyright: ignore[reportPrivateUsage]

    assert "public YouTube video URL" in instructions
    assert "audio_transcribe(file='<exact HTTPS YouTube URL>')" in instructions
    assert "do not fall back to console downloaders" in instructions


def test_agent_context_exposes_only_one_local_filesystem() -> None:
    from app.tools import agent_registry

    instructions = agent_registry._TOOL_CONTEXT_TEMPLATE  # pyright: ignore[reportPrivateUsage]

    assert "there is no local file fallback" in instructions
    assert "## File tools" in instructions
    assert "workspace://" not in instructions
    assert "## Workspace tools" not in instructions


@pytest.mark.asyncio
async def test_internal_mcp_toolset_uses_internal_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.harness import mcp_toolset

    calls: list[tuple[int, str, object]] = []

    async def fake_build_agent_mcp(
        agent_id: int,
        *,
        runtime: str = "hermes",
        task_id: object = None,
        resources: dict[str, object] | None = None,
    ) -> object:
        assert resources is None
        calls.append((agent_id, runtime, task_id))
        return _server("task_get")

    monkeypatch.setattr("app.tools.mcp_loader.build_agent_mcp", fake_build_agent_mcp)

    task_id = uuid4()
    toolset = await mcp_toolset.build_agent_mcp_toolset(12, task_id=task_id)

    assert calls == [(12, "internal", task_id)]
    assert toolset.id == "agent-mcp-12"
    assert toolset.max_retries == 3
    assert toolset.cache_tools is False
    async with toolset:
        assert set(await toolset.get_tools(None)) == {"task_get"}


@pytest.mark.asyncio
async def test_internal_mcp_toolset_defers_tools_outside_preselected_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.harness import mcp_toolset
    from app.tools import metrics
    mcp = _server("search_web", "nc_delete")
    monkeypatch.setattr(
        "app.tools.mcp_loader.build_agent_mcp",
        AsyncMock(return_value=mcp),
    )
    observed: list[tuple[bool, int]] = []
    monkeypatch.setattr(
        metrics,
        "observe_catalog_snapshot",
        lambda *, matches, missing_eager_tools: observed.append(
            (matches, missing_eager_tools)
        ),
    )

    toolset = await mcp_toolset.build_agent_mcp_toolset(
        12,
        eager_tool_names={"search_web", "tool_removed_after_planning"},
        expected_catalog_version="outdated-version",
    )

    async with toolset:
        definitions = await toolset.get_tools(None)
        assert definitions["nc_delete"].tool_def.defer_loading is True
        assert definitions["search_web"].tool_def.defer_loading is not True
    assert observed == [(False, 1)]


@pytest.mark.asyncio
async def test_resource_uri_tools_are_available_to_both_runtimes() -> None:
    from app.tools import agent_registry

    internal_mcp = agent_registry.build_galaris_fastmcp(
        12,
        runtime="internal",
        enabled_tool_codes={"file_sharing"},
    )
    internal_names = {tool.name for tool in await internal_mcp.list_tools()}

    hermes_mcp = agent_registry.build_galaris_fastmcp(
        12,
        runtime="hermes",
        enabled_tool_codes={"file_sharing"},
    )
    hermes_names = {tool.name for tool in await hermes_mcp.list_tools()}

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
    } <= internal_names
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
    } <= hermes_names


@pytest.mark.asyncio
async def test_tool_advertisement_contains_only_projected_native_functions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import agent_registry, mcp_loader

    async def noop() -> None:
        return None

    definitions = (
        mcp_loader.McpToolDefinition(
            tool_code="galaris",
            name="tools_list",
            description="List tools.",
            required_capabilities=frozenset(),
            function=noop,
        ),
        mcp_loader.McpToolDefinition(
            tool_code="galaris",
            name="process_start",
            description="Start process.",
            required_capabilities=frozenset(),
            function=noop,
        ),
    )
    projected = AsyncMock(return_value=definitions)
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", projected)

    advertisement = await agent_registry.build_agent_tool_advertisement(
        12,
        runtime="internal",
        allowed_tool_names={"tools_list", "process_start"},
    )

    assert advertisement.tool_names == frozenset({"tools_list", "process_start"})
    assert "`galaris`: `tools_list`, `process_start`" in advertisement.text
    assert "inactive_tool" not in advertisement.text
    projected.assert_awaited_once_with(
        12,
        runtime="internal",
        allowed_tool_names={"tools_list", "process_start"},
        conversation_only=False,
        resources=None,
    )


@pytest.mark.asyncio
async def test_conversation_advertisement_lists_only_task_only_application_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import agent_registry, mcp_loader

    async def noop() -> None:
        return None

    definitions = (
        mcp_loader.McpToolDefinition(
            tool_code="search",
            name="search_web",
            description="Search the web.",
            required_capabilities=frozenset(),
            function=noop,
            conversation_policy="short",
        ),
    )
    monkeypatch.setattr(
        mcp_loader,
        "list_enabled_native_mcp_definitions",
        AsyncMock(return_value=definitions),
    )
    monkeypatch.setattr(
        "app.connection.facade.get_connections_by_agent",
        AsyncMock(
            return_value=[
                SimpleNamespace(tool_id=1),
                SimpleNamespace(tool_id=2),
                SimpleNamespace(tool_id=3),
            ]
        ),
    )
    tools = {
        1: SimpleNamespace(
            code="gitlab",
            label="GitLab",
            conversation_enabled=False,
        ),
        2: SimpleNamespace(
            code="search",
            label="Web search",
            conversation_enabled=True,
        ),
        3: SimpleNamespace(
            code="audio",
            label="Audio",
            conversation_enabled=False,
        ),
    }
    monkeypatch.setattr(
        "app.tools.tool_service.get_tool_by_id",
        AsyncMock(side_effect=lambda tool_id: tools[tool_id]),
    )

    advertisement = await agent_registry.build_agent_tool_advertisement(
        12,
        runtime="internal",
        conversation_only=True,
        include_task_only_tools=True,
    )

    assert advertisement.tool_names == frozenset({"search_web"})
    assert "## Task-only Tools" in advertisement.text
    assert '{"code": "audio", "label": "Audio"}' in advertisement.text
    assert '{"code": "gitlab", "label": "GitLab"}' in advertisement.text
    assert '{"code": "search", "label": "Web search"}' not in advertisement.text
    assert "launching a Task with `conversation_task_submit` is mandatory" in advertisement.text
    assert "Never claim that the agent lacks access" in advertisement.text


@pytest.mark.asyncio
async def test_tool_advertisement_exposes_one_local_filesystem_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import agent_registry, mcp_loader

    async def noop() -> None:
        return None

    definitions = tuple(
        mcp_loader.McpToolDefinition(
            tool_code=tool_code,
            name=name,
            description=name,
            required_capabilities=frozenset(),
            function=noop,
        )
        for tool_code, name in (
            ("file_sharing", "file_schemes"),
            ("console", "console_exec"),
        )
    )
    monkeypatch.setattr(
        mcp_loader,
        "list_enabled_native_mcp_definitions",
        AsyncMock(return_value=definitions),
    )

    advertisement = await agent_registry.build_agent_tool_advertisement(
        12,
        runtime="internal",
    )

    assert "Use `console://` as the only local filesystem" in advertisement.text
    assert "Runtime staging is server-managed" in advertisement.text
    assert "workspace://" not in advertisement.text


@pytest.mark.asyncio
async def test_conversation_toolset_uses_complete_checked_tool_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.harness import mcp_toolset
    server = _server("conversation_task_submit")
    built = AsyncMock(return_value=server)

    monkeypatch.setattr("app.tools.mcp_loader.build_agent_mcp", built)
    resources = {"conversation_turn": object()}

    toolset = await mcp_toolset.build_conversation_toolset(12, resources=resources)

    built.assert_awaited_once_with(
        12,
        runtime="internal",
        task_id=None,
        resources=resources,
        conversation_only=True,
        allowed_tool_names=None,
    )
    async with toolset:
        assert set(await toolset.get_tools(None)) == {"conversation_task_submit"}


@pytest.mark.asyncio
async def test_native_compatibility_toolsets_keep_short_mcp_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.harness import mcp_toolset
    complete_server = _server("task_get", "task_create")
    agent_server = _server("task_get")
    monkeypatch.setattr(
        mcp_toolset,
        "build_galaris_fastmcp",
        lambda *_args, **_kwargs: complete_server,
    )
    monkeypatch.setattr(
        mcp_toolset,
        "build_agent_galaris_fastmcp",
        AsyncMock(return_value=agent_server),
    )

    complete = mcp_toolset.build_galaris_toolset(12)
    agent = await mcp_toolset.build_agent_galaris_toolset(12)

    async with complete, agent:
        assert set(await complete.get_tools(None)) == {"task_get", "task_create"}
        assert set(await agent.get_tools(None)) == {"task_get"}


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["internal", "hermes"])
@pytest.mark.parametrize(
    ("names", "expects_documents", "expects_sharing"),
    [
        (("file_create", "file_search", "memory_sharing", "document_share"), True, True),
        (("file_create", "memory_remember"), True, False),
        (("file_create", "document_share"), True, False),
        (("file_create", "file_search"), False, False),
        (("memory_sharing", "document_share"), False, False),
        ((), False, False),
    ],
)
async def test_tool_advertisement_encourages_shared_documents_when_available(
    monkeypatch: pytest.MonkeyPatch,
    runtime: str,
    names: tuple[str, ...],
    expects_documents: bool,
    expects_sharing: bool,
) -> None:
    from app.tools import agent_registry, mcp_loader

    async def noop() -> None:
        return None

    definitions = tuple(
        mcp_loader.McpToolDefinition(
            tool_code="file_sharing" if name.startswith("file_") else "memory",
            name=name,
            description=name,
            required_capabilities=frozenset(),
            function=noop,
        )
        for name in names
    )
    monkeypatch.setattr(
        mcp_loader,
        "list_enabled_native_mcp_definitions",
        AsyncMock(return_value=definitions),
    )

    advertisement = await agent_registry.build_agent_tool_advertisement(
        12,
        runtime=runtime,
    )

    assert advertisement.tool_names == frozenset(names)
    assert ("file_create(path='document://'" in advertisement.text) is expects_documents
    assert ("document_share(document_id=" in advertisement.text) is expects_sharing
    if expects_documents:
        assert "Prefer document:// over standalone" in advertisement.text
        assert "Markdown (.md) or HTML (.html)" in advertisement.text
        assert "editorial HTML fragment" in advertisement.text
    if expects_sharing:
        assert "expected_lock_version" in advertisement.text
        assert "does not grant access" in advertisement.text


@pytest.mark.asyncio
async def test_tool_advertisement_requires_memory_lookup_for_named_mail_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import agent_registry, mcp_loader

    async def noop() -> None:
        return None

    definitions = tuple(
        mcp_loader.McpToolDefinition(
            tool_code="mail" if name == "mail_send" else "file_sharing",
            name=name,
            description=name,
            required_capabilities=frozenset(),
            function=noop,
        )
        for name in ("mail_send", "file_search", "file_read")
    )
    monkeypatch.setattr(
        mcp_loader,
        "list_enabled_native_mcp_definitions",
        AsyncMock(return_value=definitions),
    )

    advertisement = await agent_registry.build_agent_tool_advertisement(
        12,
        runtime="internal",
    )

    assert "file_search(uri='memory://'" in advertisement.text
    assert "Never invent or infer an address" in advertisement.text
    assert "If no unique contact matches" in advertisement.text
