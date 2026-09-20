from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

# pyright: reportPrivateUsage=false

from app.agent.models import Agent
from core.settings import settings as bootstrap_settings
from bridge.hermes.manager import HermesAgent, HermesManager

manager_module = importlib.import_module("bridge.hermes.manager")


@pytest.fixture(autouse=True)
def isolate_runtime_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_module.runtime_settings, "HARNESS_MANAGER_GALARIS_API_URL", "")


def _external_ssh_config() -> Any:
    import asyncssh

    key = asyncssh.generate_private_key("ssh-ed25519")
    return manager_module._HermesSshConnection(
        connection_id=4,
        host="worker.example.test",
        port=2222,
        username="worker",
        private_key=key.export_private_key(passphrase="key-secret").decode("ascii"),
        private_key_passphrase="key-secret",
        known_host_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestOnly",
        connect_timeout_s=12.2,
        command_timeout_s=450,
    )


def _executor_llm() -> SimpleNamespace:
    return SimpleNamespace(
        id=11,
        code="executor-model",
        context_length=128_000,
        input_image=True,
        llm_name="Executor model",
    )


def test_default_compose_pins_the_supported_hermes_release() -> None:
    assert manager_module._HERMES_VERSION == "0.21.3"
    assert manager_module._HERMES_RELEASE == "v2026.9.14"
    assert (
        manager_module._DEFAULT_COMPOSE["services"]["agent"]["image"]
        == "galaris/hermes-harness:v2026.9.14"
    )
    upstream = manager_module._DEFAULT_COMPOSE["services"]["agent"]["build"]["args"]["HERMES_IMAGE"]
    assert upstream.startswith("nousresearch/hermes-agent:v2026.9.14@sha256:")
    dockerfile = (manager_module._DEFAULT_AGENT_DIR / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert f"ARG HERMES_IMAGE={upstream}" in dockerfile


def test_compose_owns_one_container_and_data_volume_for_the_agent() -> None:
    agent = cast(
        Agent,
        SimpleNamespace(
            code="alice",
            hermes_api_port=18642,
            hermes_dashboard_enabled=False,
            hermes_dashboard_port=None,
            hermes_compose=None,
        ),
    )

    compose = manager_module._build_compose_dict(agent, 10_000, 10_000)

    service = compose["services"]["agent"]
    assert service["container_name"] == "alice-agent"
    assert service["ports"] == ["18642:8642"]
    assert "./data:/opt/data" in service["volumes"]


@pytest.mark.parametrize("source", ["global", "agent"])
@pytest.mark.parametrize("network_form", [["agents-net"], {"agents-net": {"aliases": ["worker"]}}])
def test_compose_preserves_operator_networks_without_injecting_aliases(
    source: str, network_form: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yaml

    monkeypatch.setenv("HARNESS_MANAGER_DOCKER_NETWORK", "agents-net")
    configured = {
        "services": {"agent": {"networks": network_form}},
        "networks": {"agents-net": {"name": "agents-net", "external": True}},
    }
    override = yaml.safe_dump(configured)
    agent = cast(Agent, SimpleNamespace(
        code="alice", hermes_api_port=None, hermes_dashboard_enabled=False,
        hermes_dashboard_port=None, hermes_compose=override if source == "agent" else None,
    ))
    compose = manager_module._build_compose_dict(
        agent, 10_000, 10_000, override if source == "global" else None,
    )

    assert compose["services"]["agent"]["networks"] == network_form
    assert compose["networks"] == configured["networks"]


@pytest.mark.parametrize("network", ["", "galaris-net", "agents-net"])
def test_compose_does_not_infer_network_from_runtime_settings(
    network: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MANAGER_DOCKER_NETWORK", network)
    agent = cast(Agent, SimpleNamespace(
        code="remote", hermes_api_port=None, hermes_dashboard_enabled=False,
        hermes_dashboard_port=None, hermes_compose=None,
    ))
    compose = manager_module._build_compose_dict(agent, 10_000, 10_000)
    assert "networks" not in compose
    assert "networks" not in compose["services"]["agent"]


def test_agent_can_disable_global_network_attachment() -> None:
    agent = cast(Agent, SimpleNamespace(
        code="remote", hermes_api_port=None, hermes_dashboard_enabled=False,
        hermes_dashboard_port=None,
        hermes_compose="services:\n  agent:\n    networks: []\n",
    ))
    compose = manager_module._build_compose_dict(
        agent, 10_000, 10_000,
        "services:\n  agent:\n    networks: [agents-net]\nnetworks:\n  agents-net:\n    external: true\n",
    )
    assert compose["services"]["agent"]["networks"] == []


def test_external_console_forces_hermes_ssh_without_storing_credentials_in_yaml() -> None:
    config: dict[str, Any] = {
        "terminal": {
            "backend": "docker",
            "ssh_host": "stale.example.test",
        }
    }
    data_env = {"PATH": "/operator/bin:/usr/bin"}

    manager_module._inject_galaris_ssh_terminal(
        config,
        data_env,
        _external_ssh_config(),
        runtime_root="/opt/data",
    )

    assert config["terminal"] == {
        "backend": "ssh",
        "cwd": "~",
        "timeout": 450,
    }
    assert config[manager_module._GALARIS_MANAGED_TERMINAL_KEY]["previous"] == {
        "backend": "docker",
        "ssh_host": "stale.example.test",
    }
    assert data_env["TERMINAL_ENV"] == "ssh"
    assert type(config["terminal"]["timeout"]) is int
    assert data_env["TERMINAL_TIMEOUT"] == "450"
    assert int(data_env["TERMINAL_TIMEOUT"]) == config["terminal"]["timeout"]
    assert data_env["TERMINAL_SSH_HOST"] == "worker.example.test"
    assert data_env["TERMINAL_SSH_PORT"] == "2222"
    assert data_env["TERMINAL_SSH_KEY"] == "/opt/data/.galaris/ssh/id_key"
    assert data_env["PATH"].startswith("/opt/data/.galaris/ssh/bin:")
    assert "PRIVATE KEY" not in manager_module.yaml.dump(config)

    manager_module._remove_galaris_terminal_injection(config)

    assert config == {
        "terminal": {
            "backend": "docker",
            "ssh_host": "stale.example.test",
        }
    }


@pytest.mark.asyncio
async def test_external_console_materializes_strict_instance_scoped_ssh_files() -> None:
    writes: list[tuple[str, str, str, int]] = []

    class Manager:
        async def write_agent_file(
            self,
            code: str,
            filepath: str,
            content: str,
            *,
            mode: int = 0o644,
        ) -> None:
            writes.append((code, filepath, content, mode))

        async def delete_agent_tree(self, _code: str, _path: str) -> bool:
            raise AssertionError("An active external projection must not be purged first")

    agent = cast(Agent, SimpleNamespace(code="alice"))
    runtime = HermesAgent(agent, cast(HermesManager, Manager()))
    config: dict[str, Any] = {}
    data_env: dict[str, str] = {}

    await runtime._sync_console_ssh(data_env, config, _external_ssh_config())

    by_path = {path: (content, mode) for _code, path, content, mode in writes}
    private_key, key_mode = by_path["data/.galaris/ssh/id_key"]
    known_hosts, known_hosts_mode = by_path["data/.galaris/ssh/known_hosts"]
    ssh_wrapper, ssh_mode = by_path["data/.galaris/ssh/bin/ssh"]
    assert private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert key_mode == known_hosts_mode == 0o600
    assert known_hosts.startswith("[worker.example.test]:2222 ssh-ed25519 ")
    assert ssh_mode == 0o755
    assert "StrictHostKeyChecking=yes" in ssh_wrapper
    assert "UserKnownHostsFile=" in ssh_wrapper
    assert "ConnectTimeout=13" in ssh_wrapper


@pytest.mark.asyncio
async def test_external_console_resolution_uses_effective_decrypted_connection_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.connection import connection_service
    from app.tools import tool_service

    connection = SimpleNamespace(id=4, tool_id=9, active=True)
    get_connections = AsyncMock(return_value=[connection])
    get_tool = AsyncMock(return_value=SimpleNamespace(code="console"))
    get_params = AsyncMock(
        return_value=(
            connection,
            {
                "host": "worker.example.test",
                "port": "2222",
                "username": "worker",
                "private_key": "decrypted-key",
                "private_key_passphrase": "decrypted-passphrase",
                "known_host_key": "ssh-ed25519 host-key",
                "connect_timeout_s": "12.2",
                "command_timeout_s": "450",
            },
        )
    )
    monkeypatch.setattr(
        connection_service,
        "get_connections_by_agent",
        get_connections,
    )
    monkeypatch.setattr(connection_service, "get_params_as_dict", get_params)
    monkeypatch.setattr(tool_service, "get_tool_by_id", get_tool)

    resolved = await manager_module._resolve_external_console_ssh(7)

    assert resolved is not None
    assert resolved.host == "worker.example.test"
    assert resolved.port == 2222
    assert resolved.private_key == "decrypted-key"
    assert resolved.private_key_passphrase == "decrypted-passphrase"
    assert resolved.connect_timeout_s == 12.2
    assert resolved.command_timeout_s == 450
    assert type(resolved.command_timeout_s) is int
    get_params.assert_awaited_once_with(connection, decrypt_passwords=True)


@pytest.mark.asyncio
async def test_management_delegates_to_generic_harness_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_manager = HermesManager()
    status = AsyncMock(return_value="running")
    create = AsyncMock()
    delete = AsyncMock()
    action = AsyncMock(return_value="done")
    list_instances = AsyncMock(return_value=["alice"])
    logs = AsyncMock(return_value=["ready"])
    monkeypatch.setattr(manager_module.harness_manager, "get_instance_status", status)
    monkeypatch.setattr(manager_module.harness_manager, "create_instance", create)
    monkeypatch.setattr(manager_module.harness_manager, "delete_instance", delete)
    monkeypatch.setattr(manager_module.harness_manager, "run_action", action)
    monkeypatch.setattr(manager_module.harness_manager, "list_instances", list_instances)
    monkeypatch.setattr(manager_module.harness_manager, "get_logs", logs)

    assert await hermes_manager.get_agent_status("alice") == "running"
    await hermes_manager.create_agent("alice")
    await hermes_manager.delete_agent("alice")
    assert await hermes_manager.run_agent_command("alice", "restart") == "done"
    assert await hermes_manager.list_agents() == ["alice"]
    assert await hermes_manager.get_agent_logs("alice") == ["ready"]
    status.assert_awaited_once_with("alice")
    create.assert_awaited_once_with("alice", None)
    delete.assert_awaited_once_with("alice")
    action.assert_awaited_once_with("alice", "restart")
    list_instances.assert_awaited_once_with()
    logs.assert_awaited_once_with("alice", 300)


@pytest.mark.asyncio
async def test_kanban_is_not_exposed_by_the_generic_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_manager = HermesManager()

    with pytest.raises(RuntimeError, match="generic harness manager"):
        await hermes_manager.create_kanban_task(
            "alice",
            transport="legacy",
            payload={"title": "Task", "body": "Work"},
        )



@pytest.mark.asyncio
async def test_reachability_delegates_to_harness_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reachable = AsyncMock(return_value=True)
    monkeypatch.setattr(manager_module.harness_manager, "check_reachable", reachable)

    assert await HermesManager().check_reachable() is True
    reachable.assert_awaited_once_with()


def test_inject_memory_provider_selects_packaged_galaris_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        manager_module.runtime_settings, "MEMORY_CONTEXT_ENABLED", True
    )
    config: dict[str, Any] = {"memory": {"provider": "native"}}
    data_env: dict[str, str] = {}

    manager_module._inject_memory_provider(
        config,
        data_env,
        cast(Agent, SimpleNamespace(id=17)),
        "https://galaris.example.test/api/",
        "rotated-token",
    )

    assert config == {
        "memory": {"provider": "galaris"},
        "plugins": {"enabled": ["galaris-memory"]},
    }
    assert data_env == {
        "GALARIS_MEMORY_API_URL": "https://galaris.example.test/api/memory/provider",
        "GALARIS_MEMORY_TOKEN": "rotated-token",
        "GALARIS_MEMORY_AGENT_ID": "17",
    }


def test_inject_memory_provider_removes_managed_state_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        manager_module.runtime_settings, "MEMORY_CONTEXT_ENABLED", False
    )
    config: dict[str, Any] = {
        "memory": {"provider": "galaris", "custom": True},
        "plugins": {
            "enabled": ["other-plugin", "galaris-memory"],
            "disabled": ["galaris-memory", "manual-disabled"],
        },
    }
    data_env = {
        "GALARIS_MEMORY_API_URL": "old-url",
        "GALARIS_MEMORY_TOKEN": "old-token",
        "GALARIS_MEMORY_AGENT_ID": "17",
        "UNRELATED": "preserved",
    }

    manager_module._inject_memory_provider(
        config,
        data_env,
        cast(Agent, SimpleNamespace(id=17)),
        "https://galaris.example.test/api",
        "rotated-token",
    )

    assert config == {
        "memory": {"custom": True},
        "plugins": {
            "enabled": ["other-plugin"],
            "disabled": ["manual-disabled"],
        },
    }
    assert data_env == {"UNRELATED": "preserved"}


def test_galaris_memory_defaults_disable_hermes_file_memory_and_tool() -> None:
    config = manager_module._merge_hermes_config_layers(
        {
            "memory": {
                "memory_enabled": True,
                "user_profile_enabled": True,
                "custom": "preserved",
            },
            "agent": {"disabled_toolsets": ["browser"]},
        },
        {},
        {},
        galaris_memory_enabled=True,
    )

    assert config["memory"] == {
        "memory_enabled": False,
        "user_profile_enabled": False,
        "custom": "preserved",
    }
    assert config["agent"]["disabled_toolsets"] == ["browser", "memory"]


def test_params_and_agent_config_override_galaris_memory_defaults() -> None:
    global_config = {
        "memory": {
            "memory_enabled": True,
            "user_profile_enabled": True,
        },
        "agent": {"disabled_toolsets": ["memory", "browser"]},
    }
    per_agent_config = {
        "memory": {"user_profile_enabled": False},
        "agent": {"disabled_toolsets": ["browser"]},
    }

    config = manager_module._merge_hermes_config_layers(
        {},
        global_config,
        per_agent_config,
        galaris_memory_enabled=True,
    )

    assert config["memory"]["memory_enabled"] is True
    assert config["memory"]["user_profile_enabled"] is False
    assert config["agent"]["disabled_toolsets"] == ["browser"]


def test_explicit_native_memory_enable_removes_a_previous_managed_tool_disable() -> None:
    config = manager_module._merge_hermes_config_layers(
        {
            "memory": {
                "memory_enabled": False,
                "user_profile_enabled": False,
            },
            "agent": {"disabled_toolsets": ["browser", "memory"]},
        },
        {"memory": {"user_profile_enabled": True}},
        {},
        galaris_memory_enabled=True,
    )

    assert config["memory"]["user_profile_enabled"] is True
    assert config["agent"]["disabled_toolsets"] == ["browser"]


def test_disabling_galaris_memory_removes_its_previous_managed_defaults() -> None:
    config = manager_module._merge_hermes_config_layers(
        {
            "memory": {
                "provider": "galaris",
                "memory_enabled": False,
                "user_profile_enabled": False,
            },
            "agent": {"disabled_toolsets": ["browser", "memory"]},
        },
        {},
        {},
        galaris_memory_enabled=False,
    )

    assert config["memory"] == {"provider": "galaris"}
    assert config["agent"]["disabled_toolsets"] == ["browser"]


def test_galaris_browser_disables_hermes_browser_toolset() -> None:
    config = manager_module._merge_hermes_config_layers(
        {},
        {},
        {},
        galaris_memory_enabled=False,
        galaris_browser_enabled=True,
    )

    assert config["agent"]["disabled_toolsets"] == ["browser"]


def test_disabling_galaris_browser_removes_its_managed_toolset() -> None:
    config = manager_module._merge_hermes_config_layers(
        {"agent": {"disabled_toolsets": ["browser", "other"]}},
        {},
        {},
        galaris_memory_enabled=False,
        galaris_browser_enabled=False,
    )

    assert config["agent"]["disabled_toolsets"] == ["other"]


def test_explicit_hermes_browser_disable_is_preserved() -> None:
    config = manager_module._merge_hermes_config_layers(
        {},
        {"agent": {"disabled_toolsets": ["browser"]}},
        {},
        galaris_memory_enabled=False,
        galaris_browser_enabled=False,
    )

    assert config["agent"]["disabled_toolsets"] == ["browser"]


def test_galaris_image_functions_disable_matching_hermes_toolsets() -> None:
    config = manager_module._merge_hermes_config_layers(
        {"agent": {"disabled_toolsets": ["other"]}},
        {},
        {},
        galaris_memory_enabled=False,
        galaris_image_generation_enabled=True,
        galaris_image_vision_enabled=True,
    )

    assert config["agent"]["disabled_toolsets"] == [
        "other",
        "image_gen",
        "vision",
    ]


def test_inactive_galaris_image_functions_remove_managed_toolsets() -> None:
    config = manager_module._merge_hermes_config_layers(
        {"agent": {"disabled_toolsets": ["image_gen", "vision", "other"]}},
        {},
        {},
        galaris_memory_enabled=False,
        galaris_image_generation_enabled=False,
        galaris_image_vision_enabled=False,
    )

    assert config["agent"]["disabled_toolsets"] == ["other"]


def test_explicit_hermes_image_disable_is_preserved_per_toolset() -> None:
    config = manager_module._merge_hermes_config_layers(
        {},
        {"agent": {"disabled_toolsets": ["image_gen"]}},
        {},
        galaris_memory_enabled=False,
        galaris_image_generation_enabled=False,
        galaris_image_vision_enabled=True,
    )

    assert config["agent"]["disabled_toolsets"] == ["image_gen", "vision"]


def test_previous_galaris_bundle_disables_are_removed_from_disk_config() -> None:
    config = manager_module._merge_hermes_config_layers(
        {
            "skills": {
                "disabled": ["old-bundle", "manual"],
                "_galaris_managed_disabled": ["old-bundle"],
            }
        },
        {},
        {},
        galaris_memory_enabled=False,
    )

    assert config["skills"] == {"disabled": ["manual"]}


@pytest.mark.asyncio
async def test_only_galaris_owned_bundle_opt_out_marker_is_removed() -> None:
    deleted: list[tuple[str, str]] = []

    class Manager:
        async def read_agent_file(self, code: str, filepath: str) -> str:
            assert code == "alice"
            assert filepath == "data/.no-bundled-skills"
            return manager_module._GALARIS_BUNDLED_SKILLS_MARKER_CONTENT

        async def delete_agent_file(self, code: str, filepath: str) -> None:
            deleted.append((code, filepath))

    runtime = HermesAgent(
        cast(Agent, SimpleNamespace(code="alice")),
        cast(HermesManager, Manager()),
    )

    await runtime._restore_bundled_skills_opt_in()

    assert deleted == [("alice", "data/.no-bundled-skills")]


@pytest.mark.asyncio
async def test_operator_bundle_opt_out_marker_is_preserved() -> None:
    deleted: list[tuple[str, str]] = []

    class Manager:
        async def read_agent_file(self, _code: str, _filepath: str) -> str:
            return "operator-managed\n"

        async def delete_agent_file(self, code: str, filepath: str) -> None:
            deleted.append((code, filepath))

    runtime = HermesAgent(
        cast(Agent, SimpleNamespace(code="alice")),
        cast(HermesManager, Manager()),
    )

    await runtime._restore_bundled_skills_opt_in()

    assert deleted == []


def test_memory_plugin_template_projects_modern_and_legacy_layouts() -> None:
    assert manager_module._template_destinations(
        "data/plugins/memory/galaris/__init__.py"
    ) == (
        "data/plugins/memory/galaris/__init__.py",
        "data/plugins/galaris/__init__.py",
    )
    assert manager_module._template_destinations("data/config.yaml") == (
        "data/config.yaml",
    )


def test_remove_galaris_tts_injection_preserves_unmanaged_values() -> None:
    config = {
        "tts": {
            "provider": "elevenlabs",
            "_galaris_managed_provider": "elevenlabs",
            "elevenlabs": {"voice_id": "managed-voice"},
            "speed": 1.2,
        }
    }

    manager_module._remove_galaris_tts_injection(config)

    assert config == {"tts": {"speed": 1.2}}


def test_remove_galaris_stt_injection_preserves_unmanaged_values() -> None:
    config = {
        "stt": {
            "provider": "openai",
            "_galaris_managed_provider": "openai",
            "openai": {"model": "whisper-1", "api_key": "k", "base_url": "http://w"},
            "enabled": False,
        }
    }

    manager_module._remove_galaris_stt_injection(config)

    assert config == {"stt": {"enabled": False}}


@pytest.mark.asyncio
async def test_inject_elevenlabs_tts_uses_dependency_free_command_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SimpleNamespace(
        name="ElevenLabs",
        catalog_code="elevenlabs",
        provider_type="elevenlabs",
        api_key="encrypted",
        configuration={},
        base_url="https://api.elevenlabs.io/v1",
    )
    resource = SimpleNamespace(
        llm_name="voice:voice-42",
        resource_type="voice",
        service_capabilities=["speech"],
        provider=provider,
    )

    async def selected_resource(_identifier: int):
        return resource

    monkeypatch.setattr(manager_module.llm_service, "get_llm", selected_resource)
    monkeypatch.setattr(
        manager_module.llm_provider_service,
        "decrypt_api_key",
        lambda _value: "secret-key",
    )
    config: dict[str, object] = {}
    data_env: dict[str, str] = {}

    await manager_module._inject_tts(
        config,
        data_env,
        cast(Agent, SimpleNamespace(code="alice", voice="tts:8")),
    )

    assert data_env == {
        "ELEVENLABS_API_KEY": "secret-key",
        "GALARIS_ELEVENLABS_TTS_BASE_URL": "https://api.elevenlabs.io/v1",
    }
    assert config["tts"] == {
        "provider": "galaris-elevenlabs",
        "_galaris_managed_provider": "galaris-elevenlabs",
        "providers": {
            "galaris-elevenlabs": {
                "type": "command",
                "command": (
                    'python "${HERMES_HOME:-/opt/data}/scripts/galaris_tts.py" '
                    "--provider elevenlabs "
                    "--voice {voice} --model {model} --input {input_path} "
                    "--output {output_path}"
                ),
                "voice": "voice-42",
                "model": "eleven_multilingual_v2",
                "output_format": "mp3",
                "voice_compatible": True,
            }
        },
    }


@pytest.mark.asyncio
async def test_inject_google_tts_uses_command_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SimpleNamespace(
        name="Google Cloud Text-to-Speech",
        catalog_code="google-cloud-tts",
        provider_type="google_cloud_tts",
        api_key="encrypted",
        configuration={},
        base_url="https://texttospeech.googleapis.com/v1",
    )
    resource = SimpleNamespace(
        llm_name="voice:fr-FR-Neural2-A",
        resource_type="voice",
        service_capabilities=["speech"],
        provider=provider,
    )

    async def selected_resource(_identifier: int):
        return resource

    monkeypatch.setattr(manager_module.llm_service, "get_llm", selected_resource)
    monkeypatch.setattr(
        manager_module.llm_provider_service,
        "decrypt_api_key",
        lambda _value: "google-key",
    )
    config: dict[str, object] = {}
    data_env: dict[str, str] = {}

    await manager_module._inject_tts(
        config,
        data_env,
        cast(Agent, SimpleNamespace(code="alice", voice="tts:9")),
    )

    assert data_env["GOOGLE_CLOUD_TTS_API_KEY"] == "google-key"
    tts = cast(dict[str, object], config["tts"])
    assert tts["provider"] == "galaris-google-cloud-tts"
    providers = cast(dict[str, dict[str, object]], tts["providers"])
    assert providers["galaris-google-cloud-tts"]["voice"] == "fr-FR-Neural2-A"


def _stt_llm(
    *,
    catalog_code: str | None,
    provider_type: str = "openai_compatible",
    base_url: str = "https://api.example/v1",
    api_key: str | None = "encrypted",
    llm_name: str = "whisper-large-v3",
) -> SimpleNamespace:
    provider = SimpleNamespace(
        name="STT Provider",
        catalog_code=catalog_code,
        provider_type=provider_type,
        api_key=api_key,
        configuration={},
        base_url=base_url,
        is_openrouter=lambda: catalog_code == "openrouter",
    )
    return SimpleNamespace(
        llm_name=llm_name,
        resource_type="model",
        service_capabilities=["transcription"],
        provider=provider,
    )


def _patch_transcription_llm(
    monkeypatch: pytest.MonkeyPatch, resource: SimpleNamespace | None
) -> None:
    async def selected_resource(_agent_id: int):
        return resource

    monkeypatch.setattr(
        manager_module.llm_service, "get_transcription_llm", selected_resource
    )
    monkeypatch.setattr(
        manager_module.llm_provider_service,
        "decrypt_api_key",
        lambda value: "secret-key" if value else None,
    )


@pytest.mark.asyncio
async def test_inject_stt_openai_compatible_uses_config_level_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_transcription_llm(
        monkeypatch,
        _stt_llm(catalog_code="openai-api", base_url="https://api.openai.com/v1"),
    )
    config: dict[str, object] = {}
    data_env: dict[str, str] = {}

    await manager_module._inject_stt(
        config, data_env, cast(Agent, SimpleNamespace(id=7, code="alice"))
    )

    assert data_env == {}
    assert config["stt"] == {
        "enabled": True,
        "provider": "openai",
        "_galaris_managed_provider": "openai",
        "openai": {
            "model": "whisper-large-v3",
            "base_url": "https://api.openai.com/v1",
            "api_key": "secret-key",
        },
    }


@pytest.mark.asyncio
async def test_inject_stt_groq_sets_env_key_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_transcription_llm(
        monkeypatch,
        _stt_llm(catalog_code="groq", llm_name="whisper-large-v3-turbo"),
    )
    config: dict[str, object] = {}
    data_env: dict[str, str] = {}

    await manager_module._inject_stt(
        config, data_env, cast(Agent, SimpleNamespace(id=7, code="alice"))
    )

    assert data_env == {
        "GROQ_API_KEY": "secret-key",
        "STT_GROQ_MODEL": "whisper-large-v3-turbo",
    }
    assert config["stt"] == {
        "enabled": True,
        "provider": "groq",
        "_galaris_managed_provider": "groq",
    }


@pytest.mark.asyncio
async def test_inject_stt_elevenlabs_maps_realtime_model_to_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_transcription_llm(
        monkeypatch,
        _stt_llm(
            catalog_code="elevenlabs",
            provider_type="elevenlabs",
            llm_name="scribe_v2_realtime",
        ),
    )
    config: dict[str, object] = {}
    data_env: dict[str, str] = {}

    await manager_module._inject_stt(
        config, data_env, cast(Agent, SimpleNamespace(id=7, code="alice"))
    )

    assert data_env == {"ELEVENLABS_API_KEY": "secret-key"}
    assert config["stt"] == {
        "enabled": True,
        "provider": "elevenlabs",
        "_galaris_managed_provider": "elevenlabs",
        "elevenlabs": {"model_id": "scribe_v2"},
    }


@pytest.mark.asyncio
async def test_inject_stt_openrouter_uses_direct_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_transcription_llm(
        monkeypatch,
        _stt_llm(catalog_code="openrouter", llm_name="openai/whisper-large-v3"),
    )
    config: dict[str, object] = {}
    data_env: dict[str, str] = {}

    await manager_module._inject_stt(
        config, data_env, cast(Agent, SimpleNamespace(id=7, code="alice"))
    )

    assert data_env == {}
    assert config["stt"] == {
        "enabled": True,
        "provider": "openai",
        "_galaris_managed_provider": "openai",
        "openai": {
            "model": "openai/whisper-large-v3",
            "base_url": "https://api.example/v1",
            "api_key": "secret-key",
        },
    }


@pytest.mark.asyncio
async def test_inject_stt_skips_hosted_provider_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_transcription_llm(
        monkeypatch, _stt_llm(catalog_code="mistral", api_key=None)
    )
    config: dict[str, object] = {}
    data_env: dict[str, str] = {}

    await manager_module._inject_stt(
        config, data_env, cast(Agent, SimpleNamespace(id=7, code="alice"))
    )

    assert config == {}
    assert data_env == {}


@pytest.mark.asyncio
async def test_concurrent_syncs_for_one_agent_are_serialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counters = {"running": 0, "max": 0}

    async def fake_sync_config(self: HermesAgent) -> None:
        counters["running"] += 1
        counters["max"] = max(counters["max"], counters["running"])
        await asyncio.sleep(0.02)
        counters["running"] -= 1

    async def fake_command(self: HermesManager, agent_id: str, command: str) -> str:
        return "ok"

    monkeypatch.setattr(HermesAgent, "_sync_config", fake_sync_config)
    monkeypatch.setattr(HermesManager, "run_agent_command", fake_command)
    hermes_manager = HermesManager()
    agent = cast(Agent, SimpleNamespace(id=7, code="alice"))

    await asyncio.gather(
        HermesAgent(agent, hermes_manager).sync(),
        HermesAgent(agent, hermes_manager).sync(),
        HermesAgent(agent, hermes_manager).restart(),
    )

    assert counters["max"] == 1


@pytest.mark.asyncio
async def test_start_synchronizes_configuration_before_lifecycle_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_sync_config(self: HermesAgent) -> None:
        calls.append("sync")

    async def fake_command(
        self: HermesManager,
        agent_id: str,
        command: str,
    ) -> str:
        assert agent_id == "alice"
        calls.append(command)
        return "started"

    monkeypatch.setattr(HermesAgent, "_sync_config", fake_sync_config)
    monkeypatch.setattr(HermesManager, "run_agent_command", fake_command)
    hermes_manager = HermesManager()
    agent = cast(Agent, SimpleNamespace(id=7, code="alice"))

    output = await HermesAgent(agent, hermes_manager).start()

    assert output == "started"
    assert calls == ["sync", "start"]


@pytest.mark.asyncio
async def test_operator_flag_cannot_disable_the_galaris_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def selected_model(_agent: Agent) -> SimpleNamespace:
        return _executor_llm()

    monkeypatch.setattr(manager_module, "_get_effective_llm", selected_model)
    _patch_transcription_llm(monkeypatch, None)
    monkeypatch.setattr(manager_module.runtime_settings, "VOICE_ENABLED", False)
    monkeypatch.setattr(
        bootstrap_settings,
        "APP_HOST",
        "https://galaris.example.test/",
    )
    agent = cast(
        Agent,
        SimpleNamespace(
            id=7,
            code="hermes-agent",
            hermes_use_galaris_llm=False,
            hermes_dashboard_enabled=False,
        ),
    )
    runtime = HermesAgent(agent, cast(HermesManager, SimpleNamespace()))
    data_env = {"OPENAI_API_KEY": "provider-secret"}
    config = {
        "model": {
            "provider": "openai",
            "default": "provider-model",
            "api_key": "${OPENAI_API_KEY}",
        }
    }

    await runtime._inject(data_env, config, "mcp-token")

    assert "OPENAI_API_KEY" not in data_env
    assert data_env["GALARIS_LLM_API_KEY"] == "mcp-token"
    assert config["model"] == {
        "provider": "custom",
        "default": "executor-model",
        "base_url": "https://galaris.example.test/api/llm/openai",
        "api_key": "${GALARIS_LLM_API_KEY}",
        "api_mode": "chat_completions",
        "context_length": 128_000,
    }
    assert config["mcp_servers"]["galaris"]["url"] == (
        "https://galaris.example.test/api/mcp/hermes-agent"
    )
