import asyncio
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import UUID, uuid4

import pytest

# pyright: reportPrivateUsage=false


@pytest.fixture(autouse=True)
def default_harness_configuration(monkeypatch):
    # These tool-projection units isolate persistence. Revisioned policies are exercised
    # with a real database in harnesses/tests/test_execution_configuration.py.
    from app.agent import agent_service
    from app.agent.contracts import HarnessExecutionPolicy
    from app.agent.harness_port import harness_selection_port

    monkeypatch.setattr(agent_service, "get", AsyncMock(return_value=SimpleNamespace(id=7)))
    monkeypatch.setattr(harness_selection_port, "resolve", AsyncMock(return_value=None))
    monkeypatch.setattr(harness_selection_port, "configuration", AsyncMock(return_value=(HarnessExecutionPolicy(), 0)))


@pytest.mark.asyncio
@pytest.mark.parametrize("user_language,conversation_language,expected", [
    ("fr", "en", "fr"),
    (None, "zh", "zh"),
    (None, None, "en"),
])
async def test_taskless_tools_preserve_user_or_conversation_language(
    monkeypatch, user_language, conversation_language, expected,
):
    from app.tools.mcp_loader import McpToolContext, context_language
    from core.params import runtime_settings

    monkeypatch.setattr(runtime_settings, "DEFAULT_LANGUAGE", "")
    monkeypatch.setattr(
        "core.user.user_service.get_current_user",
        AsyncMock(return_value=SimpleNamespace(language=user_language) if user_language else None),
    )
    ctx = McpToolContext(
        agent_id=7, runtime="internal",
        resources={"conversation_turn": SimpleNamespace(language=conversation_language)},
    )

    assert await context_language(ctx) == expected


@pytest.mark.asyncio
async def test_execute_native_tool_reuses_authorization_and_effect_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import mcp_loader, resource_effects

    observed: dict[str, object] = {}

    async def native(ctx: object, room_id: str) -> str:
        observed["ctx"] = ctx
        observed["room_id"] = room_id
        return "sent"

    definition = mcp_loader.McpToolDefinition(
        tool_code="messenger",
        name="messenger_room_send_file",
        description="Send.",
        required_capabilities=frozenset(),
        function=native,
    )
    projection = AsyncMock(return_value=(definition,))
    effects = AsyncMock()
    monkeypatch.setattr(
        mcp_loader,
        "list_enabled_native_mcp_definitions",
        projection,
    )
    monkeypatch.setattr(resource_effects, "record_tool_resources", effects)
    task_id = uuid4()

    result = await mcp_loader.execute_native_mcp_tool(
        7,
        runtime="internal",
        task_id=task_id,
        tool_name="messenger_room_send_file",
        arguments={"room_id": "room-1"},
    )

    assert result == "sent"
    assert observed["room_id"] == "room-1"
    ctx = observed["ctx"]
    assert isinstance(ctx, mcp_loader.McpToolContext)
    assert ctx.task_id == task_id
    projection.assert_any_await(
        7,
        runtime="internal",
        allowed_tool_names={"messenger_room_send_file"},
    )
    assert projection.await_count == 2
    projection.assert_awaited_with(
        7, runtime="internal", conversation_only=False,
        allowed_tool_names={"messenger_room_send_file"}, resources={},
    )
    effects.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_tool_timeout_is_bounded_and_cancels_the_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastmcp.exceptions import ToolError

    from app.tools import mcp_loader

    cancelled = asyncio.Event()

    async def stalled(_ctx: object) -> str:
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    definition = mcp_loader.McpToolDefinition(
        tool_code="file_sharing",
        name="file_edit",
        description="Edit.",
        required_capabilities=frozenset(),
        function=stalled,
        timeout_seconds=0.01,
    )
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    wrapper = mcp_loader._wrap_tool(  # pyright: ignore[reportPrivateUsage]
        definition,
        mcp_loader.McpToolContext(agent_id=7, runtime="internal"),
    )

    with pytest.raises(ToolError):
        await wrapper()

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_parallel_native_tools_receive_distinct_database_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.database import get_db
    from app.tools import mcp_loader, resource_effects

    sessions: set[int] = set()
    active = 0
    max_active = 0

    async def native(_ctx: object, value: str) -> str:
        nonlocal active, max_active
        sessions.add(id(get_db()))
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return value

    monkeypatch.setattr(resource_effects, "record_tool_resources", AsyncMock())
    definition = mcp_loader.McpToolDefinition(
        tool_code="search",
        name="parallel_read",
        description="Read concurrently.",
        required_capabilities=frozenset(),
        function=native,
        effect_policy="read",
        concurrency_policy="safe",
    )
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    wrapper = mcp_loader._wrap_tool(  # pyright: ignore[reportPrivateUsage]
        definition,
        mcp_loader.McpToolContext(agent_id=7, runtime="internal"),
    )

    assert await asyncio.gather(wrapper(value="a"), wrapper(value="b")) == ["a", "b"]
    assert max_active == 2
    assert len(sessions) == 2


