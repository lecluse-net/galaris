"""Read-only checks of saved connection credentials, independent of activation/policy."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from loguru import logger
from pydantic import BaseModel

from app.connection.facade import get_connection, get_params_as_dict
from core.i18n import tr

from . import tool_service
from .mcp_loader import list_external_mcp_capabilities, mcp_tools_by_tool_code, native_tool_codes_for_tool


class ConnectionCheck(BaseModel):
    protocol: str
    status: Literal["success", "error", "unsupported"]
    message: str


class ConnectionTestResult(BaseModel):
    status: Literal["success", "error", "unsupported"]
    checks: list[ConnectionCheck]


ConnectionProbe = Callable[[int], Awaitable[bool | None]]
_probes: dict[str, ConnectionProbe] = {}


def register_connection_probe(protocol: str, probe: ConnectionProbe) -> None:
    """A protocol owner supplies a bounded, non-mutating credential check."""
    _probes[protocol] = probe


async def test_saved_connection(connection_id: int) -> ConnectionTestResult:
    connection = await get_connection(connection_id)
    if connection is None:
        raise LookupError("Connection not found")
    tool = await tool_service.get_tool_by_id(connection.tool_id)
    if tool is None:
        raise LookupError("Tool not found")
    checks: list[ConnectionCheck] = []

    async def check(protocol: str, probe: ConnectionProbe | None) -> None:
        state: Literal["success", "error", "unsupported"] = "unsupported"
        if protocol == "messenger" and not connection.active:
            checks.append(ConnectionCheck(protocol=protocol, status="unsupported",
                message=await tr("connection_api.test.inactive")))
            return
        if probe is not None:
            try:
                async with asyncio.timeout(30):
                    result = await probe(connection_id)
                    state = "unsupported" if result is None else "success" if result else "error"
            except Exception as exc:
                # External errors can contain credentials, URLs or account data.
                logger.warning("Connection test failed connection={} protocol={} type={}", connection_id, protocol, type(exc).__name__)
                state = "error"
        checks.append(ConnectionCheck(protocol=protocol, status=state,
            message=await tr(f"connection_api.test.{state}")))

    async def mcp_probe(connection_id: int) -> bool:
        _, params = await get_params_as_dict(connection_id, decrypt_passwords=True)
        await list_external_mcp_capabilities(tool, params, include_resources=False)
        return True

    if tool.mcp:
        await check("mcp", mcp_probe)
    protocols = [name for name, config in (("mail", tool.mail), ("calendar", tool.calendar),
        ("rest", tool.rest), ("file_share", tool.file_share), ("messenger", tool.messenger),
        ("listener", tool.listener)) if config is not None]
    # Mail exposes these same transports; its credential probe checks IMAP and SMTP.
    if tool.mail and tool.file_share and tool.file_share.service == "mail":
        protocols.remove("file_share")
    if tool.mail and tool.messenger and tool.messenger.service == "mail":
        protocols.remove("messenger")
    if tool.code == "console":
        protocols = ["console"]
    for protocol in protocols:
        await check(protocol, _probes.get(protocol))
    if not checks:
        native = bool(native_tool_codes_for_tool(tool) & mcp_tools_by_tool_code().keys())
        checks.append(ConnectionCheck(protocol="internal", status="success" if native else "unsupported",
            message=await tr("connection_api.test.internal" if native else "connection_api.test.unsupported")))
    status: Literal["success", "error", "unsupported"] = (
        "error" if any(row.status == "error" for row in checks) else
        "unsupported" if any(row.status == "unsupported" for row in checks) else "success")
    return ConnectionTestResult(status=status, checks=checks)
