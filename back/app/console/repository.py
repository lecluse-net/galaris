"""Bounded Git discovery and dedicated IDE forwarding owned by Console."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import asyncio
from collections import deque
import hashlib
import json
import shlex
from pathlib import PurePosixPath

from asyncssh import SFTPError
from asyncssh.constants import FILEXFER_TYPE_DIRECTORY, FILEXFER_TYPE_REGULAR

from .contracts import RepositoryListing, RepositoryTarget, SshConnectionConfig
from .ssh_client import SshExecutionTransport


async def list_repositories(config: SshConnectionConfig) -> RepositoryListing:
    """Bounded, read-only SFTP discovery without following directory symlinks."""
    transport = SshExecutionTransport(config)
    listing = RepositoryListing()
    try:
        async with asyncio.timeout(20):
            home, _ = await transport.resolve_path(".")
            connection = await transport.persistent_connection()
            sftp = await connection.start_sftp_client()
            try:
                pending = deque([(home, 0)])
                visited = 0
                while pending:
                    directory, depth = pending.popleft()
                    try:
                        # Revalidate before scanning: directories can change during discovery.
                        if str(await sftp.realpath(directory)) != directory:
                            listing.truncated = True
                            continue
                        async for entry in sftp.scandir(directory):
                            name = str(entry.filename)
                            if name in {".", ".."}:
                                continue
                            visited += 1
                            if visited > 10000:
                                listing.truncated = True
                                return listing
                            if "/" in name or "\\" in name or any(ord(character) < 32 for character in name):
                                listing.truncated = True
                                continue
                            if name == ".git" and entry.attrs.type in {FILEXFER_TYPE_DIRECTORY, FILEXFER_TYPE_REGULAR}:
                                if directory != home:
                                    listing.paths.append(PurePosixPath(directory).relative_to(home).as_posix())
                                    if len(listing.paths) >= 100:
                                        listing.truncated = True
                                        return listing
                            elif (entry.attrs.type == FILEXFER_TYPE_DIRECTORY and not name.startswith(".")
                                  and name not in {"node_modules", "__pycache__"}):
                                if depth >= 8:
                                    listing.truncated = True
                                else:
                                    pending.append((str(PurePosixPath(directory) / name), depth + 1))
                    except SFTPError:
                        listing.truncated = True
            finally:
                sftp.exit()
    except TimeoutError:
        listing.truncated = True
    finally:
        listing.paths.sort()
        await transport.close()
    return listing


def connection_generation(config: SshConnectionConfig) -> str:
    # Includes credentials, not only the mutable Connection primary key.
    material = {"config": config.model_dump(mode="json"),
                "key": config.private_key.get_secret_value(),
                "passphrase": config.private_key_passphrase.get_secret_value() if config.private_key_passphrase else None,
                "runtime": config.code_runtime_token.get_secret_value() if config.code_runtime_token else None}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


async def discover_repository(config: SshConnectionConfig, path: str) -> RepositoryTarget:
    if len(path) > 4096 or any(character in path for character in "\r\n\x00"):
        raise ValueError("Invalid repository path")
    transport = SshExecutionTransport(config)
    try:
        root, _ = await transport.resolve_path(path)
        if any(character in root for character in "\r\n\x00"):
            raise ValueError("Repository paths must not contain line breaks")
        quoted = shlex.quote(root)
        result = await transport.exec(
            f"git -C {quoted} rev-parse --path-format=absolute --show-toplevel --absolute-git-dir --git-common-dir",
            timeout_s=10,
        )
        paths = result.stdout.splitlines()
        if result.exit_code != 0 or len(paths) != 3:
            raise ValueError("A non-bare Git checkout is required")
        canonical = [await transport.resolve_path(value) for value in paths]
        root = canonical[0][0]
        metadata = tuple(sorted({value[0] for value in canonical[1:]}))
        observation = await transport.exec(
            "stat -Lc '%d:%i' " + " ".join(shlex.quote(value) for value in (root, *metadata)) + " && "
            f"(git -C {shlex.quote(root)} symbolic-ref --quiet --short HEAD || true) && "
            f"(git -C {shlex.quote(root)} rev-parse --verify HEAD 2>/dev/null || true)",
            timeout_s=10,
        )
        lines = observation.stdout.splitlines()
        if observation.exit_code != 0 or not lines or ":" not in lines[0]:
            raise ValueError("Unable to identify the checkout directory")
        count = 1 + len(metadata)
        identities = lines[:count]
        if len(identities) != count or any(":" not in identity for identity in identities):
            raise ValueError("Unable to identify Git metadata")
        head = lines[-1] if len(lines) > count and len(lines[-1]) in (40, 64) and all(c in "0123456789abcdef" for c in lines[-1]) else None
        branch = lines[count] if len(lines) > count and lines[count] != head else None
        generation = hashlib.sha256(json.dumps([connection_generation(config), root, metadata, identities]).encode()).hexdigest()
        home, _ = await transport.resolve_path(".")
        if root == home:
            raise ValueError("The account home cannot be exposed as a repository")
        return RepositoryTarget(home=home, root=root, git_paths=metadata, generation=generation,
            root_identity=identities[0], git_identities=tuple(identities[1:]), branch=branch, head=head)
    finally:
        await transport.close()


@asynccontextmanager
async def code_runtime_tunnel(config: SshConnectionConfig) -> AsyncGenerator[str]:
    """Independent pinned SSH transport, restricted to the configured loopback port."""
    if config.code_runtime_port is None or config.code_runtime_token is None:
        raise RuntimeError("The external Console has no prepared code runtime")
    transport = SshExecutionTransport(config)
    connection = await transport.persistent_connection()
    listener = None
    try:
        listener = await connection.forward_local_port("127.0.0.1", 0, "127.0.0.1", config.code_runtime_port)
        yield f"http://127.0.0.1:{listener.get_port()}"
    finally:
        if listener is not None:
            listener.close()
            await listener.wait_closed()
        await transport.close()
