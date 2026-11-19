"""Prepare an effective set of trusted executable contributors before publishing it."""

import asyncio
from base64 import b64encode
from collections.abc import Callable, Iterable
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from core import settings
from core.secrets import browser_executor_token
from core.util import post_buffered

from .bundles import Bundle
from .contracts import DocumentContribution, RuntimeRequirement

_prepare: Callable[[tuple[Bundle, ...]], Callable[[], None]] | None = None
_active: dict[str, Bundle] = {}


class _ModuleQualification(BaseModel):
    qualified: bool


def register_runtime(prepare: Callable[[tuple[Bundle, ...]], Callable[[], None]]) -> None:
    global _prepare
    _prepare = prepare


def dependencies_available(requirements: list[str]) -> bool:
    for requirement in requirements:
        name, expected = requirement.split("==", 1)
        try:
            if version(name) != expected:
                return False
        except PackageNotFoundError:
            return False
    return True


def runtime_endpoint(requirement: RuntimeRequirement) -> str | None:
    binding = settings.PLUGIN_RUNTIME_BINDINGS.get(requirement.code, {})
    endpoint = binding.get("url", "")
    try:
        url = urlsplit(endpoint)
        if (binding.get("image") == requirement.image and url.scheme in {"http", "https"} and url.hostname
                and url.username is None and url.password is None and not url.query and not url.fragment):
            return endpoint.rstrip("/")
    except ValueError:
        pass
    return None


async def verify_runtimes(requirements: list[RuntimeRequirement]) -> None:
    if not requirements:
        return
    async with httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False) as client:
        for requirement in requirements:
            endpoint = runtime_endpoint(requirement)
            if endpoint is None:
                raise ValueError(f"Runtime {requirement.code} is unconfigured")
            try:
                response = await client.get(f"{endpoint}/health")
            except httpx.RequestError as exc:
                raise ValueError(f"Runtime {requirement.code} health probe could not connect") from exc
            if response.status_code != 200:
                raise ValueError(f"Runtime {requirement.code} health probe returned HTTP {response.status_code}")


async def verify_document_modules(bundle: Bundle) -> None:
    async with asyncio.timeout(15):
        for item in bundle.manifest.contributions:
            if not isinstance(item, DocumentContribution):
                continue
            try:
                response = await post_buffered(
                    f"{settings.BROWSER_EXECUTOR_URL}/v1/qualify-plugin-module",
                    headers={"x-galaris-browser-token": browser_executor_token()},
                    json={"source_base64": b64encode(bundle.assets[item.frontend_path]).decode("ascii")},
                    max_bytes=1024,
                    timeout=10,
                )
                if not _ModuleQualification.model_validate_json(response).qualified:
                    raise ValueError("Browser module was not qualified")
            except (httpx.HTTPError, TimeoutError, ValueError, RuntimeError) as exc:
                raise ValueError(f"Browser module for {item.code} could not be qualified") from exc


def effective(digest: str) -> bool:
    return any(bundle.digest == digest for bundle in _active.values())


def active_bundles() -> tuple[Bundle, ...]:
    return tuple(_active.values())


def generation_fingerprint() -> str:
    return sha256("".join(sorted(bundle.digest for bundle in _active.values())).encode("ascii")).hexdigest()


def prepare_generation(bundles: Iterable[Bundle]) -> Callable[[], None]:
    next_active = {bundle.manifest.code: bundle for bundle in bundles}
    prepare = _prepare
    if prepare is None:
        raise RuntimeError("Executable plugin runtime is unavailable")
    promote = prepare(tuple(next_active.values()))

    def publish() -> None:
        global _active
        promote()
        _active = next_active

    return publish


def prepare_change(code: str, replacement: Bundle | None) -> Callable[[], None]:
    releases = {name: bundle for name, bundle in _active.items() if name != code}
    if replacement is not None:
        releases[code] = replacement
    return prepare_generation(releases.values())


def frontend_asset(digest: str, code: str) -> bytes | None:
    for bundle in _active.values():
        if bundle.digest == digest:
            for item in bundle.manifest.contributions:
                if isinstance(item, DocumentContribution) and item.code == code:
                    return bundle.assets[item.frontend_path]
    return None
