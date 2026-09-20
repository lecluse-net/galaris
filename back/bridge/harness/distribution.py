"""Deterministic source archives; installation secrets are added only on request."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from pydantic import BaseModel

from core.settings import settings

FILES = ("main.py", "update.py", "Makefile", "pyproject.toml", "uv.lock", "README.md", ".env.example")


def source_directory() -> Path:
    checkout = Path(__file__).resolve().parents[3] / "harness_manager"
    return checkout if checkout.is_dir() else Path("/opt/galaris-harness-manager")


def version_tuple(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}", value):
        return None
    return tuple(int(part) for part in value.split("."))


def source_version(source: Path | None = None) -> str:
    project = tomllib.loads(((source or source_directory()) / "pyproject.toml").read_text())["project"]
    value: object = project["version"]
    if not isinstance(value, str) or version_tuple(value) is None:
        raise ValueError("Invalid manager source version")
    return value


def update_url() -> str:
    return f"{settings.APP_API_URL.rstrip('/')}/harness-manager/updates"


class ReleaseManifest(BaseModel):
    version: str
    sha256: str
    size: int
    update_url: str


@dataclass(frozen=True)
class Release:
    content: bytes
    manifest: ReleaseManifest


def build_release(environment: str | None = None, *, source: Path | None = None) -> Release:
    directory = source or source_directory()
    version = source_version(directory)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name in (*FILES, *((".env",) if environment is not None else ())):
            if name == ".env":
                content = (environment or "").encode()
            else:
                path = directory / name
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Invalid manager distribution source")
                content = path.read_bytes()
            info = ZipInfo(f"harness_manager/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100600 if name == ".env" else 0o100644) << 16
            archive.writestr(info, content)
    content = output.getvalue()
    return Release(content, ReleaseManifest(
        version=version, sha256=sha256(content).hexdigest(), size=len(content), update_url=update_url(),
    ))
