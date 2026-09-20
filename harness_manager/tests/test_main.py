from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock
import asyncio
import pytest

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

os.environ.setdefault("HARNESS_MANAGER_SECRET", Fernet.generate_key().decode())
os.environ.setdefault("BASE_DIR", "/tmp/galaris-harness-manager-tests")


def _load_manager_module() -> ModuleType:
    module_path = Path(__file__).parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location(
        "galaris_harness_manager_main",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load harness manager from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harness_manager = _load_manager_module()


@pytest.mark.parametrize('text,binary,expected_text,expected_binary', [
    (None, None, 1_000_000, 512_000_000),
    ('0.95367431640625', '488.28125', 1_000_000, 512_000_000),
    ('2', '512', 2_097_152, 536_870_912),
])
def test_size_configuration_accepts_decimal_defaults_and_preserves_legacy_units(monkeypatch, text, binary, expected_text, expected_binary):
    # Developer .env files mounted beside the code must not supply test limits.
    monkeypatch.setattr('dotenv.load_dotenv', lambda: False)
    for name, value in [('MAX_FILE_SIZE_MB', text), ('MAX_RAW_FILE_SIZE_MB', binary)]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    configured = _load_manager_module()
    assert configured.MAX_FILE_SIZE == expected_text
    assert configured.MAX_RAW_FILE_SIZE == expected_binary


def test_download_uses_opened_inode_when_parent_is_replaced(tmp_path):
    instance = tmp_path / "runtime"
    parent = instance / "media"
    parent.mkdir(parents=True)
    (parent / "file").write_bytes(b"allowed")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_bytes(b"outside-secret")
    harness_manager.BASE_DIR = tmp_path
    response = harness_manager.download_raw("runtime", "media/file")
    parent.rename(instance / "original")
    parent.symlink_to(outside, target_is_directory=True)
    async def read():
        return b"".join([chunk async for chunk in response.body_iterator])
    assert asyncio.run(read()) == b"allowed"
    assert response.headers["content-length"] == "7"
    assert response.source.closed


def test_download_closes_descriptor_if_response_delivery_fails(tmp_path):
    instance = tmp_path / "runtime"
    instance.mkdir()
    (instance / "file").write_bytes(b"allowed")
    harness_manager.BASE_DIR = tmp_path
    response = harness_manager.download_raw("runtime", "file")
    async def send(_message):
        raise RuntimeError("client disconnected before headers")
    async def receive():
        return {"type": "http.disconnect"}
    with pytest.raises(RuntimeError):
        asyncio.run(response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send))
    assert response.source.closed


@pytest.mark.parametrize("operation", ["read", "write", "delete", "tree"])
def test_file_operations_reject_symlinked_parent(tmp_path, operation):
    instance = tmp_path / "runtime"
    instance.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "file"
    canary.write_bytes(b"secret")
    (instance / "media").symlink_to(outside, target_is_directory=True)
    client = _client(tmp_path)
    if operation == "read":
        response = client.get("/instances/runtime/raw/media/file")
    elif operation == "write":
        response = client.put("/instances/runtime/raw/media/file", content=b"replacement")
    elif operation == "delete":
        response = client.delete("/instances/runtime/files/media/file")
    else:
        response = client.delete("/instances/runtime/trees/media/subdirectory")
    assert response.status_code == 403
    assert canary.read_bytes() == b"secret"


def test_upload_keeps_original_parent_descriptor_during_swap(tmp_path):
    instance = tmp_path / "runtime"
    parent = instance / "media"
    parent.mkdir(parents=True)
    (parent / "file").write_bytes(b"old")
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "file"
    canary.write_bytes(b"secret")
    harness_manager.BASE_DIR = tmp_path
    class Request:
        async def stream(self):
            yield b"new-"
            parent.rename(instance / "original")
            parent.symlink_to(outside, target_is_directory=True)
            yield b"complete"
    asyncio.run(harness_manager.upload_raw("runtime", "media/file", Request()))
    assert canary.read_bytes() == b"secret"
    assert (instance / "original" / "file").read_bytes() == b"new-complete"


def _client(base_dir: Path) -> TestClient:
    harness_manager.BASE_DIR = base_dir
    harness_manager.ALLOWED_IP = None
    token = harness_manager._fernet.encrypt(b"test").decode()
    return TestClient(
        harness_manager.app,
        headers={"X-Harness-Token": token},
    )


def test_contract_is_runtime_agnostic(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "online",
        "service": "bridge.harness",
        "version": "1.1.0",
        "capabilities": ["compose-lifecycle", "file-share"],
    }
    paths = set(harness_manager.app.openapi()["paths"])
    assert all("hermes" not in path and "kanban" not in path for path in paths)
    assert all(not path.startswith("/agents") for path in paths)


