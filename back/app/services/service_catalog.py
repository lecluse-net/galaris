"""Bundled service presets and an atomic, opt-in GitHub catalogue snapshot."""

import asyncio
import json
from importlib.metadata import version
from pathlib import Path
import re
from typing import Any, Literal, cast

import httpx
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
import yaml
from core import settings

from .capabilities import supported_capabilities
from .schemas import ServiceCreate

REPOSITORY = "lecluse-net/galaris"
CATALOG_PATH = "back/app/services/service_catalog"
BUNDLED = Path(__file__).with_suffix("")
CACHE = Path("/data/service-catalog/snapshot.json")
MAX_FILE_BYTES = 524_288
MAX_ENTRIES = 100
_refresh_lock = asyncio.Lock()


class ServicePreset(BaseModel):
    definition: ServiceCreate
    compatible: bool
    compatibility: Literal["supported", "format", "version", "protocol"]


class ServiceCatalog(BaseModel):
    source: Literal["bundled", "github"] = "bundled"
    revision: str = "bundled"
    entries: list[ServicePreset] = Field(default_factory=lambda: list[ServicePreset]())
    refresh_failed: bool = False


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def preset(definition: ServiceCreate) -> ServicePreset:
    metadata = definition.catalog
    reason: Literal["supported", "format", "version", "protocol"] = "supported"
    available = {item.value for capability in supported_capabilities() for item in capability.protocols}
    if metadata is None or metadata.format_version != 1:
        reason = "format"
    elif _version_tuple(metadata.minimum_galaris_version) > _version_tuple(
            settings.APP_VERSION if re.fullmatch(r"\d+\.\d+\.\d+", settings.APP_VERSION) else version("app")):
        reason = "version"
    elif not definition.capabilities or not set(definition.capabilities) <= available:
        reason = "protocol"
    return ServicePreset(definition=definition, compatible=reason == "supported", compatibility=reason)


def _parse_definition(content: str) -> ServiceCreate:
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("Service preset is too large")
    raw: Any = yaml.safe_load(content)  # type: ignore[call-overload]
    definition = ServiceCreate.model_validate(raw)
    # The catalogue distributes configuration, not literal secrets or executables.
    if definition.mcp_config and (definition.mcp_config.type == "stdio"
            or definition.mcp_config.auth.token_static or definition.mcp_config.headers or definition.mcp_config.env):
        raise ValueError("Catalogue presets cannot distribute commands or literal credentials")
    if definition.listener_config and definition.listener_config.token:
        raise ValueError("Catalogue presets cannot distribute credentials")
    if any(item.type == "password" and item.default for item in definition.connection_schema.params.values()):
        raise ValueError("Catalogue presets cannot contain secret defaults")
    if definition.catalog is None:
        raise ValueError("Missing catalogue metadata")
    return definition


def _filenames(content: str) -> list[str]:
    raw: Any = yaml.safe_load(content)  # type: ignore[call-overload]
    if not isinstance(raw, dict):
        raise ValueError("Unsupported catalogue index")
    mapping = cast(dict[str, Any], raw)
    if mapping.get("format_version") != 1:
        raise ValueError("Unsupported catalogue index")
    entries: object = mapping.get("services")
    if not isinstance(entries, list) or not 0 < len(cast(list[object], entries)) <= MAX_ENTRIES:
        raise ValueError("Invalid catalogue index")
    names: list[str] = []
    for entry in cast(list[object], entries):
        if not isinstance(entry, str) or not re.fullmatch(r"[a-z][a-z0-9-]*\.yaml", entry):
            raise ValueError("Invalid service filename")
        names.append(entry)
    if len(names) != len(set(names)):
        raise ValueError("Duplicate service filename")
    return names


def _catalog(contents: list[str], *, source: Literal["bundled", "github"], revision: str) -> ServiceCatalog:
    entries = [preset(_parse_definition(content)) for content in contents]
    codes = [entry.definition.code for entry in entries]
    if len(set(codes)) != len(codes):
        raise ValueError("Duplicate service code")
    return ServiceCatalog(source=source, revision=revision,
        entries=sorted(entries, key=lambda entry: entry.definition.label.casefold()))