@pytest.mark.asyncio
async def test_recoverable_native_tool_error_keeps_its_actionable_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastmcp.exceptions import ToolError

    from app.tools import mcp_loader, tool_errors

    async def native(_ctx: object) -> str:
        raise tool_errors.RecoverableToolError(
            "No recent room was found for Alice; ask her to send a message first."
        )

    definition = mcp_loader.McpToolDefinition(
        tool_code="messenger",
        name="messenger_send_audio_message",
        description="Send audio.",
        required_capabilities=frozenset(),
        function=native,
    )
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    wrapper = mcp_loader._wrap_tool(  # pyright: ignore[reportPrivateUsage]
        definition,
        mcp_loader.McpToolContext(agent_id=7, runtime="internal"),
    )

    with pytest.raises(ToolError, match="No recent room was found for Alice"):
        await wrapper()


def test_mcp_loader_discovers_decorated_tools_by_tool_code() -> None:
    from app.tools.mcp_loader import mcp_tool_names_by_tool_code

    names = mcp_tool_names_by_tool_code()

    assert "search_web" in names["search"]
    assert {
        "agent_list",
        "task_get",
        "task_run",
        "task_stop",
        "goal_update_suivi",
        "goal_run_now",
        "goal_ask_referrer",
        "process_list",
        "process_get",
        "process_start",
        "process_list_runs",
        "process_get_run",
        "process_analyze_run",
    } <= set(names["galaris"])
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
    } == set(names["file_sharing"])
    assert {
        "task",
        "task_list_running",
        "task_list_paused",
        "tasks",
        "goal_list",
        "goal_get",
        "goal_get_suivi",
        "file_upload",
        "file_download",
        "file_transfer",
        "file_targets",
        "file_schemes",
        "file_list",
        "file_read",
    }.isdisjoint(names["galaris"])
    assert {
        "messenger_room_send_message",
        "messenger_send_audio_message",
    } <= set(names["messenger"])
    assert {
        "messenger_list_attachments",
        "messenger_read_attachment",
        "messenger_room_resend_attachment",
    }.isdisjoint(names["messenger"])
    assert {
        "memory_search",
        "memory_get",
        "memory_index",
        "document_read",
        "document_append",
    }.isdisjoint(names["memory"])
    assert all(name.startswith("messenger_") for name in names["messenger"])
    assert {"image_generate", "image_read"} <= set(names["image"])
    assert names["audio"] == ("audio_transcribe",)
    assert {
        "goal_create",
        "goal_update",
        "goal_pause",
        "goal_resume",
        "goal_complete",
        "goal_delete",
    } == set(names["goal_management"])
    assert {"skills_list", "skill_read"} == set(names["skill_management"])
    assert {
        "process_admin_engines",
        "process_admin_sync",
        "process_admin_list",
        "process_admin_get",
        "process_admin_create",
        "process_admin_update",
        "process_admin_delete",
        "process_admin_start",
        "process_admin_list_runs",
        "process_admin_get_run",
        "process_admin_refresh_run",
        "process_admin_cancel_run",
        "process_admin_retry_run",
        "process_admin_analyze_run",
        "process_admin_delete_run",
    } == set(names["process_admin"])
    assert {"conversation_round_get", "voice_turn_get", "llm_call", "llm_calls"} == set(
        names["galaris_admin"]
    )
    assert {
        "topic_list",
        "topic_get",
        "topic_items_list",
        "topic_create",
        "topic_update",
        "topic_item_move",
        "topic_merge",
        "topic_split",
    } == set(names["topic"])


