"""Reconcile durable IDE leases and revoked sessions after worker interruptions."""

import asyncio
from datetime import timedelta

from loguru import logger
from sqlalchemy import select

from core.database import get_db
from core.authorize import check_privilege
from core.user import get_user_record, web_session_active

from .contracts import runtime
from .models import CodeSession
from .service import get_workspace_record, human_mode, now, session_config

RECONCILIATION_BATCH_SIZE = 128


async def reconcile_sessions() -> None:
    sessions = (await get_db().scalars(select(CodeSession).where(
        CodeSession.state.in_(["opening", "ready", "closing", "failed"])
    ).order_by(CodeSession.reconciled_at.asc().nulls_first(), CodeSession.created_at)
    .limit(RECONCILIATION_BATCH_SIZE))).all()
    for session in sessions:
        # Persist progress before external work. A dead target or worker interruption
        # must not repeatedly starve later sessions of reconciliation.
        session.reconciled_at = now()
        await get_db().commit()
        workspace = await get_workspace_record(session.workspace_id)
        try:
            if session.state in ("closing", "failed") or session.expires_at <= now() or session.created_at + timedelta(days=1) <= now():
                raise PermissionError("Expired session")
            user = await get_user_record(session.user_id)
            if user is None or user.auth_version != session.auth_version or not await web_session_active(session.user_id, session.session_family):
                raise PermissionError("Browser session revoked")
            if (session.role_bound and session.role_id is None) or not await check_privilege(user, "CODE_ACCESS", get_db(), role_id=session.role_id):
                raise PermissionError("Editor role revoked")
            mode = await human_mode(workspace, session.user_id)
            if session.mode == "edit" and mode != "edit":
                raise PermissionError("Editing grant revoked")
            await session_config(workspace)
            continue
        except (PermissionError, FileNotFoundError, ValueError):
            session.state, session.cookie_digest, session.ticket_digest = "closing", None, None
            await get_db().commit()
        try:
            async with asyncio.timeout(5):
                await runtime().close(await runtime().connection(workspace.connection_id), session.id)
        except Exception:
            logger.warning("Code session {} awaits runtime cleanup", session.id)
        else:
            session.state = "closed"
            await get_db().commit()
