import asyncio
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import UUID, uuid4

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("include_resources", [False, True])
@pytest.mark.parametrize("supports_optional_capabilities", [False, True])
async def test_permission_inventory_discovers_only_supported_capabilities(monkeypatch, include_resources, supports_optional_capabilities):
    from app.services import mcp_loader
    from app.services.schemas import Service
    from mcp.types import PromptsCapability, ResourcesCapability, ServerCapabilities, ToolsCapability

    class CatalogueClient:
        server_capabilities = ServerCapabilities(
            tools=ToolsCapability(),
            resources=ResourcesCapability() if supports_optional_capabilities else None,
            prompts=PromptsCapability() if supports_optional_capabilities else None,
        )

        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return None
        async def list_tools(self):
            return [SimpleNamespace(name="synthetic_function", description="Synthetic function")]
        async def list_prompts(self):
            assert supports_optional_capabilities
            return [SimpleNamespace(name="synthetic_prompt", description="Synthetic prompt")]
        async def list_resources(self):
            assert include_resources and supports_optional_capabilities
            return [SimpleNamespace(uri="test://synthetic", description="Synthetic resource")]
        async def list_resource_templates(self):
            assert include_resources and supports_optional_capabilities
            return [SimpleNamespace(uri_template="test://{name}", description="Synthetic template")]
    monkeypatch.setattr(mcp_loader, "Client", lambda _transport: CatalogueClient())
    monkeypatch.setattr(mcp_loader, "_external_transport", lambda *_args: object())
    result = await mcp_loader.list_external_mcp_capabilities(
        Service(code="synthetic", label="Synthetic"), {}, include_resources=include_resources,
    )
    expected = [("synthetic_function", "Synthetic function", "tool")]
    if supports_optional_capabilities:
        if include_resources:
            expected.extend([("test://synthetic", "Synthetic resource", "resource"),
                             ("test://{name}", "Synthetic template", "resource")])
        expected.append(("synthetic_prompt", "Synthetic prompt", "prompt"))
    assert result == expected

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
    # Isolate approval persistence in these wrapper/error units. Actual pre-effect
    # authorization is exercised with real DB and MCP in test_action_authorizations.
    monkeypatch.setattr("app.services.mcp_authorization.authorize_native_call", AsyncMock(return_value=None))
    async def isolated_messenger_context(ctx, _arguments):
        return ctx
    monkeypatch.setattr("app.messenger.bind_messenger_tool_context", isolated_messenger_context)


@pytest.mark.asyncio
@pytest.mark.parametrize("user_language,conversation_language,expected", [
    ("fr", "en", "fr"),
    (None, "zh", "zh"),
    (None, None, "en"),
])
async def test_taskless_tools_preserve_user_or_conversation_language(
    monkeypatch, user_language, conversation_language, expected,
):
    from app.services.mcp_loader import McpToolContext, context_language
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
    from app.services import mcp_loader, resource_effects

    observed: dict[str, object] = {}

    async def native(ctx: object, room_id: str) -> str:
        observed["ctx"] = ctx
        observed["room_id"] = room_id
        return "sent"

    definition = mcp_loader.McpToolDefinition(
        service_code="messenger",
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
    from app.agent.task_port import task_port
    from app.agent import ScopePreflightV1
    # This projection unit replaces persistence; real pre-effect ordering and
    # rollback are covered in task/tests/test_execution_scope.py.
    scope_decision = AsyncMock(return_value=ScopePreflightV1(tool_name=definition.name,
        decision="allow_and_record", reason="Synthetic projection unit."))
    monkeypatch.setattr(task_port, "record_scope_preflight", scope_decision)
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
        task_id=task_id,
        resources=None,
    )
    assert projection.await_count == 2
    projection.assert_awaited_with(
        7, runtime="internal", conversation_only=False,
        allowed_tool_names={"messenger_room_send_file"}, resources={}, task_id=task_id,
    )
    effects.assert_awaited_once()
    assert scope_decision.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["internal", "hermes"])
