"""Registry of file-sharing bridges available in Galaris.

Each bridge declares an identifier, display label, required connection parameters, and a factory
for resolved configuration. Future plugins may call ``register`` dynamically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from pydantic import BaseModel

from bridge.affine import AffineFileClient
from bridge.grav import GravFileClient
from core.i18n import render_prompt, t

from .transport import FileTransport


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

    def info(self) -> FileShareBridgeInfo:
        return FileShareBridgeInfo(
            service=self.service,
            label=self.label,
            supports_share=self.supports_share,
            params=list(self.params),
        )


BRIDGES: Dict[str, FileShareBridge] = {}


def register(bridge: FileShareBridge) -> None:
    """Register or replace a bridge."""
    BRIDGES[bridge.service] = bridge


def _message(key: str, language: str | None = None, **values: Any) -> str:
    return render_prompt(t(f"file_share.errors.{key}", language), **values)


def get_bridge(service: str, *, language: str | None = None) -> FileShareBridge:
    bridge = BRIDGES.get(service)
    if bridge is None:
        raise ValueError(_message(
            "unknown_bridge",
            language,
            service=service,
            available=", ".join(BRIDGES) or "none",
        ))
    return bridge


def available_bridges() -> list[FileShareBridgeInfo]:
    """Return available bridges for dynamic configuration forms."""
    return [b.info() for b in BRIDGES.values()]


# =============================================================================
# Built-in bridges.
# =============================================================================

register(
    FileShareBridge(
        service="grav",
        label="Grav (media)",
        params=(
            FileShareParamInfo(key="api_key", label="API key", type="password"),
            FileShareParamInfo(key="upload_path", label="Upload route", type="string", required=False),
            FileShareParamInfo(key="default_page", label="Default page", type="string", required=False),
        ),
        build=lambda base_url, p: GravFileClient(
            base_url=base_url,
            api_key=p["api_key"],
            upload_path=p.get("upload_path") or "/api/v1/pages/{page}/media",
            default_page=p.get("default_page") or "",
        ),
    )
)

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
        build=lambda base_url, p: AffineFileClient(
            base_url=base_url,
            email=p["email"],
            password=p["password"],
        ),
    )
)
