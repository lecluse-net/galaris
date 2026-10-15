"""Preserve validated repository references when an administrator equips their Console."""

from uuid import UUID
from collections.abc import Awaitable, Callable

from sqlalchemy import select, text

from core.database import get_db
from .contracts import CodeConnection, WorkspaceTarget, RUNTIME_CONFIGURATION_LOCK_OFFSET
from .models import CodeSession, CodeWorkspace


async def prepare_runtime_configuration(reference: CodeConnection, discover: Callable[[str], Awaitable[WorkspaceTarget]]) -> dict[UUID, WorkspaceTarget]:
    verified: dict[UUID, WorkspaceTarget] = {}
    workspaces = (await get_db().scalars(select(CodeWorkspace).where(
        CodeWorkspace.connection_id == reference.connection_id,
        CodeWorkspace.connection_fingerprint == reference.fingerprint,
    ))).all()
    for workspace in workspaces:
        try:
            target = await discover(workspace.root)
        except (ValueError, PermissionError, FileNotFoundError):
            continue
        if target.generation == workspace.generation:
            verified[workspace.id] = target
    return verified


async def lock_runtime_upgrade(reference: CodeConnection) -> None:
    # Session creation uses this lock, so none can open during the build.
    await get_db().execute(text("SELECT pg_advisory_xact_lock(:key)"), {
        "key": RUNTIME_CONFIGURATION_LOCK_OFFSET + reference.connection_id,
    })
    live = await get_db().scalar(select(CodeSession.id).join(CodeWorkspace,
        CodeWorkspace.id == CodeSession.workspace_id).where(
        CodeWorkspace.connection_id == reference.connection_id,
        CodeSession.state.in_(["opening", "ready"]),
    ).limit(1))
    if live is not None:
        raise ValueError("Close editor browser tabs and wait for sessions to expire before updating the editor")


async def finish_runtime_configuration(reference: CodeConnection, verified: dict[UUID, WorkspaceTarget],
                                       discover: Callable[[str], Awaitable[WorkspaceTarget]]) -> None:
    # A deployment must not interrupt an IDE which may contain unsaved buffers.
    live_session = await get_db().scalar(select(CodeSession.id).join(CodeWorkspace,
        CodeWorkspace.id == CodeSession.workspace_id).where(
        CodeWorkspace.connection_id == reference.connection_id,
        CodeSession.state.in_(["opening", "ready"]),
    ).limit(1))
    if live_session is not None:
        raise ValueError("Close editor browser tabs and wait for sessions to expire before changing the runtime configuration")
    for identifier, previous in verified.items():
        workspace = await get_db().get(CodeWorkspace, identifier, populate_existing=True, with_for_update=True)
        if workspace is None or workspace.generation != previous.generation:
            continue
        try:
            current = await discover(workspace.root)
        except (ValueError, PermissionError, FileNotFoundError):
            continue
        identity = ("home", "root", "git_paths", "root_identity", "git_identities")
        if any(getattr(previous, field) != getattr(current, field) for field in identity):
            continue
        workspace.generation = current.generation
        workspace.connection_fingerprint = reference.fingerprint
        workspace.branch, workspace.head = current.branch, current.head