def test_tool_execution_policy_is_explicit_and_conservative() -> None:
    from app.tools.mcp_loader import execution_policy_for_tool

    assert execution_policy_for_tool("search_web") == ("read", "safe")
    assert execution_policy_for_tool("agent_list") == ("read", "safe")
    assert execution_policy_for_tool("agent_get") == ("read", "safe")
    for name in (
        "file_schemes",
        "file_list",
        "file_info",
        "file_search",
        "file_read",
    ):
        assert execution_policy_for_tool(name) == ("read", "safe")
    # Image analysis now persists its description in Memory.
    assert execution_policy_for_tool("image_read") == ("non_idempotent", "exclusive")
    assert execution_policy_for_tool("unknown_external_tool") == (
        "non_idempotent",
        "exclusive",
    )


def test_tool_code_does_not_implicitly_authorize_messenger() -> None:
    from app.tools.mcp_loader import native_tool_codes_for_connection

    for code in ("nextcloud", "matrix", "telegram", "whatsapp", "one_bot"):
        assert native_tool_codes_for_connection(code) == frozenset({code})


def test_disabled_bridge_removes_only_explicit_messaging_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bridge.matrix  # noqa: F401
    from app.tools.mcp_loader import native_tool_codes_for_tool
    from core.params.runtime_settings import runtime_settings

    tool = SimpleNamespace(
        code="my-matrix",
        messenger=SimpleNamespace(service="matrix"),
    )
    assert native_tool_codes_for_tool(tool) == frozenset(
        {"my-matrix", "messenger"}
    )

    monkeypatch.setattr(
        runtime_settings,
        "MESSENGER_ENABLED_CHANNELS",
        '["telegram"]',
    )

    assert native_tool_codes_for_tool(tool) == frozenset({"my-matrix"})


def test_concrete_tool_requires_explicit_messenger_capability() -> None:
    import bridge.matrix  # noqa: F401
    from app.tools.mcp_loader import native_tool_codes_for_tool

    ordinary = SimpleNamespace(code="messenger", messenger=None)
    configured = SimpleNamespace(
        code="my-chat",
        messenger=SimpleNamespace(service="matrix"),
    )

    assert "messenger" not in native_tool_codes_for_tool(ordinary)
    assert "messenger" in native_tool_codes_for_tool(configured)


