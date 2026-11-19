"""A signed curated catalogue served from one operator-configured HTTPS origin."""

from datetime import datetime, timedelta, timezone
import fcntl
from hashlib import sha256
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from time import monotonic
from typing import Literal, Self
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import httpx
from pydantic import AwareDatetime, Field, model_validator

from core import settings

from .bundles import Bundle, MAX_UPLOAD_BYTES, read_bundle
from .contracts import Digest, Manifest, ManifestModel

MAX_INDEX_BYTES = 1024 * 1024
SIGNATURE_BYTES = 64


class CatalogueRelease(ManifestModel):
    manifest: Manifest
    digest: Digest
    signer: Digest

    def preview(self) -> Bundle:
        return Bundle(self.manifest, self.signer, self.digest, [], {})


class CatalogueIndex(ManifestModel):
    format_version: Literal[1]
    sequence: int = Field(ge=1, le=2**53 - 1)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    releases: list[CatalogueRelease] = Field(max_length=128)
    revoked: list[Digest] = Field(max_length=2048)

    @model_validator(mode="after")
    def check_series(self) -> Self:
        if not self.issued_at < self.expires_at <= self.issued_at + timedelta(days=7):
            raise ValueError("Invalid catalogue validity window")
        if len({(item.manifest.code, item.manifest.version) for item in self.releases}) != len(self.releases):
            raise ValueError("Duplicate catalogue release")
        if len({item.digest for item in self.releases}) != len(self.releases):
            raise ValueError("Duplicate catalogue digest")
        if len(set(self.revoked)) != len(self.revoked):
            raise ValueError("Duplicate catalogue revocation")
        return self

    def current(self, now: datetime) -> bool:
        return self.issued_at <= now < self.expires_at


def _origin() -> tuple[str, bytes] | None:
    base, key = settings.PLUGIN_CATALOG_REMOTE_URL, settings.PLUGIN_CATALOG_REMOTE_PUBLIC_KEY
    if not (base or key):
        return None
    url = urlsplit(base)
    if (url.scheme != "https" or not url.hostname or url.username is not None or url.query or url.fragment
            or not re.fullmatch(r"[a-fA-F0-9]{64}", key)):
        raise ValueError("The catalogue requires a configured HTTPS origin and an Ed25519 public key")
    return base.rstrip("/") + "/", bytes.fromhex(key)


def _fetch(url: str, limit: int) -> bytes:
    started = monotonic()
    with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
        with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ValueError("Compressed catalogue response is unsupported")
            data = bytearray()
            for chunk in response.iter_raw():
                if len(chunk) > limit - len(data) or monotonic() - started > 12:
                    raise ValueError("Catalogue response exceeded its bounds")
                data.extend(chunk)
            return bytes(data)


def _verify(envelope: bytes, key: bytes) -> CatalogueIndex:
    if not SIGNATURE_BYTES < len(envelope) <= SIGNATURE_BYTES + MAX_INDEX_BYTES:
        raise ValueError("Invalid signed catalogue size")
    body = envelope[SIGNATURE_BYTES:]
    Ed25519PublicKey.from_public_bytes(key).verify(envelope[:SIGNATURE_BYTES], body)
    return CatalogueIndex.model_validate_json(body)


def _load_cache(path: Path, key: bytes) -> tuple[CatalogueIndex, bytes] | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as source:
        data = source.read(SIGNATURE_BYTES + MAX_INDEX_BYTES + 1)
    return _verify(data, key), data


def _save_cache(path: Path, data: bytes) -> None:
    with NamedTemporaryFile(dir=path.parent, prefix=".index-", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def snapshot() -> tuple[str, CatalogueIndex] | None:
    location = _origin()
    if location is None:
        return None
    base, key = location
    candidate: tuple[CatalogueIndex, bytes] | None = None
    try:
        signature = _fetch(base + "index.sig", SIGNATURE_BYTES)
        if len(signature) == SIGNATURE_BYTES:
            envelope = signature + _fetch(base + "index.json", MAX_INDEX_BYTES)
            candidate = _verify(envelope, key), envelope
    except (httpx.HTTPError, InvalidSignature, ValueError):
        pass

    root = settings.PLUGIN_CATALOG_DIRECTORY / ".remote"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("Invalid catalogue cache directory")
    path = root / sha256(base.encode() + key).hexdigest()
    lock = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = _load_cache(path, key)
        now = datetime.now(timezone.utc)
        if candidate is not None and candidate[0].current(now):
            index, envelope = candidate
            if previous is None or (index.sequence > previous[0].sequence
                    and set(previous[0].revoked).issubset(index.revoked)):
                _save_cache(path, envelope)
                return base, index
        # The last accepted series stays authoritative for rollbacks and revocations.
        return (base, previous[0]) if previous is not None else None
    finally:
        os.close(lock)


def archive(base: str, entry: CatalogueRelease) -> bytes:
    content = _fetch(base + f"archives/{entry.digest}.zip", MAX_UPLOAD_BYTES)
    bundle = read_bundle(content)
    if (bundle.digest, bundle.signer, bundle.manifest) != (entry.digest, entry.signer, entry.manifest):
        raise ValueError("Archive differs from the signed catalogue declaration")
    return content