async def test_native_mcp_ignores_unknown_arguments_and_informs_the_model(monkeypatch, runtime):
    import json
    from fastmcp import Client
    from app.services import mcp_loader
    from app.services.contracts import EXECUTION_META_KEY

    calls = []

    async def schemes(ctx: mcp_loader.McpToolContext) -> dict[str, object]:
        calls.append(ctx.runtime)
        return {"schemes": ["synthetic"]}

    definition = mcp_loader.McpToolDefinition(
        service_code="file_sharing", name="file_schemes", description="Synthetic schemes.",
        required_capabilities=frozenset(), function=schemes,
    )
    monkeypatch.setattr(mcp_loader, "load_mcp_tools", lambda: (definition,))
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    monkeypatch.setattr("app.agent.effective_capabilities", AsyncMock(return_value=frozenset({"execute"})))
    monkeypatch.setattr("app.services.resource_effects.record_tool_resources", AsyncMock())
    server = mcp_loader.build_galaris_fastmcp(7, runtime=runtime)

    async with Client(server) as client:
        result = await client.call_tool("file_schemes", {"unused": "sensitive-value"}, raise_on_error=False)
        assert not result.is_error
        assert calls == [runtime]
        assert result.structured_content == {"schemes": ["synthetic"]}
        warning = json.loads(result.content[-1].text)
        assert warning["ignored_parameters"] == ["unused"]
        assert warning["available_parameters"] == []
        assert warning["required_parameters"] == []
        assert "sensitive-value" not in result.content[-1].text
        assert result.meta[EXECUTION_META_KEY]["outcome"] == "returned"
        clean = await client.call_tool("file_schemes", {})
        assert len(clean.content) == 1


@pytest.mark.asyncio
async def test_parallel_mounts_of_one_native_definition_keep_the_callers_context(monkeypatch):
    from fastmcp import Client
    from app.services import mcp_loader

    callers = [(7, uuid4()), (7, uuid4()), (8, uuid4())]
    barrier = asyncio.Barrier(len(callers))

    async def schemes(ctx: mcp_loader.McpToolContext) -> str:
        await barrier.wait()
        return f"{ctx.agent_id}/{ctx.task_id}/{ctx.resource('marker')}"

    definition = mcp_loader.McpToolDefinition(service_code="file_sharing", name="file_schemes",
        description="Synthetic file schemes.", required_capabilities=frozenset(), function=schemes)
    monkeypatch.setattr(mcp_loader, "load_mcp_tools", lambda: (definition,))
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    monkeypatch.setattr(mcp_loader, "context_language", AsyncMock(return_value="en"))
    monkeypatch.setattr("app.agent.record_scope_preflight", AsyncMock(return_value=SimpleNamespace(
        decision="allow", operation_id=uuid4(), scope_revision=1)))
    monkeypatch.setattr("app.agent.effective_capabilities", AsyncMock(return_value=frozenset({"execute"})))
    monkeypatch.setattr("app.services.resource_effects.record_tool_resources", AsyncMock())

    async def invoke(index, agent, task):
        server = mcp_loader.build_galaris_fastmcp(agent, task_id=task, resources={"marker": index})
        async with Client(server) as client:
            result = await client.call_tool("file_schemes", {})
            assert result.content[0].text == f"{agent}/{task}/{index}"

    async with asyncio.timeout(10):
        await asyncio.gather(*(invoke(index, *caller) for index, caller in enumerate(callers)))