@pytest.mark.asyncio
async def test_agent_catalog_accumulates_mcp_messenger_and_file_share_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import agent
    from app.connection import facade as connection_service
    from app.tools import mcp_loader, tool_service

    connection = SimpleNamespace(id=11, tool_id=35, active=True)
    record = SimpleNamespace(
        id=35,
        code="nextcloud",
        label="Nextcloud",
        description="Combined Nextcloud services.",
    )
    tool = SimpleNamespace(
        code="nextcloud",
        mcp=SimpleNamespace(type="http"),
        messenger=SimpleNamespace(service="nextcloud_talk"),
        file_share=SimpleNamespace(service="nextcloud"),
    )
    native_definition = SimpleNamespace(
        name="messenger_room_send_message",
        description="Send a message.",
        required_capabilities=frozenset(),
    )
    profile = SimpleNamespace(supports=lambda _capabilities: True)

    monkeypatch.setattr(
        agent.agent_service,
        "get",
        AsyncMock(return_value=SimpleNamespace(agent_driver="hermes")),
    )
    monkeypatch.setattr(agent, "validate_agent_driver", lambda *_args, **_kwargs: "hermes")
    monkeypatch.setattr(agent, "resolve_tool_profile", lambda _runtime: profile)
    monkeypatch.setattr(
        connection_service,
        "get_connections_by_agent",
        AsyncMock(return_value=[connection]),
    )
    monkeypatch.setattr(
        connection_service,
        "get_disabled_function_names",
        AsyncMock(return_value={"nc_notes_create_note"}),
    )
    monkeypatch.setattr(
        connection_service,
        "get_params_as_dict",
        AsyncMock(return_value=(connection, {"login": "nicolas"})),
    )
    monkeypatch.setattr(
        tool_service,
        "get_all_tool_records",
        AsyncMock(return_value=[record]),
    )
    monkeypatch.setattr(tool_service, "_to_internal", lambda _record: tool)
    monkeypatch.setattr(
        mcp_loader,
        "mcp_tools_by_tool_code",
        lambda: {"messenger": [native_definition]},
    )
    monkeypatch.setattr(
        mcp_loader,
        "native_tool_codes_for_tool",
        lambda _tool: frozenset({"messenger", "nextcloud"}),
    )
    external_functions = AsyncMock(return_value=[
        ("nc_notes_create_note", "Create a note."),
        ("nc_webdav_list_directory", "List a WebDAV directory."),
    ])
    monkeypatch.setattr(
        mcp_loader,
        "list_external_mcp_functions",
        external_functions,
    )

    groups = await mcp_loader.list_agent_mcp_tools(agent_id=1)

    assert len(groups) == 1
    assert groups[0]["source"] == "mixed"
    assert {
        item["name"]: item["enabled"]
        for item in groups[0]["mcp_tools"]
    } == {
        "messenger_room_send_message": True,
        "nc_notes_create_note": False,
        "nc_webdav_list_directory": True,
    }
    external_functions.assert_awaited_once_with(tool, {"login": "nicolas"})


@pytest.mark.asyncio
async def test_enabled_native_definition_projection_applies_every_visibility_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import mcp_loader

    async def enabled(_agent_id: int) -> set[str]:
        return {"galaris", "file_sharing"}

    async def disabled(_agent_id: int) -> set[str]:
        return {"task_stop"}

    monkeypatch.setattr(mcp_loader, "get_enabled_integrated_tool_codes", enabled)
    monkeypatch.setattr(mcp_loader, "get_disabled_internal_function_names", disabled)

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="hermes",
        allowed_tool_names={
            "file_list",
            "process_list",
            "process_start",
            "task_stop",
        },
    )

    assert [definition.name for definition in definitions] == [
        "file_list",
        "process_list",
        "process_start",
    ]


@pytest.mark.asyncio
async def test_conversation_projection_intersects_checkbox_and_function_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import mcp_loader

    async def enabled(_agent_id: int) -> set[str]:
        return {"galaris", "conversation", "memory", "file_sharing"}

    async def disabled(_agent_id: int) -> set[str]:
        return set()

    checked_tools = SimpleNamespace(all=lambda: [
        SimpleNamespace(code="galaris", messenger_config=None),
        SimpleNamespace(code="conversation", messenger_config=None),
        SimpleNamespace(code="file_sharing", messenger_config=None),
    ])
    db = SimpleNamespace(scalars=AsyncMock(return_value=checked_tools))
    monkeypatch.setattr(mcp_loader, "get_enabled_integrated_tool_codes", enabled)
    monkeypatch.setattr(mcp_loader, "get_disabled_internal_function_names", disabled)
    monkeypatch.setattr(mcp_loader, "get_db", lambda: db)

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="internal",
        allowed_tool_names={
            "conversation_task_status",
            "file_search",
            "process_start",
        },
        conversation_only=True,
    )

    assert {definition.name for definition in definitions} == {
        "conversation_task_status",
        "file_search",
    }


