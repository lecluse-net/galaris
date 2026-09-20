"""Audited HTTP authorization inventory.

Any new unauthenticated or independently authenticated route must be reviewed
and added explicitly here. Broad authenticated-user routes are similarly kept
to the small set of self-service endpoints.
"""

from collections.abc import Iterator
from typing import Any, cast

from fastapi.routing import APIRoute, APIWebSocketRoute

from core.authorize import (
    OwnUserOrPrivilegeAssertion,
    Privileges,
    RequireAllPrivilegesAssertion,
)
from app.agent import AgentOwnerAssertion
from main import app


RouteKey = tuple[str, str]


def _routes(routes: list[Any]) -> Iterator[APIRoute]:
    for candidate in routes:
        if isinstance(candidate, APIRoute):
            yield candidate
            continue
        nested = getattr(
            getattr(candidate, "original_router", None),
            "routes",
            None,
        )
        if isinstance(nested, list):
            yield from _routes(cast(list[Any], nested))


def _websocket_routes(routes: list[Any]) -> Iterator[APIWebSocketRoute]:
    for candidate in routes:
        if isinstance(candidate, APIWebSocketRoute):
            yield candidate
            continue
        nested = getattr(
            getattr(candidate, "original_router", None),
            "routes",
            None,
        )
        if isinstance(nested, list):
            yield from _websocket_routes(cast(list[Any], nested))


def _route_key(route: APIRoute) -> RouteKey:
    return route.endpoint.__module__, route.name


def _all_routes() -> list[APIRoute]:
    fastapi_app = app.other_asgi_app  # type: ignore[attr-defined]
    return list(_routes(cast(list[Any], fastapi_app.routes)))


def test_public_route_allowlist_is_exact() -> None:
    expected = {
        ("core.api", "get_public_openapi_endpoint"),
        ("core.api", "public_swagger_ui_html"),
        ("core.api", "health_check"),
        ("core.api", "liveness_check"),
        ("core.api", "readiness_check"),
        ("core.user.router", "register"),
        ("core.user.router", "registration_status"),
        ("core.user.router", "login"),
        ("core.user.router", "login_json"),
        ("core.user.router", "read_user_avatar"),
    }
    actual = {
        _route_key(route)
        for route in _all_routes()
        if getattr(route.endpoint, "_public_route_reason", None)
    }

    assert actual == expected


def test_independent_auth_route_allowlist_is_exact() -> None:
    expected = {
        ("core.user.router", "logout"),
        ("core.user.router", "refresh_session"),
        ("app.chat.router", "read_standalone_html_preview"),
        ("app.llm.call_router", "llm_models"),
        ("app.llm.call_router", "llm_completion"),
        ("app.llm.call_router", "llm_responses"),
        ("app.llm.call_router", "llm_run_usage"),
        # Scope and commands are exercised through HTTP in test_protocol_inference.
        ("app.llm.call_router", "create_inference"),
        ("app.llm.call_router", "get_inference"),
        ("app.llm.call_router", "command_inference"),
        ("app.llm.call_router", "inference_events"),
        ("app.llm.anthropic_router", "anthropic_models"),
        ("app.llm.anthropic_router", "anthropic_count_tokens"),
        ("app.llm.anthropic_router", "anthropic_messages"),
        ("app.mcp.router", "agent_mcp_endpoint"),
        ("app.multimedia.router", "acknowledge_callback"),
        ("bridge.codex.router", "runtime_credential"),
        # Scoped Fernet capabilities and expired/wrong keys are tested in test_distribution.
        ("bridge.harness.router", "update_manifest"),
        ("bridge.harness.router", "update_archive"),
        ("bridge.hermes.router", "hermes_provider_search"),
        ("bridge.hermes.router", "hermes_provider_remember"),
        ("app.process.router", "receive_event"),
        ("app.process.router", "download_run_file"),
        ("bridge.whatsapp.router", "verify_webhook"),
        ("bridge.whatsapp.router", "verify_tool_webhook"),
        ("bridge.whatsapp.router", "receive_webhook"),
        ("bridge.whatsapp.router", "receive_tool_webhook"),
    }
    actual = {
        _route_key(route)
        for route in _all_routes()
        if getattr(route.endpoint, "_independent_auth_reason", None)
    }

    assert actual == expected


def test_broad_user_route_allowlist_is_exact() -> None:
    expected = {
        # Scoped display metadata only; TEAM_ACCESS is checked for the teams catalogue.
        # HTTP tests in app/agent/tests/test_selection.py enforce the actual data scope.
        ("app.agent.router", "read_agent_selection"),
        ("app.llm.personal_router", "get_preferences"),
        ("app.llm.personal_router", "put_preferences"),
        ("app.llm.personal_router", "get_options"),
        ("app.llm.personal_router", "transcribe"),
        ("app.llm.personal_router", "speech"),
        ("core.user.router", "keep_alive"),
        ("core.user.router", "read_users_me"),
        # Personal acknowledgements, scoped by the authenticated user (HTTP isolation tests).
        ("core.user.router", "list_help_dismissals"),
        ("core.user.router", "dismiss_help"),
        ("core.user.router", "delete_user_me"),
        ("core.user.router", "update_user_me"),
        ("core.user.router", "upload_user_avatar"),
        ("core.user.router", "delete_user_avatar"),
        ("core.user.router", "list_my_tokens"),
        ("core.user.router", "create_my_token"),
        ("core.user.router", "update_my_token"),
            ("core.user.router", "delete_my_token"),
            ("core.user.router", "read_mfa_status"),
            ("core.user.router", "setup_mfa"),
            ("core.user.router", "confirm_mfa"),
            ("core.user.router", "disable_mfa"),
            ("core.user.router", "regenerate_mfa_recovery_codes"),
            ("core.authorize.router", "get_my_privileges"),
        ("core.authorize.router", "switch_role"),
        ("core.authorize.router", "set_default_assignment"),
        ("app.onboarding.router", "get_onboarding_overview"),
    }
    actual: set[RouteKey] = set()
    for route in _all_routes():
        meta = getattr(route.endpoint, "_authorize_meta", None)
        if meta is not None and meta.get("privileges") in ([], ["user"]):
            actual.add(_route_key(route))

    assert actual == expected


