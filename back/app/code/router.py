"""Human workspace APIs. A room or Agent management scope never grants repository access."""

from datetime import timedelta
from uuid import UUID
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from core.authorize import authorize
from core.database import get_db
from core.user import current_web_session_family, require_web_session

from .contracts import CodeRuntimeNotConfiguredError, CodeSessionUnavailableError, Mode, runtime
from .gateway import COOKIE, router as gateway_router
from .models import CodeConversationLink, CodeSession
from .schemas import HeartbeatInfo, RecoveryInfo, SessionInfo, SessionRequest, WorkspaceInfo
from .service import browser_session, editor_origin, get_workspace_record, current_user_id, human_mode, info, now, open_session, resume_session, validate_target

router = APIRouter(prefix="/code", tags=["code"])
router.include_router(gateway_router)


@router.get("/workspaces/{identifier}", response_model=WorkspaceInfo)
@authorize("CODE_ACCESS")
async def get_workspace(identifier: UUID) -> WorkspaceInfo:
    try:
        workspace = await get_workspace_record(identifier)
        user_id = await current_user_id()
        return info(workspace, await human_mode(workspace, user_id))
    except (PermissionError, FileNotFoundError) as exc:
        raise HTTPException(404, "Repository unavailable") from exc


@router.get("/rooms/{room_id}", response_model=list[WorkspaceInfo])
@authorize("CODE_ACCESS")
async def room_workspaces(room_id: UUID) -> list[WorkspaceInfo]:
    user_id = await current_user_id()
    identifiers = (await get_db().scalars(select(CodeConversationLink.workspace_id).where(
        CodeConversationLink.room_id == room_id).order_by(CodeConversationLink.requested_at.desc()).limit(50))).all()
    result: list[WorkspaceInfo] = []
    for identifier in identifiers:
        workspace = await get_workspace_record(identifier)
        try:
            result.append(info(workspace, await human_mode(workspace, user_id)))
        except PermissionError:
            continue
    return result


@router.post("/workspaces/{identifier}/sessions", response_model=SessionInfo, dependencies=[Depends(require_web_session)])
@authorize("CODE_ACCESS")
async def create_session(identifier: UUID, body: SessionRequest) -> SessionInfo:
    try:
        result = await open_session(identifier, body.mode)
        if body.file is not None or body.view is not None:
            workspace = await get_workspace_record(identifier)
            await runtime().navigate(await runtime().connection(workspace.connection_id), result.id, body.file, body.view or "changes")
        return result
    except (PermissionError, FileNotFoundError) as exc:
        raise HTTPException(403, "Repository unavailable or target changed") from exc
    except CodeRuntimeNotConfiguredError:
        raise HTTPException(503, "code_runtime_not_configured") from None
    except (RuntimeError, ValueError, OSError):
        raise HTTPException(503, "The prepared editor runtime is unavailable") from None


@router.post("/sessions/{identifier}/navigate")
@authorize("CODE_ACCESS")
async def navigate_session(identifier: UUID, body: SessionRequest) -> dict[str, str]:
    try:
        _, workspace = await browser_session(identifier)
        config, _ = await validate_target(workspace)
        await runtime().navigate(config, identifier, body.file, body.view or "changes")
    except (PermissionError, FileNotFoundError, ValueError):
        raise HTTPException(410, "Editor access or target changed") from None
    except (RuntimeError, OSError):
        raise HTTPException(503, "Editor runtime unavailable; keep this tab for recovery") from None
    return {"state": "requested"}


@router.post("/sessions/{identifier}/heartbeat", response_model=HeartbeatInfo)
@authorize("CODE_ACCESS")
async def heartbeat(identifier: UUID) -> HeartbeatInfo:
    session = await get_db().get(CodeSession, identifier)
    if (session is None or session.user_id != await current_user_id()
            or session.session_family != current_web_session_family()):
        raise HTTPException(404, "Editor session unavailable")
    try:
        session, workspace = await browser_session(identifier)
        config, _ = await validate_target(workspace)
        await runtime().touch(config, identifier)
        session.expires_at = now() + timedelta(minutes=10)
        await get_db().commit()
        return HeartbeatInfo(workspace=info(workspace, cast(Mode, session.mode)))
    except (PermissionError, ValueError, FileNotFoundError, CodeSessionUnavailableError):
        session.state = "failed"
        await get_db().commit()
        raise HTTPException(410, "Editor access or target changed") from None
    except Exception:
        raise HTTPException(503, "Editor runtime unavailable; keep this tab for recovery") from None


@router.post("/sessions/{identifier}/resume", response_model=RecoveryInfo, dependencies=[Depends(require_web_session)])
@authorize("CODE_ACCESS")
async def resume(identifier: UUID, response: Response) -> RecoveryInfo:
    try:
        session, workspace, cookie, restarted = await resume_session(identifier)
    except (PermissionError, ValueError, FileNotFoundError):
        raise HTTPException(403, "Editor access or target changed") from None
    except (RuntimeError, OSError):
        raise HTTPException(503, "Editor recovery unavailable; keep this tab for recovery") from None
    response.set_cookie(COOKIE, cookie, path=f"/api/code/gateway/{identifier}/", httponly=True,
        secure=editor_origin().startswith("https://"), samesite="strict", max_age=86400)
    response.headers["Cache-Control"] = "no-store"
    return RecoveryInfo(workspace=info(workspace, cast(Mode, session.mode)), restart_required=restarted,
        url=f"{editor_origin()}/api/code/gateway/{identifier}/editor/" if restarted else None)
