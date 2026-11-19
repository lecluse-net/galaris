"""Synthetic read-only protocol with a single file reserved to its connection."""

from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.file_share import FileEntry, FileListing, FileShareBridge, FileShareParamInfo
from app.plugin.contracts import PluginRuntimeContext
from core.util import DEFAULT_DOWNLOAD_BYTES, copy_download


class StorageTransport:
    def __init__(self, base_url: str, token: str) -> None:
        url = urlsplit(base_url)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username is not None or url.query or url.fragment:
            raise ValueError("A Sample Storage HTTP endpoint without embedded credentials is required")
        self._url = base_url.rstrip("/") + "/note.txt"
        self._headers = {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _check_file(path: str) -> None:
        if path.lstrip("/") != "note.txt":
            raise FileNotFoundError("Sample file not found")

    async def resource_info(self, path: str, *, include_sha256: bool = False) -> FileEntry:
        self._check_file(path)
        async with httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False) as client:
            response = await client.head(self._url, headers=self._headers)
            response.raise_for_status()
        raw_size = response.headers.get("content-length", "")
        return FileEntry(path="note.txt", is_dir=False, size=int(raw_size) if raw_size.isdecimal() else None,
            mime_type="text/plain")

    async def resource_list(self, path: str, *, recursive: bool, limit: int) -> FileListing:
        if path.strip("/"):
            raise NotADirectoryError("Sample Storage only has a root collection")
        return FileListing(path="/", entries=(await self.resource_info("note.txt"),))

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = DEFAULT_DOWNLOAD_BYTES) -> int:
        self._check_file(remote)
        async with httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False) as client:
            async with client.stream("GET", self._url, headers=self._headers) as response:
                response.raise_for_status()
                return await copy_download(response.aiter_bytes(), dest, max_bytes=max_bytes)

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        raise PermissionError("Sample Storage is read-only")


def plugin_file_share_protocol(_context: PluginRuntimeContext) -> FileShareBridge:
    return FileShareBridge(service="sample.storage", label="Sample Storage",
        params=(FileShareParamInfo(key="token", label="Token", type="password"),),
        build=lambda base_url, params: StorageTransport(base_url, params["token"]), writable=False,
        indexing_modes=("excluded",))