def test_create_instance_does_not_create_runtime_specific_directories(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = client.post("/instances", json={"name": "codex-main"})

    assert response.status_code == 201
    assert response.json() == {"instance": "codex-main", "status": "created"}
    assert list((tmp_path / "codex-main").iterdir()) == []


def test_delete_incomplete_instance_does_not_run_compose(
    tmp_path: Path,
    monkeypatch,
) -> None:
    instance_dir = tmp_path / "codex-main"
    instance_dir.mkdir()
    run = Mock()
    monkeypatch.setattr(harness_manager, "_run_command", run)
    client = _client(tmp_path)

    response = client.delete("/instances/codex-main")

    assert response.status_code == 200
    assert response.json() == {"instance": "codex-main", "status": "deleted"}
    assert not instance_dir.exists()
    run.assert_not_called()


def test_delete_complete_instance_removes_compose_volumes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    instance_dir = tmp_path / "hermes-main"
    instance_dir.mkdir()
    (instance_dir / "Makefile").write_text("stop:\n\ttrue\n", encoding="utf-8")
    (instance_dir / "docker-compose.yaml").write_text(
        "services: {}\nvolumes:\n  runtime: {}\n",
        encoding="utf-8",
    )
    run_make = Mock(return_value="stopped")
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["docker", "compose", "down", "--volumes", "--remove-orphans"],
            returncode=0,
            stdout="",
            stderr="",
        )
    )
    monkeypatch.setattr(harness_manager, "_run_make", run_make)
    monkeypatch.setattr(harness_manager, "_run_command", run)
    client = _client(tmp_path)

    response = client.delete("/instances/hermes-main")

    assert response.status_code == 200
    assert response.json() == {"instance": "hermes-main", "status": "deleted"}
    assert not instance_dir.exists()
    run_make.assert_called_once_with(instance_dir, "stop")
    run.assert_called_once_with(
        ["docker", "compose", "down", "--volumes", "--remove-orphans"],
        cwd=instance_dir,
        timeout=30,
    )


def test_delete_quarantines_data_when_host_permissions_block_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    instance_dir = tmp_path / "hermes-main"
    instance_dir.mkdir()
    (instance_dir / "data").mkdir()
    monkeypatch.setattr(
        harness_manager.shutil,
        "rmtree",
        Mock(side_effect=OSError(39, "directory not empty")),
    )
    client = _client(tmp_path)

    response = client.delete("/instances/hermes-main")

    assert response.status_code == 200
    assert not instance_dir.exists()
    assert len(list(tmp_path.glob(".deleting-hermes-main-*"))) == 1


def test_lifecycle_action_is_bounded(tmp_path: Path, monkeypatch) -> None:
    instance_dir = tmp_path / "claude-code"
    instance_dir.mkdir()
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["make", "restart"],
            returncode=0,
            stdout="ready\n",
            stderr="",
        )
    )
    monkeypatch.setattr(harness_manager, "_run_command", run)
    monkeypatch.setattr(harness_manager, "_get_compose_status", lambda _path: "running")
    client = _client(tmp_path)

    denied = client.post("/instances/claude-code/actions/shell")
    restarted = client.post("/instances/claude-code/actions/restart")

    assert denied.status_code == 400
    assert restarted.status_code == 200
    assert restarted.json() == {
        "instance": "claude-code",
        "action": "restart",
        "output": "ready",
    }
    run.assert_called_once()
    assert run.call_args.kwargs["timeout"] == 1200


def test_restart_starts_an_absent_container(tmp_path: Path, monkeypatch) -> None:
    instance_dir = tmp_path / "claude-code"
    instance_dir.mkdir()
    run_make = Mock(return_value="created")
    monkeypatch.setattr(harness_manager, "_get_compose_status", lambda _path: "absent")
    monkeypatch.setattr(harness_manager, "_run_make", run_make)
    client = _client(tmp_path)

    response = client.post("/instances/claude-code/actions/restart")

    assert response.status_code == 200
    assert response.json() == {
        "instance": "claude-code",
        "action": "restart",
        "output": "created",
    }
    run_make.assert_called_once_with(instance_dir, "start")


def test_cold_start_allows_runtime_image_build(tmp_path: Path, monkeypatch) -> None:
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["make", "start"],
            returncode=0,
            stdout="ready\n",
            stderr="",
        )
    )
    monkeypatch.setattr(harness_manager, "_run_command", run)

    assert harness_manager._run_make(tmp_path, "start") == "ready"
    assert run.call_args.kwargs["timeout"] == 1200


def test_file_routes_reject_path_traversal(tmp_path: Path) -> None:
    (tmp_path / "dsh").mkdir()
    client = _client(tmp_path)

    response = client.get("/instances/dsh/files/../outside.txt")

    assert response.status_code in {403, 404}