@pytest.mark.asyncio
async def test_native_tool_timeout_is_bounded_and_cancels_the_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastmcp.exceptions import ToolError

    from app.services import mcp_loader

    cancelled = asyncio.Event()

    async def stalled(_ctx: object) -> str:
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    definition = mcp_loader.McpToolDefinition(
        service_code="file_sharing",
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
async def test_completed_tool_timeout_releases_request_context(monkeypatch: pytest.MonkeyPatch) -> None:
    import gc
    from contextvars import ContextVar
    from weakref import ref

    from app.services import mcp_loader

    class RequestContext:
        pass

    marker = ContextVar[RequestContext]("synthetic_request_context")

    async def native(_ctx: object) -> str:
        assert isinstance(marker.get(), RequestContext)
        return "ok"

    definition = mcp_loader.McpToolDefinition(
        service_code="file_sharing",
        name="file_list",
        description="List files.",
        required_capabilities=frozenset(),
        function=native,
        timeout_seconds=60,
    )
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    wrapper = mcp_loader._wrap_tool(  # pyright: ignore[reportPrivateUsage]
        definition,
        mcp_loader.McpToolContext(agent_id=7, runtime="internal"),
    )

    # A pending earlier callback can keep the cancelled deadline in the loop's queue.
    earlier = asyncio.get_running_loop().call_later(30, lambda: None)
    context = RequestContext()
    context_ref = ref(context)
    try:
        token = marker.set(context)
        try:
            assert await wrapper() == "ok"
        finally:
            marker.reset(token)
        del context
        gc.collect()
        assert context_ref() is None
    finally:
        earlier.cancel()


@pytest.mark.asyncio
async def test_parallel_native_tools_receive_distinct_database_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.database import get_db
    from app.services import mcp_loader, resource_effects

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
        service_code="browser",
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
@pytest.mark.parametrize("before_launch", [False, True])
async def test_recoverable_native_tool_error_keeps_its_actionable_message(monkeypatch: pytest.MonkeyPatch, before_launch) -> None:
    from app.services import mcp_loader, tool_errors
    from app.services.contracts import ToolExecutionContext, tool_execution
    from app.conversation.process_admission import ProcessLaunchRejected

    error = ProcessLaunchRejected if before_launch else tool_errors.RecoverableToolError

    async def native(_ctx: object) -> str:
        raise error(
            "No recent room was found for Alice; ask her to send a message first."
        )

    definition = mcp_loader.McpToolDefinition(
        service_code="messenger",
        name="messenger_send_audio_message",
        description="Send audio.",
        required_capabilities=frozenset(),
        function=native,
    )
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    monkeypatch.setattr("core.failure_journal.record_failure_event", AsyncMock())
    wrapper = mcp_loader._wrap_tool(  # pyright: ignore[reportPrivateUsage]
        definition,
        mcp_loader.McpToolContext(agent_id=7, runtime="internal"),
    )

    execution = ToolExecutionContext(uuid4(), definition.name)
    with tool_execution(execution):
        result = await wrapper()
    assert result.is_error
    assert any("No recent room was found for Alice" in part.text for part in result.content)
    assert execution.outcome == ("rejected" if before_launch else "unknown")


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "fr", "zh"])
async def test_internal_peer_message_without_task_reports_rejection_before_effect(monkeypatch, language):
    from app.messenger import mcp
    from app.services import mcp_loader
    from app.services.contracts import ToolExecutionContext, tool_execution

    messenger = SimpleNamespace(kind="internal", send_to_user=AsyncMock(), send_to_room=AsyncMock())
    monkeypatch.setattr(mcp, "_resolve_user_delivery", AsyncMock(return_value=(messenger, "agent:8")))
    monkeypatch.setattr(mcp, "_recipient_agent_id", AsyncMock(return_value=8))
    monkeypatch.setattr(mcp_loader, "context_language", AsyncMock(return_value=language))
    monkeypatch.setattr(mcp, "_context_language", AsyncMock(return_value=language))
    peer_request = AsyncMock()
    monkeypatch.setattr("app.task.facade.request_peer_message", peer_request)
    journal = AsyncMock()
    monkeypatch.setattr("core.failure_journal.record_failure_event", journal)
    definition = mcp_loader.McpToolDefinition(
        service_code="messenger", name="messenger_send_message_to_user",
        description="Send a message.", required_capabilities=frozenset(),
        function=mcp.mcp_send_message_to_user,
    )
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    wrapper = mcp_loader._wrap_tool(definition, mcp_loader.McpToolContext(agent_id=7, runtime="internal"))
    execution = ToolExecutionContext(uuid4(), definition.name)
    with tool_execution(execution):
        result = await wrapper(user="agent:8", message="Synthetic peer question", wait_for_reply=False)

    assert result.is_error
    assert execution.outcome == "rejected"
    message = " ".join(part.text for part in result.content)
    assert mcp._message(language, "peer_task_required") in message
    assert "task_run" in message
    assert journal.await_args.args[0].error_code == "actionable"
    peer_request.assert_not_awaited()
    messenger.send_to_user.assert_not_awaited()
    messenger.send_to_room.assert_not_awaited()


