from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.llm.call_router import _llm_api_auth, _resolve_llm_task_id
from bridge.hermes.manager import (
    _build_compose_dict,
    _compression_threshold,
    _default_env_dict,
    _inject_dashboard_auth,
    _inject_llm,
    _runtime_url,
    _remove_direct_llm_compose_credentials,
    _remove_direct_llm_credentials,
    runtime_settings,
)
from bridge.hermes.config_service import _hash_dashboard_password


def test_hermes_model_is_forced_through_galaris(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime_settings,
        "HARNESS_MANAGER_GALARIS_API_URL",
        "https://galaris.example.test/api",
    )
    llm = SimpleNamespace(
        id=17,
        code="deepseek-flash",
        llm_name="deepseek/deepseek-v4-flash",
        context_length=1_000_000,
    )
    config = {
        "model": {
            "default": "anthropic/old-model",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "${OPENROUTER_API_KEY}",
        }
    }
    data_env = {
        "OPENROUTER_API_KEY": "must-disappear",
        "OPENAI_API_KEY": "must-disappear-too",
    }

    _remove_direct_llm_credentials(data_env)
    _inject_llm(config, data_env, llm, "mcp_secret")

    assert config["model"] == {
        "default": "deepseek-flash",
        "provider": "custom",
        "base_url": "https://galaris.example.test/api/llm/openai",
        "api_key": "${GALARIS_LLM_API_KEY}",
        "api_mode": "chat_completions",
        "context_length": 1_000_000,
    }
    assert config["compression"] == {
        "enabled": True,
        "threshold": 0.064,
        "target_ratio": 0.10,
        "protect_first_n": 0,
        "protect_last_n": 8,
        "abort_on_summary_failure": False,
    }
    assert config["auxiliary"]["compression"]["context_length"] == 1_000_000
    assert data_env == {"GALARIS_LLM_API_KEY": "mcp_secret"}


@pytest.mark.parametrize(
    ("context_length", "expected"),
    [(1_000_000, 0.064), (256_000, 0.25), (128_000, 0.5), (64_000, 0.5)],
)
def test_compression_threshold_adapts_to_model_window(
    context_length: int, expected: float
) -> None:
    assert _compression_threshold(context_length) == expected


def test_injection_without_context_does_not_configure_context_or_compression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_settings,
        "HARNESS_MANAGER_GALARIS_API_URL",
        "https://galaris.example.test/api",
    )
    llm = SimpleNamespace(id=18, llm_name="any-model", context_length=None)
    config: dict = {}
    data_env: dict = {}
    _inject_llm(config, data_env, llm, "mcp_secret")

    assert "context_length" not in config["model"]
    assert config["model"]["default"] == "llm-18"
    assert "compression" not in config
    assert "auxiliary" not in config


def test_dashboard_basic_auth_is_injected() -> None:
    agent = SimpleNamespace(
        hermes_dashboard_enabled=True,
        hermes_dashboard_username="admin",
        hermes_dashboard_password_hash="scrypt$16384$8$1$salt$digest",
    )
    config: dict = {}

    _inject_dashboard_auth(config, agent)

    assert config["dashboard"]["basic_auth"] == {
        "username": "admin",
        "password_hash": "scrypt$16384$8$1$salt$digest",
    }


def test_dashboard_enabled_without_port_sets_env_but_does_not_expose_port() -> None:
    agent = SimpleNamespace(
        code="agent-test",
        hermes_api_key=None,
        hermes_api_port=None,
        hermes_dashboard_enabled=True,
        hermes_dashboard_port=None,
        hermes_compose=None,
    )

    env = _default_env_dict(agent)
    compose = _build_compose_dict(agent, uid=1000, gid=1000)

    assert env["DASHBOARD"] == "1"
    assert "ports" not in compose["services"]["agent"]
    assert "API_SERVER_ENABLED=true" in compose["services"]["agent"]["environment"]


def test_managed_compose_preserves_operator_network_defaults() -> None:
    agent = SimpleNamespace(
        code="agent-test",
        hermes_api_port=8643,
        hermes_dashboard_enabled=False,
        hermes_dashboard_port=None,
        hermes_compose=None,
    )

    compose = _build_compose_dict(
        agent,
        uid=1000,
        gid=1000,
        default_compose=(
            "services:\n  agent:\n    networks: [default, galaris]\n"
            "networks:\n  default: {}\n  galaris:\n"
            "    external: true\n    name: galaris_executor_net\n"
        ),
    )

    assert compose["services"]["agent"]["networks"] == ["default", "galaris"]
    assert compose["networks"] == {
        "default": {},
        "galaris": {"external": True, "name": "galaris_executor_net"},
    }
    assert _runtime_url("agent-test") == "http://agent-test-agent:8642/v1"


def test_dashboard_password_hash_matches_hermes_format() -> None:
    hashed = _hash_dashboard_password("secret")

    assert hashed is not None
    parts = hashed.split("$")
    assert parts[:4] == ["scrypt", "16384", "8", "1"]
    assert len(parts) == 6