@pytest.mark.asyncio
async def test_conversation_projection_keeps_voice_stop_as_call_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import mcp_loader

    monkeypatch.setattr(
        mcp_loader,
        "get_enabled_integrated_tool_codes",
        AsyncMock(return_value={"voice"}),
    )
    monkeypatch.setattr(
        mcp_loader,
        "get_disabled_internal_function_names",
        AsyncMock(return_value=set()),
    )
    checked_tools = SimpleNamespace(all=lambda: [])
    monkeypatch.setattr(
        mcp_loader,
        "get_db",
        lambda: SimpleNamespace(scalars=AsyncMock(return_value=checked_tools)),
    )

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="internal",
        conversation_only=True,
    )

    assert {definition.name for definition in definitions} == {"voice_call_stop"}


@pytest.mark.asyncio
async def test_task_projection_excludes_conversation_control_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import mcp_loader

    monkeypatch.setattr(
        mcp_loader,
        "get_enabled_integrated_tool_codes",
        AsyncMock(return_value={"galaris"}),
    )
    monkeypatch.setattr(
        mcp_loader,
        "get_disabled_internal_function_names",
        AsyncMock(return_value=set()),
    )

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="internal",
        allowed_tool_names={"conversation_task_submit", "conversation_task_status"},
    )

    assert definitions == ()


@pytest.mark.asyncio
async def test_checked_search_is_available_in_conversation_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import mcp_loader

    monkeypatch.setattr(
        mcp_loader,
        "get_enabled_integrated_tool_codes",
        AsyncMock(return_value={"search"}),
    )
    monkeypatch.setattr(
        mcp_loader,
        "get_disabled_internal_function_names",
        AsyncMock(return_value=set()),
    )
    checked_tools = SimpleNamespace(
        all=lambda: [SimpleNamespace(code="search", messenger_config=None)]
    )
    monkeypatch.setattr(
        mcp_loader,
        "get_db",
        lambda: SimpleNamespace(scalars=AsyncMock(return_value=checked_tools)),
    )

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="internal",
        conversation_only=True,
    )

    assert [definition.name for definition in definitions] == ["search_web"]


@pytest.mark.asyncio
async def test_conversation_projection_maps_checked_bridge_to_messenger_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import mcp_loader

    monkeypatch.setattr(
        mcp_loader,
        "get_enabled_integrated_tool_codes",
        AsyncMock(return_value={"my-chat", "messenger"}),
    )
    monkeypatch.setattr(
        mcp_loader,
        "get_disabled_internal_function_names",
        AsyncMock(return_value=set()),
    )
    checked_tools = SimpleNamespace(
        all=lambda: [
            SimpleNamespace(
                code="my-chat",
                messenger_config={"service": "telegram"},
            )
        ]
    )
    monkeypatch.setattr(
        mcp_loader,
        "get_db",
        lambda: SimpleNamespace(scalars=AsyncMock(return_value=checked_tools)),
    )

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="internal",
        allowed_tool_names={"messenger_room_history"},
        conversation_only=True,
    )

    assert [definition.name for definition in definitions] == [
        "messenger_room_history"
    ]