def test_mcp_loader_discovers_decorated_tools_by_service_code() -> None:
    from app.services.mcp_loader import mcp_tool_names_by_service_code

    names = mcp_tool_names_by_service_code()

    assert "search_web" in names["browser"]
    assert {
        "task_get",
        "task_run",
        "task_cancel",
    } <= set(names["task"])
    assert {"agent_list", "agent_get", "team_list", "team_members"} <= set(names["agent"])
    assert "services_list" in names["service"]
    assert {"agent_list", "agent_get", "services_list"}.isdisjoint(names["galaris"])
    assert not any(name.startswith("process_") or name == "processus_get" for name in names["galaris"])
    assert not any(name.startswith("goal_") for name in names["galaris"])
    assert {
        "file_schemes",
        "file_list",
        "file_info",
        "file_search",
        "file_read",
        "file_create",
        "file_to_pdf",
        "file_write",
        "file_append",
        "file_edit",
        "file_copy",
        "file_move",
        "file_rename",
        "file_delete",
        "dataset_query",
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
    assert {"image_generate", "image_read", "image_from_pdf"} <= set(names["multimedia"])
    assert "audio_transcribe" in names["multimedia"]
    assert {
        "goal_create",
        "goal_update",
        "goal_pause",
        "goal_resume",
        "goal_complete",
        "goal_delete",
        "goal_update_suivi", "goal_run_now", "goal_ask_referrer",
        "goal_retrospective_evidence", "goal_retrospective_learn", "goal_retrospective_record",
    } == set(names["goal"])
    assert {"skills_list", "skill_read", "skill_update", "skill_set_enabled", "skill_delete",
            "skill_set_authorization", "skill_set_category_authorization", "skill_release_ownership"} == set(names["skills"])
    assert "skill_management" not in names
    assert {
        "process_start", "process_analyze_run",
        "process_start_conversation", "process_prepare", "process_pending", "process_respond",
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
    } <= set(names["process"])
    assert all(name.startswith("process_") for name in names["process"])
    assert {"process_list", "process_get", "process_list_runs", "process_get_run",
            "process_definition_read", "process_run_inspect"}.isdisjoint(names["process"])
    assert all(not name.startswith("service_admin_") for name in names["service"])
    assert "topic_get" not in names["topic"]
    assert {"llm_call", "llm_calls", "documentation_catalog", "documentation_search", "incidents_list", "incident_get"} <= set(names["galaris"])
    assert {"chat_round_get", "voice_turn_get", "voice_call_start", "voice_call_stop", "voice_call_list"} <= set(names["chat"])
    assert {"platform_admin", "voice", "audio", "image", "search"}.isdisjoint(names)
    assert {
        "topic_list",
        "topic_items_list",
        "topic_create",
        "topic_update",
        "topic_item_move",
        "topic_merge",
        "topic_split",
    } == set(names["topic"])


def test_tool_execution_policy_is_explicit_and_conservative() -> None:
    from app.services.mcp_loader import execution_policy_for_tool

    assert execution_policy_for_tool("search_web") == ("read", "safe")
    assert execution_policy_for_tool("agent_list") == ("read", "safe")
    assert execution_policy_for_tool("agent_get") == ("read", "safe")
    assert execution_policy_for_tool("team_list") == ("read", "safe")
    assert execution_policy_for_tool("team_members") == ("read", "safe")
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


def test_service_code_does_not_implicitly_authorize_messenger() -> None:
    from app.services.mcp_loader import native_service_codes_for_connection

    for code in ("nextcloud", "matrix", "telegram", "whatsapp", "one_bot"):
        assert native_service_codes_for_connection(code) == frozenset({code})


def test_disabled_bridge_removes_only_explicit_messaging_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bridge.matrix  # noqa: F401
    from app.services.mcp_loader import native_service_codes_for_service
    from core.params.runtime_settings import runtime_settings

    monkeypatch.setattr(runtime_settings, "MESSENGER_ENABLED_CHANNELS", '["matrix"]')
    tool = SimpleNamespace(
        code="my-matrix",
        messenger=SimpleNamespace(service="matrix"),
    )
    assert native_service_codes_for_service(tool) == frozenset(
        {"my-matrix", "messenger"}
    )

    monkeypatch.setattr(
        runtime_settings,
        "MESSENGER_ENABLED_CHANNELS",
        '["telegram"]',
    )

    assert native_service_codes_for_service(tool) == frozenset({"my-matrix"})


def test_concrete_tool_requires_explicit_messenger_capability(monkeypatch) -> None:
    import bridge.matrix  # noqa: F401
    from app.services.mcp_loader import native_service_codes_for_service
    from core.params.runtime_settings import runtime_settings
    monkeypatch.setattr(runtime_settings, "MESSENGER_ENABLED_CHANNELS", '["matrix"]')

    ordinary = SimpleNamespace(code="messenger", messenger=None)
    configured = SimpleNamespace(
        code="my-chat",
        messenger=SimpleNamespace(service="matrix"),
    )

    assert "messenger" not in native_service_codes_for_service(ordinary)
    assert "messenger" in native_service_codes_for_service(configured)


@pytest.mark.asyncio
async def test_agent_catalog_accumulates_mcp_messenger_and_file_share_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import agent
    from app.connection import facade as connection_service
    from app.services import mcp_loader, service

    connection = SimpleNamespace(id=11, service_id=35, active=True)
    record = SimpleNamespace(
        id=35,
        code="nextcloud",
        label="Nextcloud",
        description="Combined Nextcloud services.",
    )
    tool = SimpleNamespace(
        code="nextcloud",
        mcp=SimpleNamespace(type="http"),
        mail=None,
        messenger=SimpleNamespace(service="nextcloud_talk"),
        file_share=SimpleNamespace(service="nextcloud"),
    )
    native_definition = SimpleNamespace(
        name="messenger_room_send_message",
        service_code="messenger",
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
        service,
        "get_all_service_records",
        AsyncMock(return_value=[record]),
    )
    monkeypatch.setattr(service, "_to_internal", lambda _record: tool)
    monkeypatch.setattr(
        mcp_loader,
        "mcp_tools_by_service_code",
        lambda: {"messenger": [native_definition]},
    )
    monkeypatch.setattr(
        mcp_loader,
        "native_service_codes_for_service",
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
    from app.services import mcp_loader

    _catalog_connections(monkeypatch, {code: {} for code in ("task", "file_sharing", "process")},
                         disabled={1: {"task_cancel"}})

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="hermes",
        allowed_tool_names={
            "file_list",
            "process_analyze_run",
            "process_start",
            "task_cancel",
        },
    )

    assert [definition.name for definition in definitions] == [
        "file_list",
        "process_analyze_run",
        "process_start",
    ]


def _catalog_connections(monkeypatch, configurations, *, disabled=None):
    from app.connection import facade as connections
    from app.services import service
    from app.services.schemas import Service

    services = {index: Service(code=code, label=code, **config)
                for index, (code, config) in enumerate(configurations.items(), 1)}
    active = [SimpleNamespace(id=index, service_id=index, active=True) for index in services]
    monkeypatch.setattr(connections, "active_connection_refs", AsyncMock(return_value=active))
    monkeypatch.setattr(connections, "get_disabled_function_names_many", AsyncMock(return_value=disabled or {}))
    monkeypatch.setattr(service, "get_services_by_ids", AsyncMock(return_value=services))


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
@pytest.mark.parametrize("service_scope", ["usage", "personal"])
async def test_conversation_projection_intersects_builtin_allowlist_and_function_policy(
    monkeypatch: pytest.MonkeyPatch,
    revoked: bool,
    service_scope: str,
) -> None:
    from app.services import mcp_loader
    from app.connection import facade as connections

    _catalog_connections(monkeypatch, {
        code: {} for code in ("galaris", "chat", "memory", "document", "file_sharing", "process", "agent", "task", "skills", "service", "topic")
    }, disabled={4: {"document_sharing"}} if revoked else {})
    monkeypatch.setattr(connections, "get_management_scope", AsyncMock(return_value=service_scope))

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="internal",
        allowed_tool_names={
            "agent_list",
            "agent_get",
            "task_get",
            "task_submit",
            "task_resume",
            "task_retry",
            "file_search",
            "document_sharing",
            "process_start",
            "process_start_conversation",
            "process_admin_get",
            "task_run",
            "document_analyze",
            "document_analysis_get",
            "document_analysis_cancel",
            "document_revision_list",
            "document_revision_compare",
            "document_chart",
            "skills_list",
            "skill_read",
            "skill_update",
            "file_schemes",
            "dataset_query",
            "file_create",
            "file_write",
            "file_append",
            "file_edit",
            "file_rename",
            "file_to_pdf",
            "services_list",
            "service_connection_list",
            "service_connection_create",
            "topic_list",
            "topic_items_list",
            "topic_create",
        },
        conversation_only=True,
    )

    assert {definition.name for definition in definitions} == {
        "agent_list",
        "agent_get",
        "task_get",
        "task_run",
        "task_resume",
        "file_search",
        "process_start_conversation",
        "document_sharing",
        "skills_list",
        "skill_read",
        "file_schemes",
        "dataset_query",
        "services_list",
        "topic_list",
        "topic_items_list",
    } - ({"document_sharing"} if revoked else set()) | (
        {"service_connection_list"} if service_scope == "personal" else set()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("audio_model_available", [False, True])
async def test_multimedia_conversation_exposes_readers_with_the_applicable_media_model(
    monkeypatch: pytest.MonkeyPatch, audio_model_available: bool,
) -> None:
    from app.services import mcp_loader

    _catalog_connections(monkeypatch, {"multimedia": {}})
    available = {"audio_read"} if audio_model_available else set()
    model_lookup = AsyncMock(return_value=frozenset(available))
    monkeypatch.setattr("app.llm.available_media_functions", model_lookup)

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(42, runtime="internal", conversation_only=True)

    assert {definition.name for definition in definitions} == {"image_read", "audio_transcribe"} | available
    model_lookup.assert_awaited_once_with(42, candidates={"audio_read"})


@pytest.mark.asyncio
async def test_chat_exposes_voice_call_controls_but_excludes_inspection_in_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import mcp_loader

    _catalog_connections(monkeypatch, {"chat": {}})

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="internal",
        allowed_tool_names={"voice_call_stop", "voice_call_start", "voice_call_list", "chat_round_get", "voice_turn_get"},
        conversation_only=True,
    )

    assert {definition.name for definition in definitions} == {"voice_call_start", "voice_call_stop", "voice_call_list"}


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation", [True, False])
async def test_task_run_shares_its_name_and_preserves_contextual_replay_policy(monkeypatch, conversation):
    from fastmcp import Client
    from app.services import mcp_loader

    _catalog_connections(monkeypatch, {"task": {}})
    server = await mcp_loader.build_agent_galaris_fastmcp(
        42, conversation_only=conversation, allowed_tool_names={"task_run", "task_submit"},
    )
    async with Client(server) as client:
        (tool,) = await client.list_tools()

    assert tool.name == "task_run"
    assert tool.input_schema["required"] == ["objective"]
    assert bool(tool.annotations and tool.annotations.idempotent_hint) == conversation