def test_provider_keys_are_removed_from_compose_overrides() -> None:
    compose = {
        "services": {
            "agent": {
                "environment": [
                    "OPENROUTER_API_KEY=secret",
                    "OPENAI_API_KEY=${OPENAI_API_KEY}",
                    "CUSTOM_PLATFORM_TOKEN=${CUSTOM_PLATFORM_TOKEN}",
                ]
            }
        }
    }

    _remove_direct_llm_compose_credentials(compose)

    assert compose["services"]["agent"]["environment"] == [
        "CUSTOM_PLATFORM_TOKEN=${CUSTOM_PLATFORM_TOKEN}"
    ]


@pytest.mark.asyncio
async def test_llm_task_id_prefers_explicit_value(monkeypatch: pytest.MonkeyPatch) -> None:
    explicit_task_id = uuid4()

    import app.agent as agent_module

    def fail_get_current_task(agent_id: int) -> None:
        raise AssertionError("current task fallback must not be used")

    monkeypatch.setattr(
        agent_module,
        "get_current_task",
        fail_get_current_task,
    )

    assert await _resolve_llm_task_id(
        raw_task_id=str(explicit_task_id),
        messages=[],
        agent_id=42,
    ) == explicit_task_id


@pytest.mark.asyncio
async def test_llm_task_id_prefers_prompt_context_over_current_agent_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_task_id = uuid4()

    import app.agent as agent_module

    def get_current_task(agent_id: int) -> UUID:
        return uuid4()

    monkeypatch.setattr(agent_module, "get_current_task", get_current_task)

    assert await _resolve_llm_task_id(
        raw_task_id=None,
        messages=[
            {
                "role": "user",
                "content": (
                    "<galaris_message_context>\n"
                    f'{{"task_id": "{prompt_task_id}"}}\n'
                    "</galaris_message_context>"
                ),
            }
        ],
        agent_id=42,
    ) == prompt_task_id


@pytest.mark.asyncio
async def test_llm_task_id_falls_back_to_current_hermes_agent_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_task_id = uuid4()

    import app.agent as agent_module

    def get_current_task(agent_id: int) -> UUID:
        assert agent_id == 42
        return current_task_id

    monkeypatch.setattr(agent_module, "get_current_task", get_current_task)

    assert await _resolve_llm_task_id(
        raw_task_id=None,
        messages=[],
        agent_id=42,
    ) == current_task_id


@pytest.mark.asyncio
async def test_llm_task_id_stays_empty_without_hermes_agent() -> None:
    assert await _resolve_llm_task_id(
        raw_task_id=None,
        messages=[],
        agent_id=None,
    ) is None


@pytest.mark.asyncio
async def test_proxy_token_identifies_hermes_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.mcp import mcp_token_service

    async def resolve(token: str):
        assert token == "mcp_secret"
        return SimpleNamespace(agent_id=42)

    monkeypatch.setattr(mcp_token_service, "get_enabled_system_token_by_value", resolve)
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"authorization", b"Bearer mcp_secret")],
    })

    assert await _llm_api_auth(request) == 42


@pytest.mark.asyncio
async def test_proxy_rejects_missing_machine_token_and_user(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import call_router

    monkeypatch.setattr(call_router.user_service, "get_current_user", AsyncMock(return_value=None))
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    with pytest.raises(HTTPException) as error:
        await _llm_api_auth(request)

    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_user_llm_api_auth_requires_dedicated_privilege(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm import call_router

    user = SimpleNamespace(id=7, is_active=True)
    monkeypatch.setattr(
        call_router.user_service,
        "get_current_user",
        AsyncMock(return_value=user),
    )
    check_privilege = AsyncMock(return_value=False)
    monkeypatch.setattr(call_router, "check_privilege", check_privilege)
    monkeypatch.setattr(call_router, "get_db", lambda: object())
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    with pytest.raises(HTTPException) as error:
        await _llm_api_auth(request)

    assert error.value.status_code == 403
    check_privilege.assert_awaited_once()


@pytest.mark.asyncio
async def test_hermes_llm_capability_bypasses_user_rbac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm import call_router
    from app.mcp import mcp_token_service

    resolve_system_token = AsyncMock(return_value=SimpleNamespace(agent_id=42))
    monkeypatch.setattr(
        mcp_token_service,
        "get_enabled_system_token_by_value",
        resolve_system_token,
    )
    get_current_user = AsyncMock()
    check_privilege = AsyncMock()
    monkeypatch.setattr(
        call_router.user_service,
        "get_current_user",
        get_current_user,
    )
    monkeypatch.setattr(call_router, "check_privilege", check_privilege)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"authorization", b"Bearer mcp_secret")],
        }
    )

    assert await _llm_api_auth(request) == 42
    get_current_user.assert_not_awaited()
    check_privilege.assert_not_awaited()
