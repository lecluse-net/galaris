"""Reconcile configured external editors after the deployed backend becomes ready.

This infrastructure CLI has no HTTP or agent-tool entry point. Initial installation
remains an explicit Console administration action; maintenance never changes access.
"""

import asyncio
import sys

from core.database import get_db_session, load_models
from core.update_diagnostics import record_update_failure


async def update_editors() -> bool:
    # Bootstrap mappers before importing composed application services, as in DbAdmin.
    load_models()
    from app.console import configured_external_editor_connections
    from bridge.code_server.deployment import EditorDeploymentError, update_connection_code_editor

    async with get_db_session():
        connections = await configured_external_editor_connections()
    succeeded = True
    for connection_id in connections:
        try:
            async with get_db_session():
                result = await update_connection_code_editor(connection_id)
            if result is None:
                sys.stdout.write(f"Code editor for Console connection {connection_id}: manually administered, left unchanged.\n")
                continue
            action = "verified" if result.already_installed else "updated"
            sys.stdout.write(f"Code editor for Console connection {connection_id}: {action} ({result.version}).\n")
        except Exception as error:
            # SSH/Docker exceptions can contain credentials or remote command output.
            # Report every failed target and still maintain the independent targets.
            succeeded = False
            diagnostic = record_update_failure(error, connection_id=connection_id,
                details=error.diagnostic if isinstance(error, EditorDeploymentError) else None)
            detail = f" {error}." if isinstance(error, EditorDeploymentError) else ""
            sys.stderr.write(
                f"Code editor for Console connection {connection_id}: update failed.{detail} "
                f"Diagnostic: {diagnostic or 'storage unavailable; see diagnostic above'}. "
                "Save files and close editor sessions, verify SSH/Docker access and the "
                "configured managed editor, then rerun make update.\n"
            )
    return succeeded


def main() -> int:
    try:
        return 0 if asyncio.run(update_editors()) else 1
    except Exception as error:
        diagnostic = record_update_failure(error)
        sys.stderr.write("Unable to enumerate configured code editors; make update did not complete.\n")
        sys.stderr.write(f"Diagnostic: {diagnostic or 'storage unavailable; see diagnostic above'}.\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