@pytest.mark.asyncio
async def test_conversation_aggregate_skips_unchecked_external_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastmcp import FastMCP

    from app.connection import facade as connection_service
    from app.tools import mcp_loader, tool_service

    connection = SimpleNamespace(id=9, tool_id=3, active=True)
    unchecked_tool = SimpleNamespace(
        code="external",
        mcp=SimpleNamespace(type="http"),
        conversation_enabled=False,
    )
    native = FastMCP("native")
    native_builder = AsyncMock(return_value=native)
    params = AsyncMock(side_effect=AssertionError("unchecked MCP must not be resolved"))
    monkeypatch.setattr(
        connection_service,
        "get_connections_by_agent",
        AsyncMock(return_value=[connection]),
    )
    monkeypatch.setattr(connection_service, "get_params_as_dict", params)
    monkeypatch.setattr(
        tool_service,
        "get_tool_by_id",
        AsyncMock(return_value=unchecked_tool),
    )
    monkeypatch.setattr(
        mcp_loader,
        "build_agent_galaris_fastmcp",
        native_builder,
    )

    server = await mcp_loader.build_agent_mcp(
        42,
        runtime="internal",
        conversation_only=True,
    )

    native_builder.assert_awaited_once_with(
        42,
        runtime="internal",
        task_id=None,
        resources=ANY,
        allowed_tool_names=None,
        conversation_only=True,
    )
    # Discovery observes this exact run's server, including tools mounted later.
    run_tool_names = native_builder.await_args.kwargs["resources"]["run_tool_names"]
    assert await run_tool_names() == frozenset()

    @server.tool()
    async def mounted_in_this_run() -> str:
        return "ok"

    assert await run_tool_names() == frozenset({"mounted_in_this_run"})
    params.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_loader_filters_by_tool_and_runtime() -> None:
    from app.tools.mcp_loader import build_galaris_fastmcp

    internal_mcp = build_galaris_fastmcp(
        1,
        runtime="internal",
        enabled_tool_codes={"voice", "galaris", "file_sharing"},
    )
    internal_tools = {tool.name: tool for tool in await internal_mcp.list_tools()}
    internal_names = set(internal_tools)

    hermes_mcp = build_galaris_fastmcp(
        1,
        runtime="hermes",
        enabled_tool_codes={"voice", "galaris", "file_sharing"},
    )
    hermes_names = {tool.name for tool in await hermes_mcp.list_tools()}

    management_mcp = build_galaris_fastmcp(
        1,
        runtime="internal",
        enabled_tool_codes={
            "goal_management",
            "skill_management",
            "process_admin",
            "galaris_admin",
        },
    )
    management_names = {tool.name for tool in await management_mcp.list_tools()}

    assert "voice_call_start" in internal_names
    assert "file_list" in internal_names
    assert {
        "goal_update_suivi",
        "goal_run_now",
        "goal_ask_referrer",
    } <= internal_names
    assert {"goal_list", "goal_get", "goal_get_suivi"}.isdisjoint(internal_names)
    assert "voice_call_start" in hermes_names
    assert "file_list" in hermes_names
    assert {
        "goal_create",
        "goal_update",
        "goal_pause",
        "goal_resume",
        "goal_complete",
        "goal_delete",
        "skills_list",
        "skill_read",
    } <= management_names
    assert "process_admin_create" in management_names
    assert "process_admin_delete_run" in management_names
    assert {"conversation_round_get", "voice_turn_get"} <= management_names