@pytest.mark.asyncio
async def test_task_projection_excludes_conversation_control_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import mcp_loader

    _catalog_connections(monkeypatch, {"task": {}})

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="internal",
        allowed_tool_names={"task_submit", "task_list", "task_pause", "task_resume", "task_retry"},
    )

    assert definitions == ()


@pytest.mark.asyncio
async def test_web_search_is_available_in_conversation_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import mcp_loader

    _catalog_connections(monkeypatch, {"browser": {}})

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="internal",
        conversation_only=True,
    )

    assert [definition.name for definition in definitions] == ["search_web"]


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_conversation_projection_requires_both_grants_on_the_same_bridge(
    monkeypatch: pytest.MonkeyPatch,
    revoked: bool,
) -> None:
    from app.services import mcp_loader
    import bridge.telegram  # noqa: F401
    from core.params.runtime_settings import runtime_settings
    monkeypatch.setattr(runtime_settings, "MESSENGER_ENABLED_CHANNELS", '["telegram"]')

    _catalog_connections(monkeypatch, {
        "opted-in": {"messenger_config": {"service": "telegram"}, "conversation_tools": {"native": ["messenger_room_history"]}},
        "opted-out": {"messenger_config": {"service": "telegram"}, "conversation_tools": {"external": ["messenger_room_history"]}},
    }, disabled={1: {"messenger_room_history"}} if revoked else {})

    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        42,
        runtime="internal",
        allowed_tool_names={"messenger_room_history", "messenger_search_users"},
        conversation_only=True,
    )

    assert [definition.name for definition in definitions] == ([] if revoked else ["messenger_room_history"])


