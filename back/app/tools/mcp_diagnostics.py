"""Sanitized network diagnostics for MCP Tool connection previews."""

from __future__ import annotations

import asyncio
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping
from urllib.parse import urlparse

import httpx
from loguru import logger

from app.tools.mcp import build_mcp_server
from app.tools.schemas import (
    McpConfig,
    Tool,
    ToolMcpTestDiagnostic,
    ToolMcpTestFunction,
    ToolMcpTestRequest,
    ToolMcpTestResponse,
)
from app.tools.secrets import (
    protect_mcp_config,
    resolve_connection_references,
    runtime_mcp_config,
)
from core.i18n import render_prompt, tr


DiagnosticStage = Literal[
    "configuration",
    "dns",
    "tcp",
    "tls",
    "process",
    "authentication",
    "protocol",
    "discovery",
]
DiagnosticStatus = Literal["success", "error", "warning", "skipped", "info"]
FailureKind = Literal[
    "configuration",
    "dns",
    "tcp",
    "tls",
    "process",
    "authentication",
    "authorization",
    "endpoint",
    "protocol",
    "timeout",
    "server",
    "unknown",
]

_PROBE_TIMEOUT_SECONDS = 5.0
_MAX_RESOLVED_ADDRESSES = 8
_HTTP_STATUS_RE = re.compile(r"(?<!\d)(401|403|404|405|406|415|429|5\d\d)(?!\d)")


@dataclass(frozen=True)
class DiagnosticFact:
    """Internal diagnostic fact rendered through backend i18n by the router."""

    stage: DiagnosticStage
    status: DiagnosticStatus
    message_key: str
    values: dict[str, object] = field(default_factory=dict[str, object])
    duration_ms: int | None = None


@dataclass(frozen=True)
class EndpointProbe:
    """Result of the bounded DNS, TCP, and TLS preflight."""

    diagnostics: tuple[DiagnosticFact, ...]
    failure_kind: FailureKind | None = None


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.monotonic() - started_at) * 1000))


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except Exception as exc:
        logger.debug("MCP diagnostic stream close failed: {}", type(exc).__name__)


async def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(
        loop.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        ),
        timeout=_PROBE_TIMEOUT_SECONDS,
    )
    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address not in addresses:
            addresses.append(address)
        if len(addresses) >= _MAX_RESOLVED_ADDRESSES:
            break
    return tuple(addresses)


async def _probe_tcp(address: str, port: int) -> None:
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(address, port),
        timeout=_PROBE_TIMEOUT_SECONDS,
    )
    await _close_writer(writer)


async def _probe_tls(host: str, port: int) -> None:
    context = ssl.create_default_context()
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            host,
            port,
            ssl=context,
            server_hostname=host,
        ),
        timeout=_PROBE_TIMEOUT_SECONDS,
    )
    await _close_writer(writer)