@pytest.mark.asyncio
async def test_wrapped_mcp_tool_returns_recoverable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastmcp.exceptions import ToolError

    from app.tools.mcp_loader import McpToolContext, McpToolDefinition, _wrap_tool

    sentinel = "synthetic-external-error-secret-never-return"

    async def broken_tool(ctx: McpToolContext, path: str) -> str:
        raise ValueError(sentinel)

    definition = McpToolDefinition(
        tool_code="demo",
        name="file_list",
        description="Demo",
        required_capabilities=frozenset({"file_tools"}),
        function=broken_tool,
    )
    async def english_language(_ctx: McpToolContext) -> str:
        return "en"

    monkeypatch.setattr("app.tools.mcp_loader.context_language", english_language)
    monkeypatch.setattr("app.tools.mcp_loader.list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    wrapped = _wrap_tool(definition, McpToolContext(agent_id=1, runtime="internal"))

    with pytest.raises(ToolError) as caught:
        await wrapped(path="/")

    message = str(caught.value)
    assert "Tool 'file_list' failed" in message
    assert "Cause: The arguments or current resource state were rejected." in message
    assert "Technical type: ValueError." in message
    assert "Re-read the function schema" in message
    assert "Error reference:" in message
    assert sentinel not in message


@pytest.mark.asyncio
async def test_file_create_reports_missing_remote_parent_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastmcp.exceptions import ToolError

    from app.tools import mcp_loader

    class SFTPNoSuchFile(Exception):
        pass

    async def broken_create(_ctx: object, path: str) -> str:
        del path
        raise SFTPNoSuchFile("No such file")

    definition = mcp_loader.McpToolDefinition(
        tool_code="file_sharing",
        name="file_create",
        description="Create.",
        required_capabilities=frozenset(),
        function=broken_create,
    )

    async def french_language(_ctx: mcp_loader.McpToolContext) -> str:
        return "fr"

    monkeypatch.setattr(mcp_loader, "context_language", french_language)
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    wrapped = mcp_loader._wrap_tool(  # pyright: ignore[reportPrivateUsage]
        definition,
        mcp_loader.McpToolContext(agent_id=7, runtime="internal"),
    )

    with pytest.raises(ToolError) as caught:
        await wrapped(path="console://reports/result.md")

    message = str(caught.value)
    assert "SFTPNoSuchFile" in message
    assert "Le répertoire parent de destination est introuvable" in message
    assert "file_list" in message
    assert "Référence d’erreur" in message


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (FileNotFoundError(), "not_found"),
        (FileExistsError(), "already_exists"),
        (type("SFTPNoSuchPath", (Exception,), {})(), "not_found"),
        (type("SFTPFileAlreadyExists", (Exception,), {})(), "already_exists"),
        (type("SFTPWriteProtect", (Exception,), {})(), "permission_denied"),
        (type("SFTPNoSpaceOnFilesystem", (Exception,), {})(), "capacity"),
        (type("SFTPNotADirectory", (Exception,), {})(), "invalid_arguments"),
        (type("SFTPConnectionLost", (Exception,), {})(), "connection"),
        (PermissionError(), "permission_denied"),
        (NotImplementedError(), "unsupported"),
        (TimeoutError(), "timeout"),
        (ConnectionError(), "connection"),
        (OSError(28, "No space left"), "capacity"),
        (type("GoalRevisionConflict", (RuntimeError,), {})("reload goal"), "actionable"),
        (type("MemoryConflictError", (RuntimeError,), {})("reload document"), "actionable"),
        (RuntimeError(), "unexpected"),
    ],
)
def test_native_tool_failures_have_stable_actionable_categories(
    exc: Exception,
    kind: str,
) -> None:
    from app.tools import tool_errors

    failure = tool_errors.classify_tool_failure(exc)

    assert failure.kind == kind


@pytest.mark.parametrize("language,remote_reason", [
    ("fr", "Le service distant a refusé l’accès (HTTP 403)."),
    ("en", "The remote service denied access (HTTP 403)."),
])
def test_http_forbidden_distinguishes_remote_refusal_without_exposing_secrets(
    language: str, remote_reason: str,
) -> None:
    import httpx

    from app.tools import tool_errors

    request = httpx.Request("GET", "https://example.org/private?token=secret-query-value")
    response = httpx.Response(403, request=request, text="secret-provider-response")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        failure = tool_errors.classify_tool_failure(exc)
    else:
        raise AssertionError("HTTP 403 should fail")

    # Only the diagnostic changes; effect/retry classification stays identical.
    assert failure.kind == "permission_denied"
    message = tool_errors.render_tool_failure(
        tool_name="file_read", failure=failure, language=language, reference="test-ref",
    )
    assert remote_reason in message
    assert "test-ref" in message
    assert "secret-query-value" not in message
    assert "secret-provider-response" not in message
    assert "example.org" not in message

    local_failure = tool_errors.classify_tool_failure(PermissionError("private detail"))
    local_message = tool_errors.render_tool_failure(
        tool_name="file_read", failure=local_failure, language=language, reference="local-ref",
    )
    assert local_failure.kind == "permission_denied"
    assert remote_reason not in local_message
    assert "HTTP 403" not in local_message


def test_safe_domain_cause_does_not_expose_an_arbitrary_wrapper() -> None:
    from app.file_share.resource_uri import ResourceValidationError
    from app.tools.tool_errors import classify_tool_failure

    failure = ValueError("private provider wrapper")
    failure.__cause__ = ResourceValidationError("Read the current revision before editing.")
    diagnostic = classify_tool_failure(failure)
    assert diagnostic.kind == "actionable"
    assert diagnostic.detail == "Read the current revision before editing."


