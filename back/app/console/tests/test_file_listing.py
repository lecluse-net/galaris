"""Exercise continuation and containment at the external SFTP boundary."""

import json
from types import SimpleNamespace

import pytest

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