async def probe_mcp_endpoint(
    config: McpConfig,
    connection_params: Mapping[str, Any],
) -> EndpointProbe:
    """Probe an MCP endpoint without sending credentials or MCP payloads."""

    if config.type == "stdio":
        return EndpointProbe(
            diagnostics=(
                DiagnosticFact(
                    stage="dns",
                    status="skipped",
                    message_key="mcp_test_network_not_applicable_stdio",
                ),
                DiagnosticFact(
                    stage="process",
                    status="info",
                    message_key="mcp_test_process_pending",
                ),
            )
        )

    resolved_url = resolve_connection_references(
        config.url or "",
        connection_params,
    )
    parsed = urlparse(resolved_url)
    host = parsed.hostname
    if not host or parsed.scheme not in {"http", "https"}:
        return EndpointProbe(
            diagnostics=(
                DiagnosticFact(
                    stage="configuration",
                    status="error",
                    message_key="mcp_test_url_invalid",
                ),
            ),
            failure_kind="configuration",
        )
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return EndpointProbe(
            diagnostics=(
                DiagnosticFact(
                    stage="configuration",
                    status="error",
                    message_key="mcp_test_url_invalid",
                ),
            ),
            failure_kind="configuration",
        )

    diagnostics: list[DiagnosticFact] = []
    dns_started = time.monotonic()
    try:
        addresses = await _resolve_addresses(host, port)
    except Exception as exc:
        kind = classify_mcp_exception(exc)
        diagnostics.append(
            DiagnosticFact(
                stage="dns",
                status="error",
                message_key=(
                    "mcp_test_dns_timeout"
                    if kind == "timeout"
                    else "mcp_test_dns_failed"
                ),
                values={"host": host},
                duration_ms=_elapsed_ms(dns_started),
            )
        )
        return EndpointProbe(
            diagnostics=tuple(diagnostics),
            failure_kind="timeout" if kind == "timeout" else "dns",
        )

    if not addresses:
        diagnostics.append(
            DiagnosticFact(
                stage="dns",
                status="error",
                message_key="mcp_test_dns_no_address",
                values={"host": host},
                duration_ms=_elapsed_ms(dns_started),
            )
        )
        return EndpointProbe(
            diagnostics=tuple(diagnostics),
            failure_kind="dns",
        )

    diagnostics.append(
        DiagnosticFact(
            stage="dns",
            status="success",
            message_key="mcp_test_dns_success",
            values={
                "host": host,
                "addresses": ", ".join(addresses),
            },
            duration_ms=_elapsed_ms(dns_started),
        )
    )

    tcp_started = time.monotonic()
    reachable_address: str | None = None
    last_tcp_error: Exception | None = None
    for address in addresses:
        try:
            await _probe_tcp(address, port)
            reachable_address = address
            break
        except Exception as exc:
            last_tcp_error = exc

    if reachable_address is None:
        kind = classify_mcp_exception(last_tcp_error or ConnectionError())
        diagnostics.append(
            DiagnosticFact(
                stage="tcp",
                status="error",
                message_key=(
                    "mcp_test_tcp_timeout"
                    if kind == "timeout"
                    else "mcp_test_tcp_failed"
                ),
                values={"port": port},
                duration_ms=_elapsed_ms(tcp_started),
            )
        )
        return EndpointProbe(
            diagnostics=tuple(diagnostics),
            failure_kind="timeout" if kind == "timeout" else "tcp",
        )

    diagnostics.append(
        DiagnosticFact(
            stage="tcp",
            status="success",
            message_key="mcp_test_tcp_success",
            values={"address": reachable_address, "port": port},
            duration_ms=_elapsed_ms(tcp_started),
        )
    )

    if parsed.scheme != "https":
        diagnostics.append(
            DiagnosticFact(
                stage="tls",
                status="skipped",
                message_key="mcp_test_tls_not_used",
            )
        )
        return EndpointProbe(diagnostics=tuple(diagnostics))

    tls_started = time.monotonic()
    try:
        await _probe_tls(host, port)
    except Exception as exc:
        kind = classify_mcp_exception(exc)
        diagnostics.append(
            DiagnosticFact(
                stage="tls",
                status="error",
                message_key=(
                    "mcp_test_tls_timeout"
                    if kind == "timeout"
                    else "mcp_test_tls_failed"
                ),
                values={"host": host},
                duration_ms=_elapsed_ms(tls_started),
            )
        )
        return EndpointProbe(
            diagnostics=tuple(diagnostics),
            failure_kind="timeout" if kind == "timeout" else "tls",
        )

    diagnostics.append(
        DiagnosticFact(
            stage="tls",
            status="success",
            message_key="mcp_test_tls_success",
            values={"host": host},
            duration_ms=_elapsed_ms(tls_started),
        )
    )
    return EndpointProbe(diagnostics=tuple(diagnostics))


def _exception_chain(exc: BaseException) -> tuple[BaseException, ...]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return tuple(chain)


