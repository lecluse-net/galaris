"""Exercise continuation and containment at the external SFTP boundary."""

import json
from types import SimpleNamespace

import pytest
import asyncssh

from app.console.file_transport import SshAgentFileTransport


@pytest.mark.asyncio
async def test_console_pages_preserve_every_file_and_reject_cross_directory_cursors(monkeypatch):
    paths = [f"/home/synthetic/report-{index:03}.txt" for index in range(105)]
    paths += ["/home/synthetic/escape", "/home/synthetic/symlink"]

    class Sftp:
        async def scandir(self, _base):
            for path in reversed(paths):
                yield SimpleNamespace(filename=path.rsplit("/", 1)[-1])

        async def realpath(self, path):
            return "/outside/private" if path.endswith("/escape") else path

        async def lstat(self, path):
            return SimpleNamespace(type=3 if path.endswith("/symlink") else 1, size=24, mtime=None)

        def exit(self):
            pass

    async def home():
        return "/home/synthetic"

    transport = SshAgentFileTransport(SimpleNamespace(home=home))

    async def client():
        return Sftp()

    async def resolve(_sftp, path):
        return ("/home/synthetic", ".") if path == "." else ("/home/synthetic/other", "other")

    monkeypatch.setattr(transport, "_client", client)
    monkeypatch.setattr(transport, "_resolve_existing", resolve)
    result, sizes = [], []
    cursor = first_cursor = None
    while True:
        listing = await transport.resource_list_page(".", recursive=False, limit=50, cursor=cursor)
        sizes.append(len(listing.entries))
        result.extend(entry.path for entry in listing.entries)
        if first_cursor is None:
            first_cursor = listing.next_cursor
        cursor = listing.next_cursor
        if cursor is None:
            assert not listing.truncated
            break
    assert sizes == [50, 50, 5]
    assert result == [f"report-{index:03}.txt" for index in range(105)]
    with pytest.raises(ValueError, match="cursor"):
        await transport.resource_list_page("other", recursive=False, limit=50, cursor=first_cursor)
    for invalid in ["bad", "{}", json.dumps(["/home/synthetic", 42])]:
        with pytest.raises(ValueError, match="cursor"):
            await transport.resource_list_page(".", recursive=False, limit=50, cursor=invalid)


@pytest.mark.asyncio
async def test_directory_mutations_against_sftp_preserve_collisions_roots_and_symlinks(tmp_path):
    home = tmp_path / "home" / "synthetic"
    tree = home / "tree"
    (tree / "nested").mkdir(parents=True)
    (tree / "nested" / "file.txt").write_text("Synthetic tree bytes")
    (home / "existing").mkdir()

    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            return False

    server = await asyncssh.create_server(Server, "127.0.0.1", 0,
        server_host_keys=[asyncssh.generate_private_key("ssh-ed25519")],
        sftp_factory=lambda channel: asyncssh.SFTPServer(channel, chroot=str(tmp_path)))
    try:
        async with asyncssh.connect("127.0.0.1", server.get_port(), username="synthetic", known_hosts=None) as connection:
            async def remote_home():
                return "/home/synthetic"

            async def remote_connection():
                return connection

            transport = SshAgentFileTransport(SimpleNamespace(home=remote_home, connection=remote_connection))
            with pytest.raises(asyncssh.SFTPError):
                await transport.file_move("tree", "existing")
            assert (tree / "nested" / "file.txt").read_text() == "Synthetic tree bytes"
            renamed = await transport.file_move("tree", "renamed")
            assert renamed.path == "renamed"
            with pytest.raises(IsADirectoryError):
                await transport.file_delete("renamed")
            with pytest.raises(PermissionError):
                await transport.resource_delete_collection(".")
            (home / "renamed" / "link").symlink_to("../existing", target_is_directory=True)
            with pytest.raises(PermissionError):
                await transport.resource_delete_collection("renamed")
            assert (home / "renamed" / "nested" / "file.txt").exists()
            (home / "renamed" / "link").unlink()
            await transport.resource_delete_collection("renamed")
            assert not (home / "renamed").exists()
            assert home.exists() and (home / "existing").exists()
    finally:
        server.close()
        await server.wait_closed()
