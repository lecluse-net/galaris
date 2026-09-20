import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from cryptography.fernet import Fernet

from bridge.harness.manager import HarnessManager, HarnessManagerError

# pyright: reportPrivateUsage=false

manager_module = importlib.import_module("bridge.harness.manager")


def test_auth_uses_deployment_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = Fernet.generate_key().decode()
    monkeypatch.setattr(manager_module.settings, "HARNESS_MANAGER_SECRET", secret)

    headers = HarnessManager()._auth_headers()

    assert set(headers) == {"X-Harness-Token"}
    assert Fernet(secret.encode()).decrypt(headers["X-Harness-Token"].encode()) == b"auth"


@pytest.mark.asyncio
async def test_instance_operations_use_generic_contract() -> None:
    harness_manager = HarnessManager()
    request = AsyncMock(
        side_effect=[
            SimpleNamespace(json=lambda: {"status": "running"}),
            SimpleNamespace(json=lambda: {"status": "created"}),
            SimpleNamespace(status_code=200, json=lambda: {"status": "deleted"}),
            SimpleNamespace(json=lambda: {"output": "done"}),
            SimpleNamespace(json=lambda: {"instances": ["alice"]}),
            SimpleNamespace(json=lambda: {"lines": ["ready"]}),
        ]
    )
    harness_manager._request = request

    assert await harness_manager.get_instance_status("alice") == "running"
    await harness_manager.create_instance("alice")
    await harness_manager.delete_instance("alice")
    assert await harness_manager.run_action("alice", "restart") == "done"
    assert await harness_manager.list_instances() == ["alice"]
    assert await harness_manager.get_logs("alice") == ["ready"]
    assert request.await_args_list == [
        call("GET", "/instances/alice/status", timeout=15.0),
        call("POST", "/instances", json={"name": "alice", "template": None}),
        call(
            "DELETE",
            "/instances/alice",
            acceptable_statuses=frozenset({404}),
        ),
        call("POST", "/instances/alice/actions/restart", timeout=1230.0),
        call("GET", "/instances"),
        call("GET", "/instances/alice/logs?lines=300", timeout=20.0),
    ]


@pytest.mark.asyncio
async def test_instance_status_propagates_manager_unavailability() -> None:
    harness_manager = HarnessManager()
    harness_manager._request = AsyncMock(side_effect=HarnessManagerError("unreachable"))

    with pytest.raises(HarnessManagerError, match="unreachable"):
        await harness_manager.get_instance_status("alice")


@pytest.mark.asyncio
async def test_build_actions_allow_host_manager_timeout_margin() -> None:
    harness_manager = HarnessManager()
    request = AsyncMock(
        return_value=SimpleNamespace(json=lambda: {"output": "ready"})
    )
    harness_manager._request = request

    for action in ("start", "restart", "update"):
        assert await harness_manager.run_action("alice", action) == "ready"

    assert request.await_args_list == [
        call("POST", f"/instances/alice/actions/{action}", timeout=1230.0)
        for action in ("start", "restart", "update")
    ]


@pytest.mark.asyncio
async def test_reachability_requires_generic_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        manager_module.settings,
        "HARNESS_MANAGER_SECRET",
        Fernet.generate_key().decode(),
    )
    harness_manager = HarnessManager()
    harness_manager._request = AsyncMock(
        side_effect=[
            SimpleNamespace(
                json=lambda: {
                    "service": "bridge.harness",
                    "capabilities": ["compose-lifecycle", "file-share"],
                }
            ),
            SimpleNamespace(
                json=lambda: {
                    "service": "runtime-specific-manager",
                    "capabilities": ["compose-lifecycle", "file-share"],
                }
            ),
        ]
    )

    assert await harness_manager.check_reachable() is True
    assert await harness_manager.check_reachable() is False


@pytest.mark.asyncio
async def test_delete_instance_is_idempotent_when_runtime_is_absent() -> None:
    harness_manager = HarnessManager()
    harness_manager._request = AsyncMock(
        return_value=SimpleNamespace(status_code=404)
    )

    await harness_manager.delete_instance("alice")

    harness_manager._request.assert_awaited_once_with(
        "DELETE",
        "/instances/alice",
        acceptable_statuses=frozenset({404}),
    )


@pytest.mark.asyncio
async def test_text_file_write_forwards_the_requested_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = Fernet.generate_key().decode()
    monkeypatch.setattr(manager_module.settings, "HARNESS_MANAGER_SECRET", secret)
    harness_manager = HarnessManager()
    request = AsyncMock()
    harness_manager._request = request

    await harness_manager.write_text_file(
        "alice",
        "data/.galaris/ssh/id_key",
        "private-key",
        mode=0o600,
    )

    request.assert_awaited_once()
    args = request.await_args
    assert args.args == (
        "PUT",
        "/instances/alice/files/data/.galaris/ssh/id_key",
    )
    assert args.kwargs["params"] == {"mode": 0o600}
    assert Fernet(secret.encode()).decrypt(args.kwargs["content"]) == b"private-key"
