"""Read signed declarative bundles without extracting or running their contents."""

from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import re
from stat import S_IFREG, S_IFMT
from typing import Literal, cast
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo
from zlib import error as ZlibError

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import JsonValue, TypeAdapter, ValidationError
import yaml

from app.services.facade import parse_catalog_definition
from app.services import ServiceCreate
from core import settings

from .contracts import DocumentContribution, Manifest, PresetContribution, TemplateContribution


MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_EXPANDED_BYTES = 4 * 1024 * 1024
MAX_ENTRY_BYTES = 512 * 1024
_TEMPLATE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
BundleErrorCode = Literal["invalid_bundle", "archive_too_large", "untrusted_publisher", "invalid_signature"]


class BundleError(ValueError):
    def __init__(self, code: BundleErrorCode) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Bundle:
    manifest: Manifest
    signer: str
    digest: str
    presets: list[ServiceCreate]
    assets: dict[str, bytes]


def publisher_key(publisher: str) -> bytes | None:
    configured = settings.PLUGIN_TRUSTED_PUBLISHERS.get(publisher, "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", configured):
        return None
    return bytes.fromhex(configured)


def _verify_signature(manifest: Manifest, content: bytes, signature: bytes) -> str:
    key = publisher_key(manifest.publisher)
    if key is None:
        raise BundleError("untrusted_publisher")
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, content)
    except InvalidSignature as exc:
        raise BundleError("invalid_signature") from exc
    return sha256(key).hexdigest()


def _inventory(archive: ZipFile) -> dict[str, ZipInfo]:
    members = archive.infolist()
    if len(members) > 34 or sum(item.file_size for item in members) > MAX_EXPANDED_BYTES:
        raise BundleError("archive_too_large")
    files: dict[str, ZipInfo] = {}
    for item in members:
        name = item.orig_filename
        if (
            name in files
            or not re.fullmatch(
                r"manifest\.(?:json|sig)|services/[a-z][a-z0-9-]{0,99}\.yaml|"
                r"(?:backend/[a-z][a-z0-9.-]{0,99}\.py|frontend/[a-z][a-z0-9.-]{0,99}\.mjs|data/[a-z][a-z0-9.-]{0,99}\.json)", name,
            )
            or S_IFMT(item.external_attr >> 16) not in (0, S_IFREG)
            or item.flag_bits & 1
            or item.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
        ):
            raise BundleError("invalid_bundle")
        if item.file_size > MAX_ENTRY_BYTES:
            raise BundleError("archive_too_large")
        files[name] = item
    return files


def _read(archive: ZipFile, member: ZipInfo) -> bytes:
    with archive.open(member) as stream:
        content = stream.read(MAX_ENTRY_BYTES + 1)
    if len(content) != member.file_size:
        raise BundleError("invalid_bundle")
    return content


def _verify_yaml(content: str) -> None:
    """Bound nested work before handing YAML to the shared Service validator."""
    depth = 0
    events = cast(Iterator[object], yaml.parse(content))  # pyright: ignore[reportUnknownMemberType]
    for count, event in enumerate(events):
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
        elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
        if count > 4096 or depth > 16 or isinstance(event, yaml.AliasEvent):
            raise BundleError("invalid_bundle")


def _preset(archive: ZipFile, member: ZipInfo, digest: str, code: str, manifest: Manifest) -> ServiceCreate:
    content = _read(archive, member)
    if sha256(content).hexdigest() != digest:
        raise BundleError("invalid_signature")
    decoded = content.decode("utf-8")
    _verify_yaml(decoded)
    definition = parse_catalog_definition(decoded)
    metadata = definition.catalog
    if definition.code != code or metadata is None or metadata.plugin_code or metadata.plugin_version:
        raise BundleError("invalid_bundle")
    return definition.model_copy(update={
        "catalog": metadata.model_copy(update={"plugin_code": manifest.code, "plugin_version": manifest.version}),
    })


def _read_asset(archive: ZipFile, member: ZipInfo, digest: str) -> bytes:
    content = _read(archive, member)
    if not content or sha256(content).hexdigest() != digest:
        raise BundleError("invalid_signature")
    content.decode("utf-8")
    return content


def read_bundle(content: bytes) -> Bundle:
    if len(content) > MAX_UPLOAD_BYTES:
        raise BundleError("archive_too_large")
    try:
        with ZipFile(BytesIO(content)) as archive:
            files = _inventory(archive)
            manifest_bytes = _read(archive, files["manifest.json"])
            manifest = Manifest.model_validate_json(manifest_bytes)
            signature = _read(archive, files["manifest.sig"])
            signer = _verify_signature(manifest, manifest_bytes, signature)
            paths = {"manifest.json", "manifest.sig", *(item.path for item in manifest.contributions)}
            paths.update(item.frontend_path for item in manifest.contributions if isinstance(item, DocumentContribution))
            if set(files) != paths:
                raise BundleError("invalid_bundle")
            presets = [_preset(archive, files[item.path], item.sha256, item.code, manifest)
                       for item in manifest.contributions if isinstance(item, PresetContribution)]
            assets: dict[str, bytes] = {}
            for item in manifest.contributions:
                if not isinstance(item, PresetContribution):
                    assets[item.path] = _read_asset(archive, files[item.path], item.sha256)
                if isinstance(item, TemplateContribution):
                    _TEMPLATE.validate_json(assets[item.path])
                if isinstance(item, DocumentContribution):
                    assets[item.frontend_path] = _read_asset(archive, files[item.frontend_path], item.frontend_sha256)
    except BundleError:
        raise
    except (BadZipFile, EOFError, KeyError, OSError, RuntimeError, ValueError, ValidationError, yaml.YAMLError, ZlibError) as exc:
        raise BundleError("invalid_bundle") from exc
    return Bundle(manifest, signer, sha256(content).hexdigest(), presets, assets)
