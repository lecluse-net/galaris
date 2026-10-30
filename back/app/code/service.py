"""Repository identity, explicit access and durable, idempotent IDE sessions."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import PurePosixPath
import secrets
from typing import cast
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from core.authorize import check_privilege, role_id_ctx
from core.database import get_db
from core.settings import settings
from core.user import current_web_session_family, get_current_user, get_user_record, web_session_active

from .contracts import CodeConnection, CodeRuntimeNotConfiguredError, CodeSessionUnavailableError, RepositoryCandidates, WorkspaceTarget, Mode, RUNTIME_CONFIGURATION_LOCK_OFFSET, runtime
from .models import CodeConversationLink, CodeDisplayRequest, CodeGrant, CodeSession, CodeWorkspace
from .schemas import SessionInfo, WorkspaceInfo


def now() -> datetime:
    return datetime.now(timezone.utc)


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def editor_origin() -> str:
    value = settings.APP_HOST.strip().rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path
            or parsed.query or parsed.fragment or parsed.username or parsed.password
            or (not settings.is_dev and parsed.scheme != "https")):
        raise RuntimeError("Configure a secure APP_HOST origin")
    return value


async def current_user_id() -> int:
    user = await get_current_user()
    if user is None:
        raise PermissionError("Authentication required")
    return user.id


async def get_workspace_record(identifier: UUID) -> CodeWorkspace:
    value = await get_db().get(CodeWorkspace, identifier)
    if value is None:
        raise FileNotFoundError("Repository unavailable")
    return value


async def human_mode(workspace: CodeWorkspace, user_id: int) -> Mode:
    user = await get_user_record(user_id)
    if user is None or not user.is_active or not await check_privilege(user, "CODE_ACCESS", get_db()):
        raise PermissionError("Repository unavailable")
    mode = await get_db().scalar(select(CodeGrant.mode).where(
        CodeGrant.workspace_id == workspace.id, CodeGrant.user_id == user_id))
    if mode not in ("read", "edit"):
        raise PermissionError("Repository unavailable")
    return mode


def info(workspace: CodeWorkspace, mode: Mode) -> WorkspaceInfo:
    return WorkspaceInfo(id=workspace.id, uri=f"galaris://code/{workspace.id}",
        label=PurePosixPath(workspace.root).relative_to(workspace.home).as_posix(), mode=mode)


async def human_repository_candidates(agent_id: int, user_id: int) -> RepositoryCandidates:
    config = await runtime().connection_for_agent(agent_id)
    if config.owner_user_id != user_id:
        raise PermissionError("Only the Console owner can discover repositories")
    return await runtime().repositories(config)


async def workspace_for_agent(identifier: UUID, agent_id: int) -> CodeWorkspace:
    workspace = await get_workspace_record(identifier)
    allowed = await get_db().scalar(select(CodeGrant.id).where(
        CodeGrant.workspace_id == identifier, CodeGrant.agent_id == agent_id))
    if allowed is None:
        raise PermissionError("Agent cannot read this repository")
    return workspace


async def register_repository(reference: str, agent_id: int) -> CodeWorkspace:
    return await _register_repository(reference, agent_id)


async def _register_repository(reference: str, agent_id: int, user_id: int | None = None) -> CodeWorkspace:
    parsed = urlsplit(reference)
    if parsed.scheme == "galaris" and parsed.netloc == "code" and not parsed.query and not parsed.fragment:
        return await workspace_for_agent(UUID(parsed.path.strip("/")), agent_id)
    if parsed.scheme != "console" or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("Use a console:// directory or galaris://code/<uuid>")
    path = unquote(parsed.netloc + parsed.path).rstrip("/") or "."
    config = await runtime().connection_for_agent(agent_id)
    if config.owner_user_id is None:
        raise PermissionError("An owned, active Console is required")
    target = await runtime().discover(config, path)
    # Lock identity before looking it up; callers never race a second owner/grant.
    key = int(digest(f"{config.connection_id}:{target.root}")[:15], 16)
    await get_db().execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    workspace = await get_db().scalar(select(CodeWorkspace).where(
        CodeWorkspace.connection_id == config.connection_id, CodeWorkspace.root == target.root,
        CodeWorkspace.generation == target.generation))
    if workspace is not None:
        workspace = await workspace_for_agent(workspace.id, agent_id)
        if user_id is not None:
            await human_mode(workspace, user_id)
        return workspace
    if user_id is not None and config.owner_user_id != user_id:
        raise PermissionError("Only the Console owner can register a repository")
    workspace = CodeWorkspace(id=uuid4(), connection_id=config.connection_id, agent_id=agent_id,
        owner_user_id=config.owner_user_id, label=PurePosixPath(target.root).name[:200],
        root=target.root, home=target.home, git_paths=list(target.git_paths),
        generation=target.generation, connection_fingerprint=config.fingerprint, branch=target.branch, head=target.head)
    get_db().add(workspace)
    await get_db().flush()
    get_db().add_all([
        CodeGrant(workspace_id=workspace.id, agent_id=agent_id, mode="edit"),
        CodeGrant(workspace_id=workspace.id, user_id=config.owner_user_id, mode="edit"),
    ])
    await get_db().flush()
    return workspace


async def human_directory_repository(reference: str, agent_id: int, user_id: int, room_id: UUID | None = None) -> WorkspaceInfo:
    if not reference.startswith("console://"):
        raise ValueError("A Console directory is required")
    workspace = await _register_repository(reference, agent_id, user_id)
    mode = await human_mode(workspace, user_id)
    if room_id is not None:
        await link_repository(workspace, room_id, None, view="files")
    await get_db().commit()
    return info(workspace, mode)


async def link_repository(workspace: CodeWorkspace, room_id: UUID, task_id: UUID | None,
                          file: str | None = None, view: str = "changes") -> int:
    await get_db().execute(insert(CodeConversationLink).values(
        workspace_id=workspace.id, room_id=room_id, task_id=task_id, requested_at=now(),
    ).on_conflict_do_update(index_elements=["workspace_id", "room_id"],
        set_={"requested_at": now(), "task_id": task_id}))
    request = CodeDisplayRequest(workspace_id=workspace.id, room_id=room_id, task_id=task_id, file=file, view=view)
    get_db().add(request)
    await get_db().flush()
    return request.id


async def validate_target(workspace: CodeWorkspace) -> tuple[CodeConnection, WorkspaceTarget]:
    config = await session_config(workspace)
    target = await runtime().discover(config, workspace.root)
    if target.generation != workspace.generation:
        raise PermissionError("Repository target changed; present it again after validation")
    workspace.branch, workspace.head = target.branch, target.head
    return config, target


async def session_config(workspace: CodeWorkspace) -> CodeConnection:
    config = await runtime().connection(workspace.connection_id)
    if config.fingerprint != workspace.connection_fingerprint:
        raise PermissionError("Console target changed")
    return config


async def open_session(identifier: UUID, requested: Mode | None) -> SessionInfo:
    origin = editor_origin()
    user_id = await current_user_id()
    family = current_web_session_family()
    user = await get_user_record(user_id)
    if family is None or user is None:
        raise PermissionError("A current browser session is required; sign in again")
    workspace = await get_workspace_record(identifier)
    available = await human_mode(workspace, user_id)
    mode = requested or available
    if mode == "edit" and available != "edit":
        raise PermissionError("Editing is not granted")
    await get_db().execute(text("SELECT pg_advisory_xact_lock(:key)"), {
        "key": RUNTIME_CONFIGURATION_LOCK_OFFSET + workspace.connection_id,
    })
    await get_db().refresh(workspace)
    config, target = await validate_target(workspace)
    # A user-wide lock bounds concurrent quota checks and double-open requests.
    await get_db().execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 8200000000 + user_id})
    session = await get_db().scalar(select(CodeSession).where(
        CodeSession.workspace_id == identifier, CodeSession.user_id == user_id,
        CodeSession.mode == mode, CodeSession.session_family == family,
        CodeSession.state.in_(["opening", "ready"])).with_for_update())
    if session is not None and (session.expires_at <= now() or session.created_at + timedelta(days=1) <= now()):
        session.state, session.cookie_digest, session.ticket_digest = "closing", None, None
        await get_db().commit()
        await runtime().close(config, session.id)
        session.state = "closed"
    if session is None:
        # Recover this human's retained hot-exit profile after expiry/relogin.
        # Another live browser family retains its own independent session.
        session = await get_db().scalar(select(CodeSession).where(
            CodeSession.workspace_id == identifier, CodeSession.user_id == user_id,
            CodeSession.mode == mode, CodeSession.state.in_(["closed", "failed"])
        ).order_by(CodeSession.created_at.desc()).limit(1).with_for_update())
    if session is not None and session.state in ("closed", "failed"):
        session.state, session.cookie_digest = "opening", None
        session.created_at, session.expires_at = now(), now() + timedelta(minutes=10)
        session.session_family, session.auth_version, session.role_id = family, user.auth_version, role_id_ctx.get()
        session.role_bound = session.role_id is not None
    if session is None:
        count = await get_db().scalar(select(func.count()).select_from(CodeSession).where(
            CodeSession.user_id == user_id, CodeSession.state.in_(["opening", "ready"])))
        if (count or 0) >= 8:
            raise RuntimeError("Editor session quota reached; close browser tabs and wait for inactive sessions to expire")
        session = CodeSession(id=uuid4(), workspace_id=identifier, user_id=user_id,
            role_id=role_id_ctx.get(), session_family=family, auth_version=user.auth_version,
            role_bound=role_id_ctx.get() is not None,
            mode=mode, state="opening", expires_at=now() + timedelta(minutes=10), created_at=now())
        get_db().add(session)
    ticket = secrets.token_urlsafe(32)
    session.ticket_digest, session.ticket_expires_at = digest(ticket), now() + timedelta(seconds=60)
    await get_db().commit()  # Persist the operation identity before calling the external runtime.
    try:
        await runtime().open(config, target, session.id, mode)
    except Exception as exc:
        session.state = "failed"
        await get_db().commit()
        if isinstance(exc, CodeRuntimeNotConfiguredError):
            raise
        raise RuntimeError("The prepared code runtime could not open this repository") from None
    session.state = "ready"
    session.expires_at = now() + timedelta(minutes=10)
    await get_db().commit()
    return SessionInfo(id=session.id, workspace=info(workspace, mode), expires_at=session.expires_at,
        url=f"{origin}/api/code/gateway/{session.id}/launch#ticket={ticket}")


async def authorize_session(identifier: UUID, cookie: str, *, ticket: bool = False) -> tuple[CodeSession, CodeWorkspace]:
    session = await get_db().get(CodeSession, identifier, populate_existing=True)
    if session is None or session.state != "ready" or session.expires_at <= now() or session.created_at + timedelta(days=1) <= now():
        raise PermissionError("Editor session expired")
    expected = session.ticket_digest if ticket else session.cookie_digest
    if not cookie or expected is None or not hmac.compare_digest(expected, digest(cookie)):
        raise PermissionError("Invalid editor credential")
    if ticket and (session.ticket_expires_at is None or session.ticket_expires_at <= now()):
        raise PermissionError("Launch ticket expired")
    return session, await session_workspace(session)


async def session_workspace(session: CodeSession, *, resuming: bool = False) -> CodeWorkspace:
    """The same live authorization applies to cookies and browser control actions."""
    if (session.state not in (("ready", "closed", "failed") if resuming else ("ready",))
            or (not resuming and (session.expires_at <= now() or session.created_at + timedelta(days=1) <= now()))):
        raise PermissionError("Editor session expired")
    workspace = await get_workspace_record(session.workspace_id)
    user = await get_user_record(session.user_id)
    if user is None or user.auth_version != session.auth_version or not await web_session_active(session.user_id, session.session_family):
        raise PermissionError("Browser session revoked")
    if (session.role_bound and session.role_id is None) or not await check_privilege(user, "CODE_ACCESS", get_db(), role_id=session.role_id):
        raise PermissionError("Editor role revoked")
    allowed = await human_mode(workspace, session.user_id)
    if session.mode == "edit" and allowed != "edit":
        raise PermissionError("Editing grant was revoked")
    return workspace


async def resume_session(identifier: UUID) -> tuple[CodeSession, CodeWorkspace, str, bool]:
    """Explicitly recover the same profile without replacing the browser's buffers."""
    session = await get_db().get(CodeSession, identifier)
    if (session is None or session.user_id != await current_user_id()
            or session.session_family != current_web_session_family()):
        raise PermissionError("Editor browser session unavailable")
    workspace = await get_workspace_record(session.workspace_id)
    await get_db().execute(text("SELECT pg_advisory_xact_lock(:key)"), {
        "key": RUNTIME_CONFIGURATION_LOCK_OFFSET + workspace.connection_id,
    })
    await get_db().execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 8200000000 + session.user_id})
    await get_db().refresh(session, with_for_update=True)
    if session.session_family != current_web_session_family():
        raise PermissionError("Editor browser session changed")
    workspace = await session_workspace(session, resuming=True)
    config, target = await validate_target(workspace)
    count = await get_db().scalar(select(func.count()).select_from(CodeSession).where(
        CodeSession.user_id == session.user_id, CodeSession.id != session.id,
        CodeSession.state.in_(["opening", "ready"])))
    if (count or 0) >= 8:
        raise RuntimeError("Editor session quota reached")
    restarted = False
    try:
        await runtime().touch(config, session.id)
    except CodeSessionUnavailableError:
        restarted = True
    session.state = "opening"
    session.cookie_digest, session.ticket_digest = None, None
    await get_db().commit()
    try:
        await runtime().open(config, target, session.id, cast(Mode, session.mode))
    except Exception:
        session.state = "failed"
        await get_db().commit()
        raise RuntimeError("Editor recovery unavailable; keep this tab for recovery") from None
    # Recheck live rights after starting external work, before granting access.
    session.state = "ready"
    await session_workspace(session, resuming=True)
    await validate_target(workspace)
    cookie = secrets.token_urlsafe(32)
    session.cookie_digest = digest(cookie)
    session.created_at, session.expires_at = now(), now() + timedelta(minutes=10)
    await get_db().commit()
    return session, workspace, cookie, restarted


async def browser_session(identifier: UUID) -> tuple[CodeSession, CodeWorkspace]:
    session = await get_db().get(CodeSession, identifier, populate_existing=True)
    if (session is None or session.user_id != await current_user_id()
            or session.session_family != current_web_session_family()):
        raise PermissionError("Editor browser session unavailable")
    return session, await session_workspace(session)


async def workspace_context(identifier: UUID, user_id: int, room_id: UUID) -> dict[str, str | None]:
    workspace = await get_workspace_record(identifier)
    await human_mode(workspace, user_id)
    link = await get_db().scalar(select(CodeConversationLink.id).where(
        CodeConversationLink.workspace_id == identifier, CodeConversationLink.room_id == room_id))
    if link is None:
        raise PermissionError("Repository was not presented in this conversation")
    await validate_target(workspace)
    return {"displayed_repository_uri": f"galaris://code/{identifier}",
            "repository_branch": workspace.branch, "repository_head": workspace.head}


async def human_repository_info(identifier: UUID, user_id: int) -> WorkspaceInfo:
    workspace = await get_workspace_record(identifier)
    return info(workspace, await human_mode(workspace, user_id))