def test_native_mcp_validation_detail_is_precise_and_secret_redacted() -> None:
    from app.file_share.mcp import _decode_content
    from app.tools import tool_errors

    try:
        _decode_content("not-base64", "base64")
    except ValueError as exc:
        failure = tool_errors.classify_tool_failure(exc)
    else:
        raise AssertionError("invalid base64 should fail")

    assert failure.kind == "invalid_arguments"
    assert failure.detail == "content must be valid base64 when encoding='base64'."

    safe = tool_errors.classify_tool_failure(
        tool_errors.RecoverableToolError(
            "provider rejected api_key=sk-secret-value-that-must-not-leak"
        )
    )
    assert safe.detail == "provider rejected api_key=[redacted]"


@pytest.mark.parametrize("status,kind", [(400, "provider"), (401, "authentication"), (429, "rate_limited"), (503, "provider")])
def test_internal_model_rejection_is_not_an_mcp_argument_error(status, kind) -> None:
    from pydantic_ai.exceptions import ModelHTTPError
    from app.tools.tool_errors import classify_tool_failure

    error = ModelHTTPError(status, "test-model", {"detail": "provider refusal", "secret": "do-not-expose"})
    failure = classify_tool_failure(error)
    assert failure.kind == kind
    assert failure.detail == ""
    wrapped = RuntimeError("tool failed")
    wrapped.__cause__ = error
    assert classify_tool_failure(wrapped).kind == kind


@pytest.mark.parametrize("language,remote", [("fr", "service distant"), ("en", "remote service")])
@pytest.mark.parametrize("status,kind", [
    (400, "invalid_arguments"), (401, "authentication"), (403, "permission_denied"),
    (404, "not_found"), (409, "already_exists"), (405, "unsupported"),
    (408, "timeout"), (413, "capacity"), (429, "rate_limited"), (500, "provider"),
    (502, "provider"), (504, "timeout"),
])
def test_remote_http_diagnostics_preserve_status_and_hide_provider_payload(language, remote, status, kind):
    import httpx
    from app.tools.tool_errors import classify_tool_failure, render_tool_failure

    response = httpx.Response(status, request=httpx.Request(
        "GET", "https://example.test/private?token=signed-secret",
    ), text="private-provider-body")
    error = httpx.HTTPStatusError("private-provider-body", request=response.request, response=response)
    wrapped = RuntimeError("private-wrapper-detail")
    wrapped.__cause__ = error
    failure = classify_tool_failure(wrapped)
    assert failure.kind == kind
    assert failure.http_status == status
    message = render_tool_failure(tool_name="file_create", failure=failure, language=language, reference="incident-42")
    assert f"HTTP {status}" in message
    assert remote in message
    assert "incident-42" in message
    assert not any(secret in message for secret in ("signed-secret", "private-provider-body", "private-wrapper-detail", "example.test"))
    if status == 404:
        assert "parent directory" not in message and "répertoire parent" not in message


@pytest.mark.asyncio
async def test_native_domain_not_found_message_selects_lookup_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.goal import goal_service
    from app.goal.mcp import _goal_visible_to_caller
    from app.tools import mcp_loader, tool_errors

    async def missing_goal(*_args: object, **_kwargs: object) -> None:
        return None

    async def owner_scope(_ctx: mcp_loader.McpToolContext) -> int:
        return 7

    monkeypatch.setattr(goal_service, "get_detail", missing_goal)
    monkeypatch.setattr("app.goal.mcp._goal_owner_scope", owner_scope)

    try:
        await _goal_visible_to_caller(
            mcp_loader.McpToolContext(agent_id=7, runtime="internal"),
            UUID("00000000-0000-0000-0000-000000000001"),
        )
    except ValueError as exc:
        failure = tool_errors.classify_tool_failure(exc)
    else:
        raise AssertionError("a missing Goal should fail")

    assert failure.kind == "not_found"
    assert failure.detail.startswith("Goal not found:")