def bundled_catalog() -> ServiceCatalog:
    names = _filenames((BUNDLED / "index.yaml").read_text(encoding="utf-8"))
    return _catalog([(BUNDLED / name).read_text(encoding="utf-8") for name in names],
        source="bundled", revision="bundled")


def read_catalog() -> ServiceCatalog:
    bundled = bundled_catalog()
    try:
        if CACHE.stat().st_size > MAX_FILE_BYTES * MAX_ENTRIES:
            raise ValueError("Catalogue cache is too large")
        cached = ServiceCatalog.model_validate_json(CACHE.read_text(encoding="utf-8"))
        if cached.source != "github" or not re.fullmatch(r"[0-9a-f]{40}", cached.revision):
            raise ValueError("Invalid catalogue cache")
        # Recheck compatibility after every application upgrade; keep bundled entries
        # when main removed an entry or now requires a newer application version.
        merged = {entry.definition.code: entry for entry in bundled.entries}
        for entry in cached.entries:
            checked = preset(entry.definition)
            if checked.compatible or checked.definition.code not in merged:
                merged[checked.definition.code] = checked
        return ServiceCatalog(source="github", revision=cached.revision,
            entries=sorted(merged.values(), key=lambda entry: entry.definition.label.casefold()))
    except FileNotFoundError:
        return bundled
    except (OSError, ValueError, ValidationError):
        logger.warning("Service catalogue cache unavailable; using bundled presets")
        return bundled


async def _download(client: httpx.AsyncClient, url: str) -> str:
    chunks = bytearray()
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            chunks.extend(chunk)
            if len(chunks) > MAX_FILE_BYTES:
                raise ValueError("Catalogue response is too large")
    return chunks.decode("utf-8")


async def refresh_catalog() -> ServiceCatalog:
    async with _refresh_lock:
        try:
            async with asyncio.timeout(60), httpx.AsyncClient(timeout=15, follow_redirects=False,
                    headers={"User-Agent": "Galaris-service-catalog", "Accept": "application/vnd.github+json"}) as client:
                commit = json.loads(await _download(client,
                    f"https://api.github.com/repos/{REPOSITORY}/commits/main"))
                revision = str(commit.get("sha", ""))
                if not re.fullmatch(r"[0-9a-f]{40}", revision):
                    raise ValueError("Invalid GitHub revision")
                base = f"https://raw.githubusercontent.com/{REPOSITORY}/{revision}/{CATALOG_PATH}"
                names = _filenames(await _download(client, f"{base}/index.yaml"))
                semaphore = asyncio.Semaphore(5)

                async def download(name: str) -> str:
                    async with semaphore:
                        return await _download(client, f"{base}/{name}")

                results = await asyncio.gather(*(download(name) for name in names), return_exceptions=True)
                contents: list[str] = []
                for result in results:
                    if isinstance(result, BaseException):
                        raise ValueError("Service preset download failed") from result
                    contents.append(result)
                snapshot = await asyncio.to_thread(_catalog, contents, source="github", revision=revision)
            await asyncio.to_thread(_save_snapshot, snapshot)
            return await asyncio.to_thread(read_catalog)
        except (httpx.HTTPError, OSError, ValueError, TimeoutError, yaml.YAMLError):
            logger.warning("Service catalogue refresh failed; retaining the last usable catalogue")
            previous = await asyncio.to_thread(read_catalog)
            previous.refresh_failed = True
            return previous


def _save_snapshot(snapshot: ServiceCatalog) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    temporary = CACHE.with_suffix(".tmp")
    try:
        temporary.write_text(snapshot.model_dump_json(), encoding="utf-8")
        temporary.replace(CACHE)
    finally:
        temporary.unlink(missing_ok=True)
