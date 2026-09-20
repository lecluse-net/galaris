"""Install the versioned enhanced-console helper on an SSH connection."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from .connection_service import resolve_connection
from .schemas import ConsoleHelperInstallResult
from .ssh_client import SshExecutionTransport


HELPER_VERSION = "2"
_HELPER_ASSET = Path(__file__).with_name("assets") / "galaris-exec"


def helper_payload() -> bytes:
    payload = _HELPER_ASSET.read_bytes()
    if not payload.startswith(b"#!/usr/bin/env python3\n"):
        raise RuntimeError("The packaged galaris-exec helper is invalid")
    return payload


async def install_connection_helper(
    connection_id: int,
) -> ConsoleHelperInstallResult:
    transport = SshExecutionTransport(await resolve_connection(connection_id))
    try:
        initial = await transport.status()
        if not (
            initial.reachable
            and initial.authenticated
            and initial.host_key_verified
            and initial.home_writable
            and initial.sftp_available
        ):
            raise RuntimeError(
                initial.error
                or "The standard SSH connection must pass its test before installation"
            )
        path = await transport.install_helper(
            helper_payload(),
            expected_version=HELPER_VERSION,
        )
        result = await transport.status()
        if (
            not result.galaris_exec_available
            or result.mode != "enhanced"
            or not result.operation_recovery_available
        ):
            raise RuntimeError("galaris-exec was installed but its verification failed")
    finally:
        await transport.close()

    logger.info(
        "galaris-exec installed: connection={} host={} path={} version={}",
        connection_id,
        transport.config.host,
        path,
        HELPER_VERSION,
    )
    return ConsoleHelperInstallResult(
        connection_id=connection_id,
        path=path,
        version=HELPER_VERSION,
        status=result,
    )