def test_every_route_privilege_code_exists() -> None:
    known_codes = {
        value
        for name, value in vars(Privileges).items()
        if name.isupper() and isinstance(value, str)
    }
    known_codes.add("user")

    for route in _all_routes():
        meta = getattr(route.endpoint, "_authorize_meta", None)
        if meta is None:
            continue
        assert set(meta["privileges"]) <= known_codes, _route_key(route)


def test_security_critical_route_policies_are_exact() -> None:
    by_key = {_route_key(route): route for route in _all_routes()}

    install_helper = by_key[
        ("app.console.router", "install_connection_galaris_exec")
    ]
    assert install_helper.endpoint._authorize_meta["privileges"] == [
        Privileges.CONNECTION_EDIT
    ]

    for key in (
        ("app.agent.openai_router", "get_agent_models"),
        ("app.agent.openai_router", "agent_chat_completions"),
        ("app.agent.openai_router", "get_janus_models"),
        ("app.agent.openai_router", "janus_chat_completions"),
    ):
        assert by_key[key].endpoint._authorize_meta["privileges"] == [
            Privileges.AGENT_API_ACCESS
        ]

    for name in (
        "list_agent_mcp_tokens",
        "create_agent_mcp_token",
        "update_agent_mcp_token",
        "delete_agent_mcp_token",
    ):
        meta = by_key[("app.mcp.router", name)].endpoint._authorize_meta
        assert set(meta["privileges"]) == {
            Privileges.AGENT_EDIT,
            Privileges.MCP_API_ACCESS,
        }
        assert meta["assertion"] is RequireAllPrivilegesAssertion

    for name in ("harness_status", "harness_logs"):
        assert set(
            by_key[("app.harnesses.router", name)]
            .endpoint._authorize_meta["privileges"]
        ) == {Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT}

    assert set(
        by_key[("bridge.hermes.router", "list_hermes_configurations")]
        .endpoint._authorize_meta["privileges"]
    ) == {Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT}

    for name in ("hermes_reachable", "hermes_list_agents"):
        assert set(
            by_key[("bridge.hermes.router", name)]
            .endpoint._authorize_meta["privileges"]
        ) == {Privileges.HERMES_ACCESS, Privileges.HERMES_EDIT}

    meta = by_key[
        ("app.harnesses.router", "run_harness_action")
    ].endpoint._authorize_meta
    assert meta["privileges"] == [Privileges.AGENT_EDIT]
    assert meta["assertion"] is AgentOwnerAssertion

    for name in (
        "create_harness",
        "probe_harness",
        "update_harness",
        "delete_harness",
    ):
        meta = by_key[("app.harnesses.router", name)].endpoint._authorize_meta
        assert meta["privileges"] == [Privileges.PARAMS_EDIT]

    for name in (
        "update_agent",
        "delete_agent",
        "upload_avatar",
        "delete_avatar",
    ):
        meta = by_key[("app.agent.router", name)].endpoint._authorize_meta
        assert meta["privileges"] == [Privileges.AGENT_EDIT]
        assert meta["assertion"] is AgentOwnerAssertion

    config_meta = by_key[
        ("bridge.hermes.router", "update_hermes_configuration")
    ].endpoint._authorize_meta
    assert config_meta["privileges"] == [Privileges.AGENT_EDIT]
    assert config_meta["assertion"] is AgentOwnerAssertion

    sync_meta = by_key[
        ("app.harness.router", "sync_harness_skills")
    ].endpoint._authorize_meta
    assert sync_meta["privileges"] == [Privileges.SKILL_ASSIGN]
    assert sync_meta["assertion"] is AgentOwnerAssertion

    assignment_meta = by_key[
        ("core.authorize.router", "get_user_assignments")
    ].endpoint._authorize_meta
    assert assignment_meta["assertion"] is OwnUserOrPrivilegeAssertion
    assert Privileges.MANAGE_ASSIGNMENT in assignment_meta["privileges"]


def test_native_websocket_route_allowlist_is_exact() -> None:
    fastapi_app = app.other_asgi_app  # type: ignore[attr-defined]
    actual = {
        (route.endpoint.__module__, route.name)
        for route in _websocket_routes(cast(list[Any], fastapi_app.routes))
    }

    # OneBot verifies its connection-scoped bearer secret before accepting.
    assert actual == {("bridge.one_bot.router", "onebot_endpoint")}
