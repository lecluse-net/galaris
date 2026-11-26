"""Durable direct harness conversations and ordered replay of their visible activity."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import exists, select
from sqlalchemy.orm import aliased

from app.agent import AIMessage, ExecutionResult, ResolvedExecutionTarget, ResolvedModel, assess_checkpoint, classify_execution_error
from app.agent.contracts import AgentRunCheckpoint, ReasoningEffort, ScopedInferenceAdmission
from app.agent.facade import deep_execution_target, deep_harness_target, steer_deep_input, stream_deep_submission
from app.messenger import Message, Room, get_messenger, has_chat_room_access
from app.services.facade import authorization_context_pending, canonical_authorization_snapshot, invalidate_authorization_context
from core.database import get_db, get_db_session
from core.i18n import normalize_language
from core.params import runtime_settings
from core.util import get_encryption_service

from .contracts import inference_binding, inference_limit, inference_tool_calls_used, public_ai_message, reserve_inference_tool
from .checkpoint_journal import read_checkpoint_payload
from .deep_failures import DeepFailureInfo, describe_deep_failure, read_deep_failures
from .models import ConversationRoundMessage, DeepEvent, DeepRoomMode, DeepSession, DeepSubmission

DeepState = Literal["queued", "running", "waiting_approval", "completed", "failed", "interrupted", "cancelled", "steered"]
_TERMINAL_STATES = frozenset({"completed", "failed", "interrupted", "cancelled", "steered"})
_LEASE = timedelta(seconds=45)
_MAX_ACTIVE = 16
_workers: set[asyncio.Task[None]] = set()
_supervisor: asyncio.Task[None] | None = None
_wakeup: asyncio.Event | None = None
_listener: Callable[[UUID], Awaitable[None]] | None = None
_workspace_access: Callable[[UUID, int, UUID, int], Awaitable[dict[str, str | None]]] | None = None


class DeepSubmissionInfo(BaseModel):
    id: UUID
    session_id: UUID
    message_id: UUID
    response_message_id: UUID | None
    state: str
    sequence: int
    stop_requested: bool
    has_activity: bool
    approvals: list[UUID]
    failure: DeepFailureInfo | None = None


class DeepRoomInfo(BaseModel):
    enabled: bool
    submissions: list[DeepSubmissionInfo]


class DeepActivityEvent(BaseModel):
    sequence: int
    kind: str
    payload: dict[str, object]


def register_deep_listener(listener: Callable[[UUID], Awaitable[None]]) -> None:
    global _listener
    _listener = listener


def register_deep_workspace_access(
    check: Callable[[UUID, int, UUID, int], Awaitable[dict[str, str | None]]],
) -> None:
    global _workspace_access
    _workspace_access = check


async def _notify(room_id: UUID) -> None:
    if _listener is not None:
        try:
            async with asyncio.timeout(2):
                await _listener(room_id)
        except Exception:
            logger.warning("Could not notify Chat of Deep activity in room {}", room_id)


def _wake() -> None:
    if _wakeup is not None:
        _wakeup.set()


def _workspace_id(message: Message) -> UUID | None:
    context = message.metadata_.get("repository_context")
    if not isinstance(context, dict):
        return None
    uri = str(cast(dict[str, object], context).get("displayed_repository_uri") or "")
    if uri.startswith("galaris://code/"):
        return UUID(uri.removeprefix("galaris://code/"))
    return None


def _deep_command_argument(text: str) -> str | None:
    parts = text.strip().split(maxsplit=1)
    if not parts or parts[0].casefold() != "@deep":
        return None
    return parts[1] if len(parts) == 2 else ""


def _deep_input_text(text: str) -> str:
    argument = _deep_command_argument(text)
    return text if argument is None else argument


def _session_target(session: DeepSession) -> ResolvedExecutionTarget:
    return deep_execution_target(ResolvedExecutionTarget.model_validate(session.target))


async def admit_deep_input(message: Message, *, agent_id: int, connection_id: int) -> bool:
    """Consume an internal Chat command or direct input exactly once."""

    room_id = message.messenger_room_id
    if room_id is None or message.platform != "internal" or message.requester_user_id is None:
        return False
    argument = _deep_command_argument(message.text)
    toggle = argument == "" and not message.attachments and not message.resource_uris
    async with get_db_session() as db:
        room = await db.scalar(select(Room).where(Room.id == room_id).with_for_update())
        if room is None or room.kind != "direct" or room.connection_id != connection_id:
            return False
        if await db.scalar(select(DeepSubmission.id).where(DeepSubmission.message_id == message.id)):
            return True
        mode = await db.get(DeepRoomMode, room_id)
        if argument is None and (mode is None or not mode.enabled):
            return False
        # Recovery must preserve messages previously admitted in standard mode,
        # including messages with a prefix that was introduced after admission.
        if await db.scalar(select(ConversationRoundMessage.message_id).where(
            ConversationRoundMessage.message_id == message.id, ConversationRoundMessage.role == "input",
        )):
            return False
        if argument is not None:
            if mode is None:
                db.add(DeepRoomMode(room_id=room_id, enabled=True))
            else:
                mode.enabled = not mode.enabled if toggle else True
        if toggle:
            db.add(DeepSubmission(message_id=message.id, state="toggle"))
        else:
            driver_code, target = await deep_harness_target(agent_id)
            workspace_id = _workspace_id(message)
            session = await db.scalar(select(DeepSession).where(
                DeepSession.room_id == room_id, DeepSession.closed_at.is_(None),
            ))
            if session is not None:
                if session.workspace_bound and session.workspace_id is None and workspace_id is None:
                    raise PermissionError("The Deep checkout is no longer available. Select another checkout.")
                workspace_id = workspace_id or session.workspace_id
                if (session.agent_id, session.requester_user_id, session.workspace_id, session.driver_code, _session_target(session)) != (
                    agent_id, message.requester_user_id, workspace_id, driver_code, target,
                ):
                    if await db.scalar(select(DeepSubmission.id).where(
                        DeepSubmission.session_id == session.id,
                        DeepSubmission.state.in_(("queued", "running", "steering", "waiting_approval")),
                    ).limit(1)):
                        raise PermissionError("The current Deep session still has pending work.")
                    session.closed_at = datetime.now(timezone.utc)
                    await db.flush()
                    session = None
            if session is None:
                session = DeepSession(room_id=room_id, agent_id=agent_id, requester_user_id=message.requester_user_id,
                                      workspace_id=workspace_id, workspace_bound=workspace_id is not None,
                                      driver_code=driver_code, target=target.model_dump(mode="json"))
                db.add(session)
                await db.flush()
                if target.metadata.get("galaris_extensions") is True:
                    session.inference_credential = get_encryption_service().encrypt(f"galaris:deep:v1:{session.id}")
            db.add(DeepSubmission(message_id=message.id, session_id=session.id, state="queued"))
        await db.commit()
    await _notify(room_id)
    _wake()
    return True


async def deep_session_agent(session_id: UUID) -> int | None:
    return await get_db().scalar(select(DeepSession.agent_id).where(DeepSession.id == session_id))


async def authorize_deep_runtime(session_id: UUID, agent_id: int) -> int:
    session = await get_db().get(DeepSession, session_id)
    if (session is None or session.agent_id != agent_id or session.closed_at is not None
            or not await has_chat_room_access(session.requester_user_id, session.room_id)
            or (session.driver_code, _session_target(session)) != await deep_harness_target(agent_id)):
        raise PermissionError("The Deep session is unavailable for this runtime.")
    return session.requester_user_id


async def _embedded_submission(
    session_id: UUID, submission_id: UUID, agent_id: int, *, lock: bool = False, include_waiting: bool = False,
) -> tuple[DeepSubmission, int]:
    active = (DeepSubmission.state == "running") & (DeepSubmission.lease_until > datetime.now(timezone.utc))
    if include_waiting:
        active = active | (DeepSubmission.state == "waiting_approval")
    stmt = select(DeepSubmission, DeepSession).join(DeepSession).where(
        DeepSubmission.id == submission_id, DeepSubmission.session_id == session_id,
        DeepSession.agent_id == agent_id, DeepSession.closed_at.is_(None),
        DeepSession.driver_code == "claude_embedded", DeepSubmission.stop_requested.is_(False), active,
    ).execution_options(populate_existing=True)
    if lock:
        stmt = stmt.with_for_update(of=DeepSubmission)
    row = (await get_db().execute(stmt)).one_or_none()
    if row is None:
        raise PermissionError("The embedded Deep submission is no longer active.")
    item, session = row
    requester = await authorize_deep_runtime(session_id, agent_id)
    if session.workspace_bound and session.workspace_id is None:
        raise PermissionError("The Deep checkout is no longer available.")
    if session.workspace_id is not None:
        if _workspace_access is None:
            raise PermissionError("The Deep workspace is unavailable.")
        try:
            await _workspace_access(session.workspace_id, requester, session.room_id, agent_id)
        except FileNotFoundError as exc:
            raise PermissionError("The Deep workspace is unavailable.") from exc
    return item, requester


async def _admit_embedded_inference(
    session_id: UUID, submission_id: UUID, agent_id: int, model: ResolvedModel, lease_token: UUID,
) -> ScopedInferenceAdmission:
    async with get_db_session():
        item, _ = await _embedded_submission(session_id, submission_id, agent_id, lock=True)
        snapshot = {"model_id": model.id, "model_code": model.code, "reasoning_effort": model.reasoning_effort}
        prior = item.inference_admission
        if item.lease_token != lease_token:
            raise PermissionError("The Deep submission lease was lost.")
        if prior is not None and any(prior.get(key) != value for key, value in snapshot.items()):
            raise PermissionError("The Deep submission already has a different admitted model.")
        request_limit = inference_limit(prior, "request_limit") or runtime_settings.TASK_AGENT_MAX_REQUESTS
        tool_call_limit = inference_limit(prior, "tool_call_limit") or runtime_settings.TASK_AGENT_MAX_TOOL_CALLS
        item.inference_admission = {**snapshot, "claim": str(lease_token), "request_limit": request_limit,
                                    "tool_call_limit": tool_call_limit, "tool_calls_used": inference_tool_calls_used(prior)}

    async def reserve_tool(previously_recorded: int) -> bool:
        async with get_db_session():
            owned, _ = await _embedded_submission(session_id, submission_id, agent_id, lock=True)
            if owned.lease_token != lease_token or owned.lease_until is None or owned.lease_until <= datetime.now(timezone.utc):
                raise PermissionError("The Deep tool attempt is no longer active.")
            reserved = reserve_inference_tool(owned.inference_admission, previously_recorded)
            if reserved is None:
                return False
            owned.inference_admission = reserved
            return True

    return ScopedInferenceAdmission(lease_token, request_limit, tool_call_limit, reserve_tool)


async def authorize_embedded_deep_inference(
    session_id: UUID, submission_id: UUID, agent_id: int, *, claim_id: UUID,
    model_id: int, model_code: str, reasoning_effort: ReasoningEffort | None,
    request_limit: int | None = None,
) -> int:
    item, requester = await _embedded_submission(session_id, submission_id, agent_id)
    admission = inference_binding(item.inference_admission)
    expected: dict[str, object] = {
        "claim": str(claim_id), "model_id": model_id, "model_code": model_code,
        "reasoning_effort": reasoning_effort,
    }
    if admission is not None and "request_limit" in admission:
        expected["request_limit"] = request_limit
    if item.lease_token != claim_id or admission != expected:
        raise PermissionError("The Deep inference does not match the admitted submission, model and request limit.")
    return requester


def _embedded_context(session_id: UUID, submission_id: UUID) -> str:
    return f"deep:{session_id}:submission:{submission_id}"


def _context_ids(context: str) -> tuple[UUID, UUID | None]:
    if not context.startswith("deep:"):
        raise ValueError("Invalid Deep authorization context.")
    session, marker, submission = context.removeprefix("deep:").partition(":submission:")
    return UUID(session), UUID(submission) if marker else None


async def _authorization_scope(agent_id: int, context: str) -> dict[str, object] | None:
    try:
        session_id, submission_id = _context_ids(context)
        if submission_id is None:
            requester = await authorize_deep_runtime(session_id, agent_id)
        else:
            _, requester = await _embedded_submission(session_id, submission_id, agent_id, include_waiting=True)
    except (ValueError, PermissionError):
        return None
    db = get_db()
    session = await db.get(DeepSession, session_id)
    if session is None:
        return None
    snapshot: dict[str, object] = {
        "room": str(session.room_id), "workspace": str(session.workspace_id or ""), "requester": requester,
    }
    if submission_id is not None:
        return {**snapshot, "submission": str(submission_id)}
    if session.driver_code == "claude_embedded":
        return None
    if session.workspace_bound and session.workspace_id is None:
        return None
    if not await db.scalar(select(DeepSubmission.id).where(
        DeepSubmission.session_id == session_id, DeepSubmission.state == "running", DeepSubmission.stop_requested.is_(False),
    ).limit(1)):
        return None
    if session.workspace_id is not None:
        if _workspace_access is None:
            return None
        try:
            await _workspace_access(session.workspace_id, requester, session.room_id, agent_id)
        except (PermissionError, FileNotFoundError):
            return None
    return snapshot


async def _wake_authorization_context(agent_id: int, context: str) -> bool:
    try:
        session_id, submission_id = _context_ids(context)
    except ValueError:
        return False
    if submission_id is None:
        return False
    async with get_db_session() as db:
        row = (await db.execute(select(DeepSubmission, DeepSession.room_id).join(DeepSession).where(
            DeepSubmission.id == submission_id, DeepSubmission.session_id == session_id,
            DeepSession.agent_id == agent_id, DeepSession.driver_code == "claude_embedded",
        ).with_for_update(of=DeepSubmission))).one_or_none()
        if row is None:
            return True
        item, room_id = row
        if item.state == "running":
            return False
        if item.state != "waiting_approval":
            return True
        if await authorization_context_pending(agent_id, context):
            return False
        item.state = "queued"
    await _notify(room_id)
    _wake()
    return True


async def deep_room_info(room_id: UUID, viewer_id: int) -> DeepRoomInfo:
    db = get_db()
    enabled = await db.scalar(select(DeepRoomMode.enabled).where(DeepRoomMode.room_id == room_id))
    activity_exists = select(DeepEvent.id).where(
        DeepEvent.submission_id == DeepSubmission.id, DeepEvent.kind == "activity",
    ).exists()
    rows = (await db.execute(select(DeepSubmission, activity_exists, DeepSession.driver_code)
        .join(DeepSession, DeepSession.id == DeepSubmission.session_id)
        .where(DeepSession.room_id == room_id)
        .order_by(DeepSubmission.created_at.desc(), DeepSubmission.id.desc()).limit(50))).all()
    submissions = [item for item, _, _ in rows]
    from app.services.facade import pending_context_approvals

    contexts = {item.id: (_embedded_context(item.session_id, item.id) if driver == "claude_embedded" else f"deep:{item.session_id}")
                for item, _, driver in rows if item.session_id is not None and item.state in ("running", "waiting_approval")}
    approvals = await pending_context_approvals(set(contexts.values()), approver_user_id=viewer_id)
    failures = await read_deep_failures(submissions)
    infos = [DeepSubmissionInfo(
        id=item.id, session_id=item.session_id, message_id=item.message_id,
        response_message_id=item.response_message_id,
        state="running" if item.state == "waiting_approval" else item.state, sequence=item.last_sequence,
        stop_requested=item.stop_requested, has_activity=has_activity,
        approvals=approvals.get(contexts.get(item.id, ""), []),
        failure=failures.get(item.id),
    ) for item, has_activity, _ in reversed(rows) if item.session_id is not None]
    return DeepRoomInfo(enabled=bool(enabled), submissions=infos)


async def deep_events(room_id: UUID, submission_id: UUID, after: int, limit: int) -> list[DeepActivityEvent] | None:
    db = get_db()
    if not await db.scalar(select(DeepSubmission.id).join(DeepSession)
                           .where(DeepSession.room_id == room_id, DeepSubmission.id == submission_id)):
        return None
    events = (await db.scalars(select(DeepEvent).where(
        DeepEvent.submission_id == submission_id, DeepEvent.sequence > after,
    ).order_by(DeepEvent.sequence).limit(limit))).all()
    return [DeepActivityEvent(sequence=item.sequence, kind=item.kind, payload=item.payload) for item in events]


async def stop_deep_submission(room_id: UUID, submission_id: UUID) -> bool:
    db = get_db()
    row = (await db.execute(select(DeepSubmission, DeepSession).join(DeepSession)
                          .where(DeepSession.room_id == room_id, DeepSubmission.id == submission_id)
                          .with_for_update(of=DeepSubmission))).one_or_none()
    if row is None:
        return False
    item, session = row
    active = item.state not in _TERMINAL_STATES
    if item.state in ("queued", "waiting_approval"):
        item.state = "cancelled"
    elif item.state == "running":
        item.stop_requested = True
    await db.commit()
    if active and session.driver_code == "claude_embedded":
        await invalidate_authorization_context(session.agent_id, _embedded_context(session.id, item.id))
    await _notify(room_id)
    _wake()
    return True


async def _claim() -> tuple[UUID, UUID] | None:
    now = datetime.now(timezone.utc)
    async with get_db_session() as db:
        expired = (await db.execute(select(DeepSubmission, DeepSession).join(DeepSession)
            .where(DeepSubmission.state.in_(("running", "steering")), DeepSubmission.lease_until <= now)
            .limit(_MAX_ACTIVE).with_for_update(of=DeepSubmission, skip_locked=True))).all()
        for item, _ in expired:
            item.state = "interrupted"
            item.lease_until = None
            item.lease_token = None
        running = aliased(DeepSubmission)
        claimed = (await db.execute(select(DeepSubmission, DeepSession.room_id).join(DeepSession)
            .where(DeepSubmission.state == "queued",
                   ~exists(select(running.id).where(running.session_id == DeepSession.id,
                       running.state.in_(("running", "steering", "waiting_approval")))))
            .join(Message, Message.id == DeepSubmission.message_id)
            .order_by(Message.journal_position)
            .limit(1).with_for_update(of=(DeepSession, DeepSubmission), skip_locked=True))).one_or_none()
        if claimed is not None:
            claimed[0].state = "running"
            claimed[0].lease_until = now + _LEASE
            claimed[0].lease_token = uuid4()
        await db.commit()
    for item, session in expired:
        if session.driver_code == "claude_embedded":
            await invalidate_authorization_context(session.agent_id, _embedded_context(session.id, item.id))
        await _notify(session.room_id)
    if claimed is None:
        return None
    return claimed[0].id, claimed[1]


async def _heartbeat(submission_id: UUID, lease_token: UUID) -> Literal["running", "stop", "lost"]:
    async with get_db_session() as db:
        item = await db.scalar(select(DeepSubmission).where(DeepSubmission.id == submission_id).with_for_update())
        now = datetime.now(timezone.utc)
        if (item is None or item.state != "running" or item.lease_token != lease_token
                or item.lease_until is None or item.lease_until <= now):
            return "lost"
        item.lease_until = now + _LEASE
        await db.commit()
        return "stop" if item.stop_requested else "running"


def _read_checkpoint(stored: str) -> AgentRunCheckpoint:
    payload = read_checkpoint_payload(stored)
    return AgentRunCheckpoint(
        driver_code=payload["driver_code"], runtime_run_id=payload["runtime_run_id"],
        status=payload["status"], data=payload["data"],
        result=ExecutionResult.model_validate(payload["result"]) if payload.get("result") else None,
    )


async def _persist(
    submission_id: UUID, room_id: UUID, events: list[tuple[str, dict[str, object]]], *,
    state: DeepState = "running", native_session: str | None = None, response_message_id: UUID | None = None,
    native_history: str | None = None,
    failure: DeepFailureInfo | None = None,
    lease_token: UUID | None = None,
) -> None:
    async with get_db_session() as db:
        item = await db.scalar(select(DeepSubmission).where(DeepSubmission.id == submission_id).with_for_update())
        if item is None or item.state in _TERMINAL_STATES or (lease_token is not None and item.lease_token != lease_token):
            return
        if state == "waiting_approval" and item.stop_requested:
            state = "interrupted"
        if failure is not None:
            events = [*events, ("failure", failure.model_dump(mode="json"))]
        for kind, payload in events:
            item.last_sequence += 1
            db.add(DeepEvent(submission_id=submission_id, sequence=item.last_sequence, kind=kind, payload=payload))
        if (native_session or native_history) and item.session_id is not None:
            session = await db.get(DeepSession, item.session_id)
            if session is not None:
                if native_session:
                    session.native_session = native_session[:512]
                if native_history:
                    session.native_history = get_encryption_service().encrypt(native_history)
        if state in _TERMINAL_STATES:
            item.state = state
            item.lease_until = None
            item.lease_token = None
            item.response_message_id = response_message_id
        elif state == "waiting_approval":
            item.state = state
            item.lease_until = None
            item.lease_token = None
        invalidated: tuple[int, str] | None = None
        if state in {"failed", "interrupted"} and item.session_id is not None:
            origin = await db.get(DeepSession, item.session_id)
            if origin is not None and origin.driver_code == "claude_embedded":
                invalidated = origin.agent_id, _embedded_context(origin.id, submission_id)
        await db.commit()
    if invalidated is not None:
        await invalidate_authorization_context(*invalidated)
    await _notify(room_id)


async def _history(session_id: UUID, agent_id: int, message: Message, *, include_media: bool = False) -> tuple[dict[str, Any], ...]:
    db = get_db()
    earlier = aliased(Message)
    paired = (await db.execute(select(earlier, DeepSubmission.response_message_id)
        .join(DeepSubmission, DeepSubmission.message_id == earlier.id)
        .where(DeepSubmission.session_id == session_id, DeepSubmission.state == "completed",
               earlier.journal_position < message.journal_position)
        .order_by(earlier.journal_position.desc()).limit(50))).all()
    reply_ids = [reply for _, reply in paired if reply is not None]
    replies = ({key: text for key, text in (await db.execute(
        select(Message.id, Message.text).where(Message.id.in_(reply_ids)),
    )).all()} if reply_ids else {})
    inputs: dict[UUID, dict[str, Any]] = {}
    if include_media and paired:
        from app.agent.contracts import TaskMessage
        from app.messenger import hydrate_messages

        inputs = {item.id: TaskMessage.from_messenger(item).model_dump(mode="json")
                  for item in await hydrate_messages([source for source, _ in paired])}
    history: list[dict[str, Any]] = []
    for source, reply_id in reversed(paired):
        history.append({**inputs.get(source.id, {}), "text": _deep_input_text(source.text)[:3000], "sender_is_ai": False})
        if reply_id is not None and reply_id in replies:
            history.append({"text": replies[reply_id][:3000], "sender_is_ai": True, "sender_agent_id": agent_id})
    return tuple(history)


async def _send(submission_id: UUID, room_id: UUID, lease_token: UUID, tool_lock: asyncio.Lock) -> None:
    # Keep tool context available across stream yields. Event and heartbeat writes
    # use their own short transactions, so the browser can reconnect mid-stream.
    async with get_db_session() as db:
        row = (await db.execute(select(DeepSubmission, DeepSession, Message).select_from(DeepSubmission)
               .join(DeepSession, DeepSession.id == DeepSubmission.session_id)
               .join(Message, Message.id == DeepSubmission.message_id)
               .where(DeepSubmission.id == submission_id, DeepSubmission.lease_token == lease_token,
                      DeepSubmission.state == "running"))).one_or_none()
        if row is None:
            return
        item, session, message = row
        actor = message.requester_user_id
        if actor is None or not await has_chat_room_access(actor, room_id):
            raise PermissionError("Access to the Deep conversation was revoked.")
        workspace: dict[str, str | None] = {}
        if session.workspace_bound and session.workspace_id is None:
            raise PermissionError("The Deep checkout is no longer available.")
        if session.workspace_id is not None:
            if _workspace_access is None:
                raise PermissionError("The Deep workspace is unavailable.")
            workspace = await _workspace_access(session.workspace_id, actor, room_id, session.agent_id)
        embedded = session.driver_code == "claude_embedded"
        history = (await _history(session.id, session.agent_id, message, include_media=embedded)
                   if embedded or not (session.native_session or session.native_history) else ())
        native_history = get_encryption_service().decrypt(session.native_history) if session.native_history else None
        checkpoint = await asyncio.to_thread(_read_checkpoint, item.encrypted_checkpoint) if item.encrypted_checkpoint else None
        completed_history: str | None = None

        def save_native_history(value: str) -> None:
            nonlocal completed_history
            completed_history = value

        async def admit_inference(model: ResolvedModel) -> ScopedInferenceAdmission:
            return await _admit_embedded_inference(session.id, submission_id, session.agent_id, model, lease_token)

        async def save_checkpoint(value: AgentRunCheckpoint) -> None:
            if value.driver_code != session.driver_code or value.runtime_run_id != str(submission_id):
                raise ValueError("The checkpoint belongs to another Deep submission.")
            sealed = await asyncio.to_thread(
                lambda: get_encryption_service().encrypt(canonical_authorization_snapshot(value)),
            )
            async with get_db_session() as checkpoint_db:
                owned = await checkpoint_db.scalar(select(DeepSubmission).where(
                    DeepSubmission.id == submission_id, DeepSubmission.lease_token == lease_token,
                    DeepSubmission.state == "running", DeepSubmission.lease_until > datetime.now(timezone.utc),
                ).with_for_update())
                if owned is None:
                    raise PermissionError("The Deep submission lease was lost.")
                owned.encrypted_checkpoint = sealed

        from app.messenger import deep_message_file_context

        file_ids, file_uris = await deep_message_file_context(message.id)
        resources = tuple({"uri": uri} for uri in dict.fromkeys((*file_uris, *message.resource_uris)))
        objective = _deep_input_text(message.text)
        links = "\n".join(item["uri"] for item in resources if item["uri"] not in objective)
        if links:
            objective = "\n\n".join(filter(None, (objective, links)))
        if not objective.strip():
            raise ValueError("A direct harness input requires text or a supported attachment.")
        await db.commit()
        target = _session_target(session)
        control = session.control_credential
        if target.metadata.get("authorization_enabled") is True and target.metadata.get("galaris_extensions") is True:
            now = datetime.now(timezone.utc)
            if control is None or session.control_expires_at is None or session.control_expires_at <= now:
                from app.services.facade import issue_deep_runtime_grant

                control = await issue_deep_runtime_grant(session.agent_id, target, session.id)
                session.control_credential = control
                session.control_expires_at = now + timedelta(days=6)
                await db.commit()
        events = stream_deep_submission(
            session_id=session.id, submission_id=submission_id, agent_id=session.agent_id,
            driver_code=session.driver_code, target=target,
            native_session=session.native_session, objective=objective, room_id=room_id,
            credential=session.inference_credential, requester_user_id=actor,
            control_credential=control,
            connection_id=message.connection_id, language=normalize_language(str(message.metadata_.get("language") or "")),
            message_data={"id": str(message.id), "message_id": str(message.id), "file_ids": file_ids,
                          "requester_user_id": actor, **workspace},
            history=history, attachments=resources,
            native_history=native_history, save_native_history=save_native_history,
            admit_inference=admit_inference if session.driver_code == "claude_embedded" else None,
            resume_checkpoint=checkpoint, save_checkpoint=save_checkpoint if session.driver_code == "claude_embedded" else None,
            tool_lock=tool_lock if session.driver_code == "claude_embedded" else None,
        )
        buffers: list[tuple[str, dict[str, object]]] = []
        last_flush = 0.0
        final_text = ""
        final_native: str | None = None
        succeeded = False
        waiting = False
        failure: DeepFailureInfo | None = None
        try:
            async for event in events:
                if event.message is not None:
                    if event.message.native_session_ref:
                        await _persist(submission_id, room_id, [], native_session=event.message.native_session_ref, lease_token=lease_token)
                        continue
                    payload = _public_event(event.message)
                    if event.message.type == "text":
                        for offset in range(0, len(event.message.content), 4000):
                            buffers.append(("text", {"content": event.message.content[offset:offset + 4000]}))
                    else:
                        buffers.append(("activity", payload))
                    now = asyncio.get_running_loop().time()
                    if now - last_flush > 0.12 or len(buffers) >= 16:
                        await _persist(submission_id, room_id, buffers, lease_token=lease_token)
                        buffers.clear()
                        last_flush = now
                if event.result is not None:
                    final_text = event.result.result
                    native = event.result.metadata.get("deep_native_session")
                    final_native = native if isinstance(native, str) else None
                    succeeded = event.result.success
                    waiting = (session.driver_code == "claude_embedded"
                               and event.result.disposition == "waiting_for_authorization")
                    if not succeeded:
                        failure = describe_deep_failure(event.result.failure)
        finally:
            await events.aclose()
            if buffers:
                await _persist(submission_id, room_id, buffers, lease_token=lease_token)
        response_id = None
        stopped = await _heartbeat(submission_id, lease_token)
        if stopped == "lost":
            return
        if stopped == "stop":
            await _persist(submission_id, room_id, [], state="interrupted", native_session=final_native, lease_token=lease_token)
            return
        if waiting:
            async with get_db_session() as active_db:
                sealed = await active_db.scalar(select(DeepSubmission.encrypted_checkpoint).where(
                    DeepSubmission.id == submission_id, DeepSubmission.lease_token == lease_token,
                ))
            if not sealed or not assess_checkpoint(await asyncio.to_thread(_read_checkpoint, sealed)).resumable:
                raise ValueError("The Claude authorization cannot be paused without a durable continuation.")
            await _persist(submission_id, room_id, [], state="waiting_approval", lease_token=lease_token)
            return
        if succeeded and final_text:
            messenger = await get_messenger(message.connection_id)
            try:
                delivered = await messenger.send_to_room(room_id, final_text, reply_to=message.remote_message_id,
                    journal_metadata={"deep_session": str(session.id), "deep_submission": str(submission_id)})
                response_id = delivered.id
            finally:
                await messenger.close()
        await _persist(submission_id, room_id, [], state="completed" if succeeded else "failed",
                       native_session=final_native, response_message_id=response_id,
                       native_history=completed_history if succeeded else None, failure=failure, lease_token=lease_token)


def _public_event(message: AIMessage) -> dict[str, object]:
    return public_ai_message(message).model_dump(mode="json")


async def _steer_next(submission_id: UUID, room_id: UUID) -> None:
    """Forward a queued plain-text input only to a known native Codex turn."""
    async with get_db_session() as db:
        session = await db.scalar(select(DeepSession).join(DeepSubmission).where(
            DeepSubmission.id == submission_id, DeepSubmission.state == "running", DeepSubmission.stop_requested.is_(False),
        ))
        if (session is None or session.target.get("provider_code") != "codex"
                or not session.control_credential or not session.native_session):
            return
        row = (await db.execute(select(DeepSubmission, Message).join(Message, Message.id == DeepSubmission.message_id)
            .where(DeepSubmission.session_id == session.id, DeepSubmission.state == "queued")
            .order_by(Message.journal_position).limit(1).with_for_update(of=DeepSubmission))).one_or_none()
        if row is None:
            return
        queued, message = row
        objective = _deep_input_text(message.text)
        if not objective.strip() or message.resource_uris or message.attachments:
            return
        from app.services.facade import authorization_context_pending

        if (await authorization_context_pending(session.agent_id, f"deep:{session.id}")
                or await _authorization_scope(session.agent_id, f"deep:{session.id}") is None):
            return
        queued.state = "steering"
        queued.lease_until = datetime.now(timezone.utc) + _LEASE
        await db.commit()
        try:
            accepted = await steer_deep_input(session.driver_code, _session_target(session),
                                              session.id, session.control_credential, objective)
        except Exception:
            await _persist(queued.id, room_id, [], state="interrupted")
        else:
            if accepted:
                await _persist(queued.id, room_id, [], state="steered")
            else:
                # A definite 'no active turn' occurs before the native RPC.
                queued.state = "queued"
                queued.lease_until = None
                await db.commit()
                _wake()


async def _run(submission_id: UUID, room_id: UUID) -> None:
    async with get_db_session() as db:
        token = await db.scalar(select(DeepSubmission.lease_token).where(
            DeepSubmission.id == submission_id, DeepSubmission.state == "running",
        ))
    if token is None:
        return
    tool_lock = asyncio.Lock()
    work = asyncio.create_task(_send(submission_id, room_id, token, tool_lock))
    try:
        while not work.done():
            done, _ = await asyncio.wait({work}, timeout=2)
            if done:
                await work
                return
            heartbeat = await _heartbeat(submission_id, token)
            if heartbeat == "stop" and tool_lock.locked():
                continue
            if heartbeat != "running":
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                await _persist(submission_id, room_id, [], state="interrupted", lease_token=token)
                return
            try:
                await _steer_next(submission_id, room_id)
            except Exception as exc:
                logger.warning("Could not check queued Deep input for {} ({})", submission_id, type(exc).__name__)
        await work
    except asyncio.CancelledError:
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)
        await _persist(submission_id, room_id, [], state="interrupted", lease_token=token)
        raise
    except Exception as exc:
        if not work.done():
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            await _persist(submission_id, room_id, [], state="interrupted", lease_token=token)
            return
        logger.warning("Deep submission {} failed ({})", submission_id, type(exc).__name__)
        await _persist(submission_id, room_id, [], state="failed", failure=describe_deep_failure(
            classify_execution_error(exc), error_type=type(exc).__name__, message=str(exc),
        ), lease_token=token)
    finally:
        _wake()


async def _loop() -> None:
    assert _wakeup is not None
    wakeup = _wakeup
    while True:
        wakeup.clear()
        try:
            while len(_workers) < _MAX_ACTIVE and (work := await _claim()) is not None:
                task = asyncio.create_task(_run(*work), name=f"deep:{work[0]}")
                _workers.add(task)
                task.add_done_callback(_workers.discard)
        except Exception:
            logger.exception("Deep scheduler could not claim work")
        try:
            await asyncio.wait_for(wakeup.wait(), timeout=2)
        except TimeoutError:
            pass


async def start_deep() -> None:
    global _supervisor, _wakeup
    if not deep_running():
        from app.services.facade import register_authorization_context_guard, register_authorization_waker

        register_authorization_context_guard("deep", _authorization_scope)
        register_authorization_waker("conversation-deep", _wake_authorization_context)
        _wakeup = asyncio.Event()
        _supervisor = asyncio.create_task(_loop(), name="deep-scheduler")


async def stop_deep() -> None:
    global _supervisor, _wakeup
    tasks = [*_workers, *([_supervisor] if _supervisor is not None else [])]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _supervisor = None
    _wakeup = None


def deep_running() -> bool:
    return _supervisor is not None and not _supervisor.done()
