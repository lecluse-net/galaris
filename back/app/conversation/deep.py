"""Durable direct harness conversations and ordered replay of their visible activity."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, cast
from uuid import UUID

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import exists, select
from sqlalchemy.orm import aliased

from app.agent import AIMessage, ResolvedExecutionTarget, classify_execution_error
from app.agent.facade import deep_execution_target, deep_harness_target, steer_deep_input, stream_deep_submission
from app.messenger import Message, Room, get_messenger, has_chat_room_access
from core.database import get_db, get_db_session
from core.i18n import normalize_language
from core.util import get_encryption_service

from .contracts import public_ai_message
from .deep_failures import DeepFailureInfo, describe_deep_failure, read_deep_failures
from .models import ConversationRoundMessage, DeepEvent, DeepRoomMode, DeepSession, DeepSubmission

DeepState = Literal["queued", "running", "completed", "failed", "interrupted", "cancelled", "steered"]
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
                        DeepSubmission.session_id == session.id, DeepSubmission.state.in_(("queued", "running", "steering")),
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


async def _authorization_scope(agent_id: int, context: str) -> dict[str, object] | None:
    try:
        session_id = UUID(context.removeprefix("deep:"))
        requester = await authorize_deep_runtime(session_id, agent_id)
    except (ValueError, PermissionError):
        return None
    db = get_db()
    session = await db.get(DeepSession, session_id)
    if session is None:
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
    return {"room": str(session.room_id), "workspace": str(session.workspace_id or ""), "requester": requester}


async def deep_room_info(room_id: UUID, viewer_id: int) -> DeepRoomInfo:
    db = get_db()
    enabled = await db.scalar(select(DeepRoomMode.enabled).where(DeepRoomMode.room_id == room_id))
    activity_exists = select(DeepEvent.id).where(
        DeepEvent.submission_id == DeepSubmission.id, DeepEvent.kind == "activity",
    ).exists()
    rows = (await db.execute(select(DeepSubmission, activity_exists)
        .join(DeepSession, DeepSession.id == DeepSubmission.session_id)
        .where(DeepSession.room_id == room_id)
        .order_by(DeepSubmission.created_at.desc(), DeepSubmission.id.desc()).limit(50))).all()
    submissions = [item for item, _ in rows]
    from app.services.facade import pending_context_approvals

    approvals = await pending_context_approvals({f"deep:{item.session_id}" for item in submissions
        if item.session_id is not None and item.state == "running"}, approver_user_id=viewer_id)
    failures = await read_deep_failures(submissions)
    infos = [DeepSubmissionInfo(
        id=item.id, session_id=item.session_id, message_id=item.message_id,
        response_message_id=item.response_message_id, state=item.state, sequence=item.last_sequence,
        stop_requested=item.stop_requested, has_activity=has_activity,
        approvals=approvals.get(f"deep:{item.session_id}", []) if item.state == "running" else [],
        failure=failures.get(item.id),
    ) for item, has_activity in reversed(rows) if item.session_id is not None]
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
    item = await db.scalar(select(DeepSubmission).join(DeepSession)
                           .where(DeepSession.room_id == room_id, DeepSubmission.id == submission_id)
                           .with_for_update(of=DeepSubmission))
    if item is None:
        return False
    if item.state == "queued":
        item.state = "cancelled"
    elif item.state == "running":
        item.stop_requested = True
    await db.commit()
    await _notify(room_id)
    _wake()
    return True


async def _claim() -> tuple[UUID, UUID] | None:
    now = datetime.now(timezone.utc)
    async with get_db_session() as db:
        expired = (await db.execute(select(DeepSubmission, DeepSession.room_id).join(DeepSession)
            .where(DeepSubmission.state.in_(("running", "steering")), DeepSubmission.lease_until <= now)
            .limit(_MAX_ACTIVE).with_for_update(of=DeepSubmission, skip_locked=True))).all()
        for item, _ in expired:
            item.state = "interrupted"
            item.lease_until = None
        running = aliased(DeepSubmission)
        claimed = (await db.execute(select(DeepSubmission, DeepSession.room_id).join(DeepSession)
            .where(DeepSubmission.state == "queued",
                   ~exists(select(running.id).where(running.session_id == DeepSession.id, running.state.in_(("running", "steering")))))
            .join(Message, Message.id == DeepSubmission.message_id)
            .order_by(Message.journal_position)
            .limit(1).with_for_update(of=(DeepSession, DeepSubmission), skip_locked=True))).one_or_none()
        if claimed is not None:
            claimed[0].state = "running"
            claimed[0].lease_until = now + _LEASE
        await db.commit()
    for _, room_id in expired:
        await _notify(room_id)
    if claimed is None:
        return None
    return claimed[0].id, claimed[1]


async def _heartbeat(submission_id: UUID) -> Literal["running", "stop", "lost"]:
    async with get_db_session() as db:
        item = await db.scalar(select(DeepSubmission).where(DeepSubmission.id == submission_id).with_for_update())
        if item is None or item.state != "running":
            return "lost"
        item.lease_until = datetime.now(timezone.utc) + _LEASE
        await db.commit()
        return "stop" if item.stop_requested else "running"


async def _persist(
    submission_id: UUID, room_id: UUID, events: list[tuple[str, dict[str, object]]], *,
    state: DeepState = "running", native_session: str | None = None, response_message_id: UUID | None = None,
    native_history: str | None = None,
    failure: DeepFailureInfo | None = None,
) -> None:
    async with get_db_session() as db:
        item = await db.scalar(select(DeepSubmission).where(DeepSubmission.id == submission_id).with_for_update())
        if item is None or item.state in _TERMINAL_STATES:
            return
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
            item.response_message_id = response_message_id
        await db.commit()
    await _notify(room_id)


async def _history(session_id: UUID, agent_id: int, message: Message) -> tuple[dict[str, Any], ...]:
    db = get_db()
    earlier = aliased(Message)
    paired = (await db.execute(select(earlier.text, DeepSubmission.response_message_id)
        .join(DeepSubmission, DeepSubmission.message_id == earlier.id)
        .where(DeepSubmission.session_id == session_id, DeepSubmission.state == "completed",
               earlier.journal_position < message.journal_position)
        .order_by(earlier.journal_position.desc()).limit(50))).all()
    reply_ids = [reply for _, reply in paired if reply is not None]
    replies = ({key: text for key, text in (await db.execute(
        select(Message.id, Message.text).where(Message.id.in_(reply_ids)),
    )).all()} if reply_ids else {})
    history: list[dict[str, Any]] = []
    for text, reply_id in reversed(paired):
        history.append({"text": _deep_input_text(text)[:3000], "sender_is_ai": False})
        if reply_id is not None and reply_id in replies:
            history.append({"text": replies[reply_id][:3000], "sender_is_ai": True, "sender_agent_id": agent_id})
    return tuple(history)


async def _send(submission_id: UUID, room_id: UUID) -> None:
    # Keep tool context available across stream yields. Event and heartbeat writes
    # use their own short transactions, so the browser can reconnect mid-stream.
    async with get_db_session() as db:
        row = (await db.execute(select(DeepSubmission, DeepSession, Message).select_from(DeepSubmission)
               .join(DeepSession, DeepSession.id == DeepSubmission.session_id)
               .join(Message, Message.id == DeepSubmission.message_id)
               .where(DeepSubmission.id == submission_id))).one_or_none()
        if row is None:
            return
        _, session, message = row
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
        history = () if session.native_session or session.native_history else await _history(session.id, session.agent_id, message)
        native_history = get_encryption_service().decrypt(session.native_history) if session.native_history else None
        completed_history: str | None = None

        def save_native_history(value: str) -> None:
            nonlocal completed_history
            completed_history = value
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
        )
        buffers: list[tuple[str, dict[str, object]]] = []
        last_flush = 0.0
        final_text = ""
        final_native: str | None = None
        succeeded = False
        failure: DeepFailureInfo | None = None
        try:
            async for event in events:
                if event.message is not None:
                    if event.message.native_session_ref:
                        await _persist(submission_id, room_id, [], native_session=event.message.native_session_ref)
                        continue
                    payload = _public_event(event.message)
                    if event.message.type == "text":
                        for offset in range(0, len(event.message.content), 4000):
                            buffers.append(("text", {"content": event.message.content[offset:offset + 4000]}))
                    else:
                        buffers.append(("activity", payload))
                    now = asyncio.get_running_loop().time()
                    if now - last_flush > 0.12 or len(buffers) >= 16:
                        await _persist(submission_id, room_id, buffers)
                        buffers.clear()
                        last_flush = now
                if event.result is not None:
                    final_text = event.result.result
                    native = event.result.metadata.get("deep_native_session")
                    final_native = native if isinstance(native, str) else None
                    succeeded = event.result.success
                    if not succeeded:
                        failure = describe_deep_failure(event.result.failure)
        finally:
            await events.aclose()
            if buffers:
                await _persist(submission_id, room_id, buffers)
        response_id = None
        stopped = await _heartbeat(submission_id)
        if stopped == "lost":
            return
        if stopped == "stop":
            await _persist(submission_id, room_id, [], state="interrupted", native_session=final_native)
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
                       native_history=completed_history if succeeded else None, failure=failure)


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
    work = asyncio.create_task(_send(submission_id, room_id))
    try:
        while not work.done():
            done, _ = await asyncio.wait({work}, timeout=2)
            if done:
                await work
                return
            if await _heartbeat(submission_id) != "running":
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                await _persist(submission_id, room_id, [], state="interrupted")
                return
            try:
                await _steer_next(submission_id, room_id)
            except Exception as exc:
                logger.warning("Could not check queued Deep input for {} ({})", submission_id, type(exc).__name__)
        await work
    except asyncio.CancelledError:
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)
        await _persist(submission_id, room_id, [], state="interrupted")
        raise
    except Exception as exc:
        if not work.done():
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            await _persist(submission_id, room_id, [], state="interrupted")
            return
        logger.warning("Deep submission {} failed ({})", submission_id, type(exc).__name__)
        await _persist(submission_id, room_id, [], state="failed", failure=describe_deep_failure(
            classify_execution_error(exc), error_type=type(exc).__name__, message=str(exc),
        ))
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
        from app.services.facade import register_authorization_context_guard

        register_authorization_context_guard("deep", _authorization_scope)
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
