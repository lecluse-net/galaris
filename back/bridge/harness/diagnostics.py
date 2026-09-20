"""Bounded, read-only diagnostics; never expose credentials or remote response bodies."""

from __future__ import annotations

import asyncio
import socket
import ssl
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel

from core.settings import settings
from core.params import runtime_settings
from core.util import as_list

from .manager import HarnessManager, HarnessManagerError, manager
from .distribution import source_version, version_tuple


ManagerState = Literal[
    "ok", "missing_secret", "invalid_secret", "invalid_url", "dns_error",
    "connection_error", "timeout", "tls_error", "unauthorized", "forbidden",
    "not_found", "http_error", "incompatible_manager", "invalid_response",
]


class ManagerDiagnostics(BaseModel):
    state: ManagerState
    manager_url: str
    galaris_api_url: str
    public_api_url: str
    secret_configured: bool
    api_url_source: Literal["HARNESS_MANAGER_GALARIS_API_URL", "APP_HOST"]
    mode_hint: Literal["local", "remote", "unknown"]
    api_issue: Literal["none", "missing", "invalid_url", "loopback", "docker_hostname"]
    runtime_api_check: Literal["not_checked"] = "not_checked"
    legacy_environment_detected: bool = False
    http_status: int | None = None
    manager_version: str | None = None
    expected_version: str | None = None
    version_status: Literal["not_checked", "current", "update_available", "newer", "unknown"] = "not_checked"


def _safe_url(raw: str) -> str:
    """Only expose HTTP(S) origin and path, never userinfo, query or fragments."""
    try:
        parsed = urlsplit(raw.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        netloc = f"{host}:{parsed.port}" if parsed.port else host
        return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))
    except ValueError:
        return ""


def _error_state(exc: BaseException) -> tuple[ManagerState, int | None]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and all(current is not item for item in chain):
        chain.append(current)
        current = current.__cause__ or current.__context__
    for item in chain:
        if isinstance(item, httpx.HTTPStatusError):
            status = item.response.status_code
            states: dict[int, ManagerState] = {401: "unauthorized", 403: "forbidden", 404: "not_found"}
            state = states.get(status, "http_error")
            return state, status
    if any(isinstance(item, socket.gaierror) for item in chain):
        return "dns_error", None
    if any(isinstance(item, ssl.SSLError) for item in chain):
        return "tls_error", None
    if any(isinstance(item, (TimeoutError, httpx.TimeoutException)) for item in chain):
        return "timeout", None
    if any(isinstance(item, ValueError) for item in chain):
        return "invalid_secret", None
    return "connection_error", None


async def diagnose(client: HarnessManager = manager) -> ManagerDiagnostics:
    manager_url = _safe_url(client.base_url)
    api_url = _safe_url(runtime_settings.HARNESS_API_URL)
    host = urlsplit(manager_url).hostname
    mode: Literal["local", "remote", "unknown"] = (
        "local" if host in {"host.docker.internal", "localhost", "127.0.0.1", "::1"}
        else "remote" if host else "unknown"
    )
    api_host = urlsplit(api_url).hostname
    issue: Literal["none", "missing", "invalid_url", "loopback", "docker_hostname"] = "none"
    if not runtime_settings.HARNESS_API_URL:
        issue = "missing"
    elif not api_url:
        issue = "invalid_url"
    elif api_host in {"localhost", "127.0.0.1", "::1"}:
        issue = "loopback"
    elif api_host and "." not in api_host and ":" not in api_host:
        issue = "docker_hostname"
    result = ManagerDiagnostics(
        state="missing_secret",
        manager_url=manager_url,
        galaris_api_url=api_url,
        public_api_url=_safe_url(settings.APP_API_URL),
        secret_configured=client.configured,
        api_url_source="HARNESS_MANAGER_GALARIS_API_URL" if runtime_settings.HARNESS_MANAGER_GALARIS_API_URL else "APP_HOST",
        mode_hint=mode,
        api_issue=issue,
    )
    try:
        result.expected_version = source_version()
    except (OSError, ValueError, KeyError):
        pass  # Connectivity diagnostics remain useful if the distribution is unavailable.
    if not manager_url:
        result.state = "invalid_url"
        return result
    if not client.configured:
        return result
    try:
        payload = await asyncio.wait_for(client.get_contract(), timeout=10.0)
    except (HarnessManagerError, httpx.RequestError, TimeoutError) as exc:
        result.state, result.http_status = _error_state(exc)
        return result
    except (ValueError, TypeError):
        result.state = "invalid_response"
        return result
    capabilities = {str(item) for item in as_list(payload.get("capabilities"))}
    result.state = (
        "ok" if payload.get("service") == "bridge.harness"
        and {"compose-lifecycle", "file-share"} <= capabilities
        else "incompatible_manager"
    )
    if result.state == "ok":
        installed = version_tuple(payload.get("version"))
        expected = version_tuple(result.expected_version)
        result.manager_version = str(payload["version"]) if installed else None
        result.version_status = (
            "unknown" if installed is None or expected is None
            else "current" if installed == expected
            else "update_available" if installed < expected else "newer"
        )
    return result