def test_text_file_route_writes_secret_atomically_with_requested_mode(
    tmp_path: Path,
) -> None:
    instance = tmp_path / "hermes-main"
    instance.mkdir()
    client = _client(tmp_path)
    encrypted = harness_manager._fernet.encrypt(b"private-key").decode()

    response = client.put(
        "/instances/hermes-main/files/data/.galaris/ssh/id_key?mode=384",
        content=encrypted,
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 200
    key = instance / "data" / ".galaris" / "ssh" / "id_key"
    assert key.read_text(encoding="utf-8") == "private-key"
    assert key.stat().st_mode & 0o777 == 0o600


def test_raw_upload_replaces_only_after_complete_stream(tmp_path):
    import asyncio
    instance = tmp_path / "runtime"
    instance.mkdir()
    target = instance / "media.bin"
    target.write_bytes(b"old")
    harness_manager.BASE_DIR = tmp_path

    class Request:
        async def stream(self):
            yield b"new-"
            assert target.read_bytes() == b"old"
            yield b"complete"

    result = asyncio.run(harness_manager.upload_raw("runtime", "media.bin", Request()))
    assert result["size"] == 12
    assert target.read_bytes() == b"new-complete"
    assert list(instance.iterdir()) == [target]


def test_interrupted_raw_upload_preserves_previous_file(tmp_path):
    import asyncio
    import pytest
    instance = tmp_path / "runtime"
    instance.mkdir()
    target = instance / "media.bin"
    target.write_bytes(b"old")
    harness_manager.BASE_DIR = tmp_path

    class Request:
        async def stream(self):
            yield b"partial"
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(harness_manager.upload_raw("runtime", "media.bin", Request()))
    assert target.read_bytes() == b"old"
    assert list(instance.iterdir()) == [target]


def test_upload_reserves_instance_until_complete(tmp_path):
    instance = tmp_path / "runtime"
    instance.mkdir()
    harness_manager.BASE_DIR = tmp_path
    class Request:
        async def stream(self):
            yield b"first"
            with pytest.raises(harness_manager.HTTPException) as blocked:
                harness_manager.delete_instance("runtime")
            assert blocked.value.status_code == 409
            yield b"last"
    asyncio.run(harness_manager.upload_raw("runtime", "file", Request()))
    assert (instance / "file").read_bytes() == b"firstlast"
    harness_manager.delete_instance("runtime")
    harness_manager.create_instance(harness_manager.CreateInstanceRequest(name="runtime"))
    assert list(instance.iterdir()) == []


def test_delete_keeps_identity_when_runtime_cleanup_fails(tmp_path, monkeypatch):
    instance = tmp_path / "runtime"
    instance.mkdir()
    (instance / "Makefile").write_text("stop:\n\tfalse\n")
    (instance / "compose.yaml").write_text("services: {}")
    harness_manager.BASE_DIR = tmp_path
    error = harness_manager.HTTPException(500, "runtime still present")
    monkeypatch.setattr(harness_manager, "_run_make", Mock(side_effect=error))
    monkeypatch.setattr(harness_manager, "_remove_compose_volumes", Mock(side_effect=error))
    with pytest.raises(harness_manager.HTTPException):
        harness_manager.delete_instance("runtime")
    assert instance.exists()
    with pytest.raises(harness_manager.HTTPException) as conflict:
        harness_manager.create_instance(harness_manager.CreateInstanceRequest(name="runtime"))
    assert conflict.value.status_code == 409


def test_raw_upload_limit_checks_chunks_and_preserves_old_file(tmp_path, monkeypatch):
    instance = tmp_path / "runtime"
    instance.mkdir()
    (instance / "file").write_bytes(b"old")
    harness_manager.BASE_DIR = tmp_path
    monkeypatch.setattr(harness_manager, "MAX_RAW_FILE_SIZE", 5)
    class Request:
        async def stream(self):
            yield b"1234"
            yield b"56"
            pytest.fail("oversized stream was consumed")
    with pytest.raises(harness_manager.HTTPException) as rejected:
        asyncio.run(harness_manager.upload_raw("runtime", "file", Request()))
    assert rejected.value.status_code == 413
    assert (instance / "file").read_bytes() == b"old"


def test_timed_out_command_kills_its_descendants(tmp_path):
    marker = tmp_path / "child.pid"
    script = (
        "import os,signal,time; "
        "pid=os.fork(); "
        f"open({str(marker)!r},'w').write(str(pid)) if pid else None; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        harness_manager._run_command([sys.executable, "-c", script], cwd=tmp_path, timeout=0.5)
    child = int(marker.read_text())
    status = Path(f"/proc/{child}/stat")
    assert not status.exists() or status.read_text().split()[2] == "Z"


@pytest.mark.parametrize("failure", ["create", "flush", "replace"])
def test_storage_exhaustion_preserves_previous_file_and_releases_identity(tmp_path, monkeypatch, failure):
    import errno
    instance = tmp_path / "runtime"
    instance.mkdir()
    target = instance / "file"
    target.write_bytes(b"previous")
    client = _client(tmp_path)
    original_open = os.open
    original_fsync = os.fsync
    original_replace = os.replace

    def full(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    def limited_open(path, flags, *args, **kwargs):
        if flags & os.O_CREAT:
            return full()
        return original_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        if failure == "create":
            patch.setattr(os, "open", limited_open)
        elif failure == "flush":
            patch.setattr(os, "fsync", full)
        else:
            patch.setattr(os, "replace", full)
        response = client.put("/instances/runtime/raw/file", content=b"replacement")
        assert response.status_code == 507
        assert target.read_bytes() == b"previous"
        assert list(instance.iterdir()) == [target]
    assert os.open is original_open and os.fsync is original_fsync and os.replace is original_replace
    assert client.put("/instances/runtime/raw/file", content=b"retry").status_code == 200
    assert target.read_bytes() == b"retry"