@pytest.mark.asyncio
async def test_conversation_aggregate_skips_unchecked_external_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gc
    from weakref import ref

    from fastmcp import FastMCP

    from app.connection import facade as connection_service
    from app.services import mcp_loader, service
    from app.services.contracts import ToolCallRejectedError

    connection = SimpleNamespace(id=9, service_id=3, active=True)
    unchecked_tool = SimpleNamespace(
        code="external",
        can_disable=True,
        mcp=SimpleNamespace(type="http"),
        conversation_tools={},
    )
    native = FastMCP("native")
    native_builder = AsyncMock(return_value=native)
    params = AsyncMock(side_effect=AssertionError("unchecked MCP must not be resolved"))
    monkeypatch.setattr(
        connection_service,
        "active_connection_refs",
        AsyncMock(return_value=[connection]),
    )
    monkeypatch.setattr(connection_service, "get_params_as_dict", params)
    monkeypatch.setattr(
        service,
        "get_services_by_ids",
        AsyncMock(return_value={connection.service_id: unchecked_tool}),
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
        _bindings=ANY,
    )
    # Discovery observes this exact run's server, including tools mounted later.
    run_tool_names = native_builder.await_args.kwargs["resources"]["run_tool_names"]
    assert await run_tool_names() == frozenset()

    @server.tool()
    async def mounted_in_this_run() -> str:
        return "ok"

    assert await run_tool_names() == frozenset({"mounted_in_this_run"})
    params.assert_not_awaited()

    server_ref = ref(server)
    del server
    gc.collect()
    assert server_ref() is None, "A retained catalogue callback must not keep its server alive"
    with pytest.raises(ToolCallRejectedError):
        await run_tool_names()


