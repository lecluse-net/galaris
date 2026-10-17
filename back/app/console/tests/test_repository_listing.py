"""Synthetic SFTP boundaries for bounded home-relative Git discovery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import asyncssh
from asyncssh.constants import FILEXFER_TYPE_DIRECTORY as DIRECTORY, FILEXFER_TYPE_REGULAR as FILE, FILEXFER_TYPE_SYMLINK as SYMLINK
from asyncssh import SFTPPermissionDenied
from pydantic import SecretStr
import pytest

from app.console import repository, SshConnectionConfig


@pytest.mark.asyncio
async def test_discovery_over_real_ssh_and_sftp_returns_only_synthetic_home_paths(tmp_path):
    class SyntheticServer(asyncssh.SSHServer):
        def begin_auth(self, username):
            return False

    async def process(session):
        assert session.command == "printf '%s' \"$HOME\""
        session.stdout.write(str(tmp_path))
        session.exit(0)

    for path, is_worktree in [("work/project", False), ("work/project-fix", True)]:
        directory = tmp_path / path
        directory.mkdir(parents=True)
        if is_worktree:
            (directory / ".git").write_text("gitdir: ../project/.git/worktrees/fix")
        else:
            (directory / ".git").mkdir()
    (tmp_path / "external").symlink_to(tmp_path.parent, target_is_directory=True)
    key = asyncssh.generate_private_key("ssh-ed25519")
    server = await asyncssh.create_server(SyntheticServer, "127.0.0.1", 0,
        server_host_keys=[key], process_factory=process, sftp_factory=asyncssh.SFTPServer)
    try:
        config = SshConnectionConfig(connection_id=1, host="127.0.0.1", port=server.get_port(),
            username="synthetic", private_key=SecretStr(key.export_private_key().decode()),
            known_host_key=key.export_public_key().decode().strip())
        result = await repository.list_repositories(config)
        assert result.paths == ["work/project", "work/project-fix"]
        assert not result.truncated
    finally:
        server.close()
        await server.wait_closed()


def transport_for(monkeypatch, tree, *, realpaths=None):
    async def scandir(path):
        entries = tree.get(path, [])
        if isinstance(entries, Exception):
            raise entries
        for name, kind in entries:
            yield SimpleNamespace(filename=name, attrs=SimpleNamespace(type=kind))

    async def realpath(path):
        return (realpaths or {}).get(path, path)

    sftp = SimpleNamespace(scandir=scandir, realpath=realpath, exit=Mock())
    connection = SimpleNamespace(start_sftp_client=AsyncMock(return_value=sftp))
    transport = SimpleNamespace(resolve_path=AsyncMock(return_value=("/home/synthetic", ".")),
        persistent_connection=AsyncMock(return_value=connection), close=AsyncMock())
    monkeypatch.setattr(repository, "SshExecutionTransport", lambda config: transport)
    config = SshConnectionConfig(connection_id=1, host="synthetic.test", username="synthetic",
        private_key=SecretStr("synthetic key"), known_host_key="synthetic pinned key")
    return config, transport, sftp


@pytest.mark.asyncio
async def test_lists_checkout_and_worktree_paths_without_following_links_or_entering_metadata(monkeypatch):
    config, transport, sftp = transport_for(monkeypatch, {
        "/home/synthetic": [("work", DIRECTORY), ("external", SYMLINK), (".cache", DIRECTORY)],
        "/home/synthetic/work": [("project", DIRECTORY), ("project-fix", DIRECTORY), ("plain", DIRECTORY)],
        "/home/synthetic/work/project": [(".git", DIRECTORY), ("node_modules", DIRECTORY)],
        "/home/synthetic/work/project-fix": [(".git", FILE)],
        "/home/synthetic/external": [(".git", DIRECTORY)],
        "/home/synthetic/.cache": [(".git", DIRECTORY)],
        "/home/synthetic/work/project/.git": [("nested", DIRECTORY)],
    })
    result = await repository.list_repositories(config)
    assert result.paths == ["work/project", "work/project-fix"]
    assert not result.truncated
    transport.close.assert_awaited_once()
    sftp.exit.assert_called_once()


@pytest.mark.asyncio
async def test_partial_listing_keeps_accessible_results_and_rejects_replaced_directories(monkeypatch):
    config, _, _ = transport_for(monkeypatch, {
        "/home/synthetic": [("project", DIRECTORY), ("denied", DIRECTORY), ("replaced", DIRECTORY)],
        "/home/synthetic/project": [(".git", FILE)],
        "/home/synthetic/denied": SFTPPermissionDenied("synthetic denial"),
        "/outside": [(".git", DIRECTORY)],
    }, realpaths={"/home/synthetic/replaced": "/outside"})
    result = await repository.list_repositories(config)
    assert result.paths == ["project"]
    assert result.truncated


@pytest.mark.asyncio
async def test_repository_limit_is_explicit_and_does_not_lose_already_found_paths(monkeypatch):
    tree = {"/home/synthetic": [(f"project-{index:03}", DIRECTORY) for index in range(101)]}
    tree.update({f"/home/synthetic/project-{index:03}": [(".git", FILE)] for index in range(101)})
    config, transport, sftp = transport_for(monkeypatch, tree)
    result = await repository.list_repositories(config)
    assert len(result.paths) == 100
    assert result.truncated
    transport.close.assert_awaited_once()
    sftp.exit.assert_called_once()
