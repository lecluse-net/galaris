from typing import Any, cast
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncssh
import pytest
import pytest_asyncio

from app.console.file_transport import SshAgentFileTransport
from app.tools.contracts import ToolCallRejectedError
from app.file_share.path_normalization import (
    FilePathError,
    normalize_transport_reference,
    normalize_file_reference,
)
from bridge.hermes import paths as hermes_paths


def test_file_reference_normalizes_safe_root_aliases() -> None:
    assert normalize_file_reference("report.pdf") == "report.pdf"
    assert normalize_file_reference("./reports//report.pdf") == "reports/report.pdf"
    assert normalize_file_reference("~/report.pdf") == "report.pdf"
    assert normalize_file_reference(
        "/provider-root/reports/report.pdf",
        root="/provider-root",
    ) == "reports/report.pdf"
    assert normalize_file_reference(
        "exchange/reports/report.pdf",
        aliases=("exchange",),
    ) == "reports/report.pdf"
    assert normalize_file_reference("/", root="/provider-root", allow_root=True) == "."


@pytest.mark.parametrize(
    "value",
    (
        "../outside.txt",
        "/tmp/outside.txt",
        "file:///provider-root/report.pdf",
        "C:/provider-root/report.pdf",
    ),
)
def test_file_reference_rejects_unsafe_or_non_provider_paths(value: str) -> None:
    with pytest.raises(FilePathError):
        normalize_file_reference(value, root="/provider-root")


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("mon_fichier.ext", "mon_fichier.ext"),
        ("./mon_fichier.ext", "mon_fichier.ext"),
        ("galaris/mon_fichier.ext", "mon_fichier.ext"),
        ("data/galaris/mon_fichier.ext", "mon_fichier.ext"),
        ("opt/data/galaris/mon_fichier.ext", "mon_fichier.ext"),
        ("/opt/data/galaris/mon_fichier.ext", "mon_fichier.ext"),
        ("~/mon_fichier.ext", "mon_fichier.ext"),
    ),
)
def test_hermes_runtime_path_matrix(value: str, expected: str) -> None:
    assert hermes_paths.to_runtime_path(value) == expected


def test_hermes_runtime_path_rejects_absolute_paths_outside_exchange_root() -> None:
    with pytest.raises(FilePathError):
        hermes_paths.to_runtime_path("/tmp/mon_fichier.ext")


@pytest.mark.asyncio
async def test_ssh_transport_normalizes_home_aliases() -> None:
    class Execution:
        async def home(self) -> str:
            return "/home/alice"

    transport = SshAgentFileTransport(cast(Any, Execution()))

    assert await normalize_transport_reference(transport, "~/report.pdf") == "report.pdf"
    assert await normalize_transport_reference(
        transport,
        "/home/alice/reports/report.pdf",
    ) == "reports/report.pdf"
    assert await normalize_transport_reference(
        transport,
        "home/alice/reports/report.pdf",
    ) == "reports/report.pdf"
    assert await transport._lexical(  # pyright: ignore[reportPrivateUsage]
        "home/alice/reports/report.pdf"
    ) == ("/home/alice/reports/report.pdf", "reports/report.pdf")
    with pytest.raises(FilePathError):
        await normalize_transport_reference(transport, "/tmp/report.pdf")


@pytest.mark.asyncio
async def test_ssh_transport_normalizes_a_missing_sftp_entry() -> None:
    class Sftp:
        async def realpath(self, path: str) -> str:
            return path

        async def lstat(self, _path: str) -> None:
            raise asyncssh.SFTPNoSuchFile("No such file")

        def exit(self) -> None:
            return None

    class Connection:
        async def start_sftp_client(self) -> Sftp:
            return Sftp()

    class Execution:
        async def home(self) -> str:
            return "/home/alice"

        async def connection(self) -> Connection:
            return Connection()

    transport = SshAgentFileTransport(cast(Any, Execution()))

    with pytest.raises(FileNotFoundError, match="missing.txt"):
        await transport.file_info("missing.txt", include_sha256=False)


@pytest_asyncio.fixture
async def ssh_files(tmp_path):
    class Authentication(asyncssh.SSHServer):
        def begin_auth(self, username):
            return False

    home = tmp_path / "home"
    home.mkdir()
    listener = await asyncssh.create_server(
        Authentication,
        "127.0.0.1",
        0,
        server_host_keys=[asyncssh.generate_private_key("ssh-ed25519")],
        sftp_factory=asyncssh.SFTPServer,
    )
    try:
        async with asyncssh.connect(
            "127.0.0.1", port=listener.get_port(), known_hosts=None,
        ) as connection:
            execution = SimpleNamespace(
                home=AsyncMock(return_value=str(home)),
                connection=AsyncMock(return_value=connection),
            )
            yield SshAgentFileTransport(execution), home
    finally:
        listener.close()
        await listener.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["upload", "append", "copy", "move"])
async def test_ssh_files_create_missing_parents_and_reuse_existing_directories(
    ssh_files, operation,
):
    transport, home = ssh_files
    source = home / "source.md"
    content = "# Annexe\n\n| Colonne |\n|---|\n| Préservé |\n"
    source.write_text(content)
    for filename in ("annexe.md", "second.md"):
        destination = f"conversion/nested/{filename}"
        if operation == "upload":
            assert await transport.upload_from(source, destination) == destination
        elif operation == "append":
            await transport.file_append_text(destination, content)
        elif operation == "copy":
            await transport.file_copy("source.md", destination)
        else:
            source.write_text(content)
            await transport.file_move("source.md", destination)
            assert not source.exists()
        assert (home / destination).read_text() == content
    assert not list(home.rglob("*.galaris-part-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("outside_exists", [False, True])
async def test_ssh_upload_refuses_symlink_escape_before_creating_parents(
    ssh_files, outside_exists,
):
    transport, home = ssh_files
    outside = home.parent / "outside"
    if outside_exists:
        outside.mkdir()
    (home / "escape").symlink_to(outside, target_is_directory=True)
    source = home / "source.md"
    source.write_text("preserved")

    with pytest.raises(ToolCallRejectedError) as failure:
        await transport.upload_from(source, "escape/nested/annexe.md")
    assert "outside the SSH home" in str(failure.value.__cause__)

    assert outside.exists() == outside_exists
    assert not (outside / "nested").exists()
    assert source.read_text() == "preserved"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["source", "publish", "cleanup"])
async def test_ssh_upload_only_proves_rejection_before_publication_and_after_cleanup(
    ssh_files, monkeypatch, failure_stage,
):
    transport, home = ssh_files
    destination = home / "annexe.md"
    destination.write_bytes(b"original")
    sftp = await transport._client()
    monkeypatch.setattr(transport, "_client", AsyncMock(return_value=sftp))
    rename = sftp.posix_rename

    async def lost_publish_reply(*args):
        await rename(*args)
        raise TimeoutError("published but reply lost")

    if failure_stage == "publish":
        monkeypatch.setattr(sftp, "posix_rename", lost_publish_reply)
    elif failure_stage == "cleanup":
        monkeypatch.setattr(sftp, "remove", AsyncMock(side_effect=OSError("cleanup failed")))

    async def source():
        yield b"replacement"
        if failure_stage != "publish":
            raise TimeoutError("source interrupted")

    error = ToolCallRejectedError if failure_stage == "source" else TimeoutError
    with pytest.raises(error):
        await transport.upload_stream(source(), "annexe.md")
    assert destination.read_bytes() == (b"replacement" if failure_stage == "publish" else b"original")
    assert bool(list(home.glob("*.galaris-part-*"))) == (failure_stage == "cleanup")