@pytest.mark.asyncio
async def test_mcp_loader_filters_by_tool_and_runtime() -> None:
    from app.services.mcp_loader import build_galaris_fastmcp

    internal_mcp = build_galaris_fastmcp(
        1,
        runtime="internal",
        enabled_service_codes={"chat", "galaris", "file_sharing", "task", "process", "document"},
    )
    internal_tools = {tool.name: tool for tool in await internal_mcp.list_tools()}
    internal_names = set(internal_tools)

    hermes_mcp = build_galaris_fastmcp(
        1,
        runtime="hermes",
        enabled_service_codes={"chat", "galaris", "file_sharing", "task", "process", "document"},
    )
    hermes_names = {tool.name for tool in await hermes_mcp.list_tools()}

    management_mcp = build_galaris_fastmcp(
        1,
        runtime="internal",
        enabled_service_codes={
            "goal",
            "skills",
            "process",
            "chat",
        },
    )
    management_names = {tool.name for tool in await management_mcp.list_tools()}

    assert "voice_call_start" in internal_names
    assert "file_list" in internal_names
    assert {
        "goal_update_suivi",
        "goal_run_now",
        "goal_ask_referrer",
    } <= management_names
    assert not {"goal_update_suivi", "goal_run_now", "goal_ask_referrer"} & internal_names
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
    assert {"chat_round_get", "voice_turn_get"} <= management_names