def _http_status(chain: tuple[BaseException, ...]) -> int | None:
    for item in chain:
        response = getattr(item, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        match = _HTTP_STATUS_RE.search(str(item))
        if match:
            return int(match.group(1))
    return None


def classify_mcp_exception(exc: BaseException) -> FailureKind:
    """Classify an exception without returning its potentially sensitive text."""

    chain = _exception_chain(exc)
    status_code = _http_status(chain)
    if status_code == 401:
        return "authentication"
    if status_code == 403:
        return "authorization"
    if status_code == 404:
        return "endpoint"
    if status_code is not None and status_code >= 500:
        return "server"
    if status_code is not None:
        return "protocol"

    if any(isinstance(item, (ssl.SSLError, ssl.CertificateError)) for item in chain):
        return "tls"
    if any(isinstance(item, socket.gaierror) for item in chain):
        return "dns"
    if any(
        isinstance(item, (TimeoutError, httpx.TimeoutException))
        for item in chain
    ):
        return "timeout"
    if any(isinstance(item, FileNotFoundError) for item in chain):
        return "process"
    if any(
        isinstance(
            item,
            (
                ConnectionError,
                httpx.ConnectError,
                httpx.NetworkError,
            ),
        )
        for item in chain
    ):
        return "tcp"
    return "unknown"


_FAILURE_MESSAGE_KEYS: dict[FailureKind, str] = {
    "configuration": "mcp_test_configuration_failed",
    "dns": "mcp_test_dns_summary",
    "tcp": "mcp_test_tcp_summary",
    "tls": "mcp_test_tls_summary",
    "process": "mcp_test_process_failed",
    "authentication": "mcp_test_authentication_failed",
    "authorization": "mcp_test_authorization_failed",
    "endpoint": "mcp_test_endpoint_failed",
    "protocol": "mcp_test_protocol_failed",
    "timeout": "mcp_test_timeout",
    "server": "mcp_test_server_failed",
    "unknown": "mcp_test_connection_error",
}


async def _message(key: str, **values: Any) -> str:
    return render_prompt(await tr(f"tools.{key}"), **values)


async def _error(key: str, **values: Any) -> str:
    return render_prompt(await tr(f"tools.errors.{key}"), **values)


async def _render_diagnostics(
    facts: list[DiagnosticFact],
) -> list[ToolMcpTestDiagnostic]:
    diagnostics: list[ToolMcpTestDiagnostic] = []
    for fact in facts:
        diagnostics.append(
            ToolMcpTestDiagnostic(
                stage=fact.stage,
                status=fact.status,
                message=await _message(fact.message_key, **fact.values),
                duration_ms=fact.duration_ms,
            )
        )
    return diagnostics


async def _failure_message(kind: FailureKind) -> str:
    return await _message(_FAILURE_MESSAGE_KEYS[kind])


async def diagnose_mcp_connection(
    data: ToolMcpTestRequest,
    *,
    existing_config: Mapping[str, Any] | None = None,
) -> ToolMcpTestResponse:
    """Run a bounded, non-persistent MCP connection diagnostic."""

    diagnostic_facts: list[DiagnosticFact] = []
    try:
        protected_config = protect_mcp_config(
            data.mcp_config.model_dump(),
            existing=existing_config,
        )
        preview_tool = Tool(
            code=data.code,
            label=data.code,
            mcp_config=McpConfig(**runtime_mcp_config(protected_config)),
        )
        connection_params = {
            name: value
            for name, value in data.params.items()
            if value is not None
        }
        server = build_mcp_server(
            preview_tool,
            connection_params,
            prefix_tools=False,
        )
        if server is None:
            diagnostic_facts.append(
                DiagnosticFact(
                    stage="configuration",
                    status="error",
                    message_key="mcp_test_server_creation_failed",
                )
            )
            return ToolMcpTestResponse(
                success=False,
                message=await _error("server_creation_failed"),
                failure_kind="configuration",
                diagnostics=await _render_diagnostics(diagnostic_facts),
            )
    except ValueError as exc:
        diagnostic_facts.append(
            DiagnosticFact(
                stage="configuration",
                status="error",
                message_key="mcp_test_configuration_detail",
                values={"detail": str(exc)},
            )
        )
        return ToolMcpTestResponse(
            success=False,
            message=str(exc),
            failure_kind="configuration",
            diagnostics=await _render_diagnostics(diagnostic_facts),
        )

    assert preview_tool.mcp is not None
    diagnostic_facts.append(
        DiagnosticFact(
            stage="configuration",
            status="success",
            message_key="mcp_test_configuration_valid",
            values={
                "transport": preview_tool.mcp.type,
                "auth_type": preview_tool.mcp.auth.type,
            },
        )
    )
    probe = await probe_mcp_endpoint(preview_tool.mcp, connection_params)
    diagnostic_facts.extend(probe.diagnostics)
    auth_configured = preview_tool.mcp.auth.type != "none"
    if probe.failure_kind is not None:
        diagnostic_facts.append(
            DiagnosticFact(
                stage="authentication",
                status="warning" if auth_configured else "skipped",
                message_key=(
                    "mcp_test_auth_not_verified"
                    if auth_configured
                    else "mcp_test_auth_not_configured"
                ),
            )
        )
        diagnostic_facts.append(
            DiagnosticFact(
                stage="protocol",
                status="skipped",
                message_key="mcp_test_protocol_not_attempted",
            )
        )
        return ToolMcpTestResponse(
            success=False,
            message=await _failure_message(probe.failure_kind),
            failure_kind=probe.failure_kind,
            diagnostics=await _render_diagnostics(diagnostic_facts),
        )

    mcp_started = time.monotonic()
    try:
        async with server:
            tools = await server.list_tools()
    except Exception as exc:
        failure_kind = classify_mcp_exception(exc)
        logger.error(
            "MCP Tool preview failed for code={} (failure_kind={}, error_type={})",
            data.code,
            failure_kind,
            type(exc).__name__,
        )
        if failure_kind == "authentication":
            diagnostic_facts.append(
                DiagnosticFact(
                    stage="authentication",
                    status="error",
                    message_key="mcp_test_auth_rejected",
                )
            )
        elif failure_kind == "authorization":
            diagnostic_facts.append(
                DiagnosticFact(
                    stage="authentication",
                    status="error",
                    message_key="mcp_test_authorization_rejected",
                )
            )
        else:
            diagnostic_facts.append(
                DiagnosticFact(
                    stage="authentication",
                    status="warning" if auth_configured else "skipped",
                    message_key=(
                        "mcp_test_auth_not_verified"
                        if auth_configured
                        else "mcp_test_auth_not_configured"
                    ),
                )
            )
        diagnostic_facts.append(
            DiagnosticFact(
                stage="process" if failure_kind == "process" else "protocol",
                status="error",
                message_key=_FAILURE_MESSAGE_KEYS[failure_kind],
                duration_ms=_elapsed_ms(mcp_started),
            )
        )
        return ToolMcpTestResponse(
            success=False,
            message=await _failure_message(failure_kind),
            failure_kind=failure_kind,
            diagnostics=await _render_diagnostics(diagnostic_facts),
        )

    mcp_duration_ms = _elapsed_ms(mcp_started)
    if preview_tool.mcp.type == "stdio":
        diagnostic_facts.append(
            DiagnosticFact(
                stage="process",
                status="success",
                message_key="mcp_test_process_started",
            )
        )
    diagnostic_facts.append(
        DiagnosticFact(
            stage="authentication",
            status="success" if auth_configured else "skipped",
            message_key=(
                "mcp_test_auth_accepted"
                if auth_configured
                else "mcp_test_auth_not_configured"
            ),
        )
    )
    diagnostic_facts.extend(
        [
            DiagnosticFact(
                stage="protocol",
                status="success",
                message_key="mcp_test_protocol_success",
                duration_ms=mcp_duration_ms,
            ),
            DiagnosticFact(
                stage="discovery",
                status="success",
                message_key="mcp_test_discovery_success",
                values={"count": len(tools)},
            ),
        ]
    )
    return ToolMcpTestResponse(
        success=True,
        message=await _message("mcp_test_tools_available", count=len(tools)),
        diagnostics=await _render_diagnostics(diagnostic_facts),
        tools=[
            ToolMcpTestFunction(
                name=tool.name,
                description=tool.description or "",
            )
            for tool in tools
        ],
    )
