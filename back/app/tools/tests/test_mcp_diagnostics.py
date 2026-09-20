"""Tests for sanitized MCP endpoint diagnostics."""

import socket
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools import mcp_diagnostics
from app.tools.schemas import McpConfig, ToolMcpTestRequest


class _PreviewServer:
    async def __aenter__(self) -> "_PreviewServer":
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback

    async def list_tools(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(name="issues_list", description="List issues"),
            SimpleNamespace(name="issues_get", description=None),
        ]


class _AuthenticationFailureServer(_PreviewServer):
    async def list_tools(self) -> list[SimpleNamespace]:
        raise RuntimeError("HTTP 401 Unauthorized")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("request failed with 401 Unauthorized"), "authentication"),
        (RuntimeError("request failed with 403 Forbidden"), "authorization"),
        (RuntimeError("request failed with 404 Not Found"), "endpoint"),
        (ssl.SSLCertVerificationError("certificate verify failed"), "tls"),
        (socket.gaierror("name resolution failed"), "dns"),
        (TimeoutError(), "timeout"),
        (FileNotFoundError(), "process"),
        (ConnectionRefusedError(), "tcp"),
    ],
)
def test_classify_mcp_exception(error: BaseException, expected: str) -> None:
    assert mcp_diagnostics.classify_mcp_exception(error) == expected


@pytest.mark.asyncio
async def test_probe_reports_dns_tcp_and_tls_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve = AsyncMock(return_value=("192.0.2.10", "2001:db8::10"))
    tcp = AsyncMock(return_value=None)
    tls = AsyncMock(return_value=None)
    monkeypatch.setattr(mcp_diagnostics, "_resolve_addresses", resolve)
    monkeypatch.setattr(mcp_diagnostics, "_probe_tcp", tcp)
    monkeypatch.setattr(mcp_diagnostics, "_probe_tls", tls)

    result = await mcp_diagnostics.probe_mcp_endpoint(
        McpConfig(
            type="http",
            url="https://mcp.example.test/service",
        ),
        {},
    )

    assert result.failure_kind is None
    assert [diagnostic.stage for diagnostic in result.diagnostics] == [
        "dns",
        "tcp",
        "tls",
    ]
    assert result.diagnostics[0].values["addresses"] == (
        "192.0.2.10, 2001:db8::10"
    )
    assert result.diagnostics[1].values == {
        "address": "192.0.2.10",
        "port": 443,
    }
    resolve.assert_awaited_once_with("mcp.example.test", 443)
    tcp.assert_awaited_once_with("192.0.2.10", 443)
    tls.assert_awaited_once_with("mcp.example.test", 443)


@pytest.mark.asyncio
async def test_diagnostic_uses_preview_config_and_ephemeral_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_config = {"type": "http", "headers": {"X-Secret": "encrypted"}}
    protect = MagicMock(side_effect=lambda config, *, existing: config)
    build_server = MagicMock(return_value=_PreviewServer())
    monkeypatch.setattr(mcp_diagnostics, "protect_mcp_config", protect)
    monkeypatch.setattr(
        mcp_diagnostics,
        "runtime_mcp_config",
        lambda config: config,
    )
    monkeypatch.setattr(mcp_diagnostics, "build_mcp_server", build_server)
    monkeypatch.setattr(
        mcp_diagnostics,
        "probe_mcp_endpoint",
        AsyncMock(
            return_value=mcp_diagnostics.EndpointProbe(
                diagnostics=(
                    mcp_diagnostics.DiagnosticFact(
                        stage="dns",
                        status="success",
                        message_key="mcp_test_dns_success",
                        values={
                            "host": "preview.example.test",
                            "addresses": "192.0.2.10",
                        },
                        duration_ms=3,
                    ),
                )
            )
        ),
    )
    monkeypatch.setattr(
        mcp_diagnostics,
        "_message",
        AsyncMock(return_value="translated diagnostic"),
    )

    result = await mcp_diagnostics.diagnose_mcp_connection(
        ToolMcpTestRequest(
            tool_id=7,
            code="issue_tracker",
            mcp_config={
                "type": "http",
                "url": "https://preview.example.test/mcp",
                "headers": {"X-Secret": "••••••••"},
            },
            params={"token": "temporary", "unused": None},
        ),
        existing_config=existing_config,
    )

    assert result.success is True
    assert result.failure_kind is None
    assert [diagnostic.stage for diagnostic in result.diagnostics] == [
        "configuration",
        "dns",
        "authentication",
        "protocol",
        "discovery",
    ]
    assert result.diagnostics[1].duration_ms == 3
    assert [tool.name for tool in result.tools] == ["issues_list", "issues_get"]
    protect.assert_called_once()
    assert protect.call_args.kwargs["existing"] is existing_config
    preview_tool, params = build_server.call_args.args
    assert preview_tool.code == "issue_tracker"
    assert preview_tool.mcp is not None
    assert preview_tool.mcp.url == "https://preview.example.test/mcp"
    assert params == {"token": "temporary"}
    assert build_server.call_args.kwargs["prefix_tools"] is False


@pytest.mark.asyncio
async def test_diagnostic_reports_authentication_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_diagnostics,
        "protect_mcp_config",
        lambda config, **_kwargs: config,
    )
    monkeypatch.setattr(
        mcp_diagnostics,
        "runtime_mcp_config",
        lambda config: config,
    )
    monkeypatch.setattr(
        mcp_diagnostics,
        "build_mcp_server",
        MagicMock(return_value=_AuthenticationFailureServer()),
    )
    monkeypatch.setattr(
        mcp_diagnostics,
        "probe_mcp_endpoint",
        AsyncMock(
            return_value=mcp_diagnostics.EndpointProbe(diagnostics=())
        ),
    )
    monkeypatch.setattr(
        mcp_diagnostics,
        "_message",
        AsyncMock(side_effect=lambda key, **_values: key),
    )

    result = await mcp_diagnostics.diagnose_mcp_connection(
        ToolMcpTestRequest(
            code="protected_server",
            mcp_config={
                "type": "http",
                "url": "https://mcp.example.test",
                "auth": {"type": "bearer", "param": "token"},
            },
            params={"token": "temporary"},
        )
    )

    assert result.success is False
    assert result.failure_kind == "authentication"
    auth_diagnostic = next(
        diagnostic
        for diagnostic in result.diagnostics
        if diagnostic.stage == "authentication"
    )
    assert auth_diagnostic.status == "error"
    assert auth_diagnostic.message == "mcp_test_auth_rejected"