@pytest.mark.asyncio
async def test_wrapped_mcp_tool_returns_recoverable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastmcp.exceptions import ToolError

    from app.services.mcp_loader import McpToolContext, McpToolDefinition, _wrap_tool

    sentinel = "synthetic-external-error-secret-never-return"

    async def broken_tool(ctx: McpToolContext, path: str) -> str:
        raise ValueError(sentinel)

    definition = McpToolDefinition(
        service_code="demo",
        name="file_list",
        description="Demo",
        required_capabilities=frozenset({"file_tools"}),
        function=broken_tool,
    )
    async def english_language(_ctx: McpToolContext) -> str:
        return "en"

    monkeypatch.setattr("app.services.mcp_loader.context_language", english_language)
    monkeypatch.setattr("app.services.mcp_loader.list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    wrapped = _wrap_tool(definition, McpToolContext(agent_id=1, runtime="internal"))

    with pytest.raises(ToolError) as caught:
        await wrapped(path="/")

    message = str(caught.value)
    assert "Service 'file_list' failed" in message
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

    from app.services import mcp_loader

    class SFTPNoSuchFile(Exception):
        pass

    async def broken_create(_ctx: object, path: str) -> str:
        del path
        raise SFTPNoSuchFile("No such file")

    definition = mcp_loader.McpToolDefinition(
        service_code="file_sharing",
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
        (type("DocumentConflictError", (RuntimeError,), {})("reload document"), "actionable"),
        (type("DocumentPermissionError", (RuntimeError,), {})(), "permission_denied"),
        (type("DocumentNotFoundError", (RuntimeError,), {})(), "not_found"),
        (RuntimeError(), "unexpected"),
    ],
)
def test_native_tool_failures_have_stable_actionable_categories(
    exc: Exception,
    kind: str,
) -> None:
    from app.services import tool_errors

    failure = tool_errors.classify_tool_failure(exc)

    assert failure.kind == kind


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("current,previous,kind", [
    (PermissionError, FileNotFoundError, "permission_denied"),
    (PermissionError, FileExistsError, "permission_denied"),
    (FileNotFoundError, PermissionError, "not_found"),
    (FileExistsError, FileNotFoundError, "already_exists"),
])
def test_filesystem_diagnostic_preserves_current_failure(wrapped, current, previous, kind):
    from app.services.tool_errors import classify_tool_failure, render_tool_failure

    try:
        try:
            raise previous("Synthetic previous failure")
        except previous:
            raise current("Synthetic current failure")
    except current as error:
        failure = error
        if wrapped:
            failure = RuntimeError("Synthetic provider wrapper")
            failure.__cause__ = error
        diagnostic = classify_tool_failure(failure)

    assert diagnostic.kind == kind
    message = render_tool_failure(tool_name="file_create", failure=diagnostic,
                                  language="fr", reference="synthetic-ref")
    if kind != "not_found":
        assert "répertoire parent" not in message
    assert "Synthetic" not in message


@pytest.mark.parametrize("language,remote_reason", [
    ("fr", "Le service distant a refusé l’accès (HTTP 403)."),
    ("en", "The remote service denied access (HTTP 403)."),
])
def test_http_forbidden_distinguishes_remote_refusal_without_exposing_secrets(
    language: str, remote_reason: str,
) -> None:
    import httpx

    from app.services import tool_errors

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
    from app.services.tool_errors import classify_tool_failure

    failure = ValueError("private provider wrapper")
    failure.__cause__ = ResourceValidationError("Read the current revision before editing.")
    diagnostic = classify_tool_failure(failure)
    assert diagnostic.kind == "actionable"
    assert diagnostic.detail == "Read the current revision before editing."


def test_native_mcp_validation_detail_is_precise_and_secret_redacted() -> None:
    from app.file_share.mcp import _decode_content
    from app.services import tool_errors

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
    from app.services.tool_errors import classify_tool_failure

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
    from app.services.tool_errors import classify_tool_failure, render_tool_failure

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
    from app.services import mcp_loader, tool_errors

    async def missing_goal(*_args: object, **_kwargs: object) -> None:
        return None

    async def owner_scope(_ctx: mcp_loader.McpToolContext, _goal_id: UUID) -> int:
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

def test_native_tools_select_services_by_public_code():
    import inspect
    from app.services.mcp_loader import load_mcp_tools

    for definition in load_mcp_tools():
        parameters = inspect.signature(definition.function).parameters
        assert not {"connection_id", "connection_ids", "referrer_connection_id", "service_id"}.intersection(parameters), definition.name
