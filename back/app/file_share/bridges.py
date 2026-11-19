"""Registry of file-sharing bridges available in Galaris.

Each bridge declares an identifier, display label, required connection parameters, and a factory
for resolved configuration. Future plugins may call ``register`` dynamically.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Callable, Dict

from pydantic import BaseModel

from bridge.affine import AffineFileClient
from core.i18n import render_prompt, t

from .transport import FileTransport
from .file_contracts import FileEntry
from .service_references import normalize_source_reference
from app.services.contracts import FileIndexingMode


class AffineResourceTransport(AffineFileClient):
    """Adapt AFFiNE blob headers to the file facade's metadata contract."""

    async def resource_info(self, path: str, *, include_sha256: bool = False) -> FileEntry:
        if "/" not in path.strip("/"):
            # A workspace is an upload target, not a blob that this API can stat.
            raise FileNotFoundError(path)
        source = normalize_source_reference("affine", path)
        blob = await self.blob_metadata(source.remote, target=source.target)
        return FileEntry(path=path, is_dir=False, size=blob.size, mime_type=blob.media_type)


# =============================================================================
# Public bridge description used to generate the configuration form.
# =============================================================================

class FileShareParamInfo(BaseModel):
    """Bridge parameter mapped to an agent connection parameter."""
    key: str
    label: str
    type: str = "string"  # "string" | "password"
    required: bool = True


class FileShareBridgeInfo(BaseModel):
    """Bridge description exposed to the API and frontend."""
    service: str
    label: str
    supports_share: bool = False
    indexing_modes: tuple[FileIndexingMode, ...] = ("excluded", "known_uris")
    params: list[FileShareParamInfo]


# =============================================================================
# Registry
# =============================================================================

@dataclass(frozen=True)
class FileShareBridge:
    service: str
    label: str
    params: tuple[FileShareParamInfo, ...]
    build: Callable[[str, Dict[str, str]], FileTransport]
    supports_share: bool = False
    indexing_modes: tuple[FileIndexingMode, ...] = ("excluded", "known_uris")
    writable: bool = True

    def info(self) -> FileShareBridgeInfo:
        return FileShareBridgeInfo(
            service=self.service,
            label=self.label,
            supports_share=self.supports_share,
            indexing_modes=self.indexing_modes,
            params=list(self.params),
        )


BRIDGES: Dict[str, FileShareBridge] = {}
_plugin_bridges: dict[str, FileShareBridge] = {}


def register(bridge: FileShareBridge) -> None:
    """Register or replace a bridge."""
    BRIDGES[bridge.service] = bridge


def prepare_plugin_file_share_bridges(bridges: Iterable[FileShareBridge]) -> Callable[[], None]:
    prepared: dict[str, FileShareBridge] = {}
    for bridge in bridges:
        if bridge.service in BRIDGES or bridge.service in prepared:
            raise ValueError(f"Duplicate file-sharing protocol: {bridge.service}")
        if len({param.key for param in bridge.params}) != len(bridge.params):
            raise ValueError(f"Duplicate connection parameter for {bridge.service}")
        prepared[bridge.service] = bridge

    def publish() -> None:
        global _plugin_bridges
        _plugin_bridges = prepared

    return publish


def find_bridge(service: str) -> FileShareBridge | None:
    return BRIDGES.get(service) or _plugin_bridges.get(service)


def _message(key: str, language: str | None = None, **values: Any) -> str:
    return render_prompt(t(f"file_share.errors.{key}", language), **values)


def get_bridge(service: str, *, language: str | None = None) -> FileShareBridge:
    bridge = find_bridge(service)
    if bridge is None:
        raise ValueError(_message(
            "unknown_bridge",
            language,
            service=service,
            available=", ".join((*BRIDGES, *_plugin_bridges)) or "none",
        ))
    return bridge


def available_bridges() -> list[FileShareBridgeInfo]:
    """Return available bridges for dynamic configuration forms."""
    return [b.info() for b in (*BRIDGES.values(), *_plugin_bridges.values())]


# =============================================================================
# Built-in bridges.
# =============================================================================

register(
    FileShareBridge(
        service="affine",
        label="AFFiNE (blobs)",
        params=(
            # AFFiNE uses an email/password session rather than a token. The workspace is
            # supplied at the start of each operation path.
            FileShareParamInfo(key="email", label="AFFiNE account email", type="string"),
            FileShareParamInfo(key="password", label="AFFiNE password", type="password"),
        ),
        build=lambda base_url, p: AffineResourceTransport(
            base_url=base_url,
            email=p["email"],
            password=p["password"],
        ),
    )
)
